import sys
from typing import Any
from datetime import datetime
from db.manticore_db import ManticoreDB
from models.api import Query
from models.core import EntityDTO, Meta, Record
from models.enums import ContentType, SortType, QueryType
from repositories.base_repo import BaseRepo
from utils import db as main_db
from utils.helpers import branch_path, camel_case
from utils.access_control import access_control
from utils.settings import settings


class ManticoreRepo(BaseRepo):
    
    def __init__(self) -> None:
        super().__init__(ManticoreDB())
    
    async def search(
        self, query: Query, user_shortname: str | None = None
    ) -> tuple[int, list[dict[str, Any]]]:
        if query.type != QueryType.search:
            return 0, []

        search_res: list[dict[str, Any]] = []
        total: int = 0

        if not query.filter_schema_names:
            query.filter_schema_names = ["meta"]

        limit = query.limit
        offset = query.offset
        if len(query.filter_schema_names) > 1 and query.sort_by:
            limit += offset
            offset = 0

        query_policies: list[str] | None = None
        if user_shortname:
            query_policies = await access_control.user_query_policies(
                user_shortname=user_shortname,
                space=query.space_name,
                subpath=query.subpath,
            )
        for schema_name in query.filter_schema_names:
            result = await self.db.search(
                space_name=query.space_name,
                branch_name=query.branch_name,
                schema_name=schema_name,
                search=query.search,
                filters={
                    "resource_type": query.filter_types or [],
                    "shortname": query.filter_shortnames or [],
                    "tags": query.filter_tags or [],
                    "subpath": [query.subpath],
                    "query_policies": query_policies,
                    "user_shortname": user_shortname,
                },
                exact_subpath=query.exact_subpath,
                limit=limit,
                offset=offset,
                highlight_fields=list(query.highlight_fields.keys()),
                sort_by=query.sort_by,
                sort_type=query.sort_type or SortType.ascending,
            )

            if result:
                search_res.extend(result[1])
                total += result[0]
        return total, search_res

    async def aggregate(
        self, query: Query, user_shortname: str | None = None
    ) -> list[dict[str, Any]]:
        if not query.aggregation_data:
            return []

        if len(query.filter_schema_names) > 1:
            return []

        query_policies: list[str] | None = None
        if user_shortname:
            query_policies = await access_control.user_query_policies(
                user_shortname=user_shortname,
                space=query.space_name,
                subpath=query.subpath,
            )

        return await self.db.aggregate(
            space_name=query.space_name,
            branch_name=query.branch_name,
            schema_name=query.filter_schema_names[0],
            search=query.search,
            filters={
                "resource_type": query.filter_types or [],
                "shortname": query.filter_shortnames or [],
                "subpath": [query.subpath],
                "query_policies": query_policies,
            },
            load=query.aggregation_data.load,
            group_by=query.aggregation_data.group_by,
            reducers=query.aggregation_data.reducers,
            exact_subpath=query.exact_subpath,
            sort_by=query.sort_by,
            limit=query.limit,
            sort_type=query.sort_type or SortType.ascending,
        )
    
    async def find(self, dto: EntityDTO) -> None | Meta:
        user_document = await self.db.find(dto)

        if not user_document:
            return None

        try:
            return dto.class_type.model_validate(user_document)  # type: ignore
        except Exception as _:
            return None
        # return Meta(shortname="", owner_shortname="")
    
    async def create(
        self, dto: EntityDTO, meta: Meta, payload: dict[str, Any] | None = None
    ) -> None:
        meta_doc_id, meta_json = await self.db.prepare_meta_doc(
            dto.space_name, dto.branch_name, dto.subpath, meta
        )

        if payload is None:
            payload = {}
        if (
            not payload
            and meta.payload
            and meta.payload.content_type == ContentType.json
            and isinstance(meta.payload.body, str)
        ):
            payload = await main_db.load_resource_payload(dto)
            

        meta_json["payload_string"] = await self.generate_payload_string(
            dto, payload
        )

        await self.db.save_at_id(meta_doc_id, meta_json)

        if payload:
            payload_doc_id, payload_json = await self.db.prepare_payload_doc(
                dto,
                meta,
                payload,
            )
            payload_json.update(meta_json)
            await self.db.save_at_id(payload_doc_id, payload_json)
    
    
    async def update(
        self, dto: EntityDTO, meta: Meta, payload: dict[str, Any] | None = None
    ) -> None:
        pass
    
    async def db_doc_to_record(
        self,
        space_name: str,
        db_entry: dict,
        retrieve_json_payload: bool = False,
        retrieve_attachments: bool = False,
        filter_types: list | None = None,
    ) -> Record:
        meta_doc_content = {}
        payload_doc_content = {}
        resource_class = getattr(
            sys.modules["models.core"],
            camel_case(db_entry["resource_type"]),
        )

        for key, value in db_entry.items():
            if key in resource_class.model_fields.keys():
                meta_doc_content[key] = value
            elif key not in self.db.SYS_ATTRIBUTES:
                payload_doc_content[key] = value

        dto = EntityDTO(
            space_name=space_name,
            subpath=db_entry["subpath"],
            shortname=db_entry["shortname"],
            resource_type=db_entry["resource_type"],
        )
        # Get payload db_entry
        if (
                not payload_doc_content
                and retrieve_json_payload
                and "payload_doc_id" in db_entry
        ):
            payload_doc_content = await self.get_payload_doc(
                db_entry["payload_doc_id"], db_entry["resource_type"]
            )

        # Get lock data
        locked_data = await self.get_lock_doc(dto)

        meta_doc_content["created_at"] = datetime.fromtimestamp(
            meta_doc_content["created_at"]
        )
        meta_doc_content["updated_at"] = datetime.fromtimestamp(
            meta_doc_content["updated_at"]
        )
        resource_obj = resource_class.model_validate(meta_doc_content)
        resource_base_record = resource_obj.to_record(
            db_entry["subpath"],
            meta_doc_content["shortname"],
            [],
            db_entry["branch_name"],
        )

        if locked_data:
            resource_base_record.attributes["locked"] = locked_data

        # Get attachments
        entry_path = (
                settings.spaces_folder
                / f"{space_name}/{branch_path(db_entry['branch_name'])}/{db_entry['subpath']}/.dm/{meta_doc_content['shortname']}"
        )
        if retrieve_attachments and entry_path.is_dir():
            resource_base_record.attachments = await main_db.get_entry_attachments(
                subpath=f"{db_entry['subpath']}/{meta_doc_content['shortname']}",
                branch_name=db_entry["branch_name"],
                attachments_path=entry_path,
                filter_types=filter_types,
                retrieve_json_payload=retrieve_json_payload,
            )

        if (
                retrieve_json_payload
                and resource_base_record.attributes["payload"]
                and resource_base_record.attributes["payload"].content_type
                == ContentType.json
        ):
            resource_base_record.attributes["payload"].body = payload_doc_content

        if isinstance(resource_base_record, Record):
            return resource_base_record
        else:
            return Record()
    
    async def tags_query(
        self, query: Query, user_shortname: str | None = None
    ) -> tuple[int, list[Record]]:
        return (0, [])

    async def random_query(
        self, query: Query, user_shortname: str | None = None
    ) -> tuple[int, list[Record]]:
        return (0, [])

    
