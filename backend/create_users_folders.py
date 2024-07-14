import asyncio
import os
from models.enums import ResourceType
from utils.operational_repo import operational_repo
from models.core import EntityDTO, Folder
from utils.settings import settings


async def main() -> None:  
    users_processed = 0
    folder_processed = 0
    
    users_subpath = settings.spaces_folder / settings.management_space / "users/.dm"
    users_iterator = os.scandir(users_subpath)
    for entry in users_iterator:
        if not entry.is_dir():
            continue
        
        
        folders = [
            ("personal", "people", entry.name),
            ("personal", f"people/{entry.name}", "notifications"),
            ("personal", f"people/{entry.name}", "private"),
            ("personal", f"people/{entry.name}", "protected"),
            ("personal", f"people/{entry.name}", "public"),
            ("personal", f"people/{entry.name}", "inbox"),
        ]
        for folder in folders:
            if (settings.spaces_folder / folder[0] / folder[1] / folder[2]).is_dir():
                continue
            await operational_repo.internal_save_model(
                dto=EntityDTO(
                    space_name=folder[0],
                    subpath=folder[1],
                    shortname=folder[2],
                    resource_type=ResourceType.folder,
                    schema_shortname="folder"
                ),
                meta=Folder(
                    shortname=folder[2],
                    is_active=True,
                    owner_shortname=entry.name
                )
            )
            print(f"Created folder {folder} for user {entry.name}")
            folder_processed += 1
            
        users_processed += 1
            
    users_iterator.close()        
    
    print(f"\n===== DONE ====== \nScanned {users_processed} users,\
    Created {folder_processed} missing folders")
        

if __name__ == "__main__":

    asyncio.run(main())