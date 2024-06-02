import asyncio
from datetime import datetime
import json
from time import time
from models.core import Meta
import os
import shutil
import sys
import argparse
from utils.helpers import camel_case
from utils.redis_services import RedisServices
from utils.settings import settings


def redis_doc_to_meta(doc: dict) -> Meta:
    meta_doc_content = {}
    resource_class = getattr(
        sys.modules["models.core"],
        camel_case(doc["resource_type"]),
    )
    for key, value in doc.items():
        if key in resource_class.model_fields.keys():
            meta_doc_content[key] = value
    meta_doc_content["created_at"] = datetime.fromtimestamp(
        meta_doc_content["created_at"]
    )
    meta_doc_content["updated_at"] = datetime.fromtimestamp(
        meta_doc_content["updated_at"]
    )
    return resource_class.model_validate(meta_doc_content)


async def archive(space: str, subpath: str, schema: str, timewindow: int):
    """
    Archives records from a specific space, subpath, and schema.

    Args:
        space (str): The name of the space.
        subpath (str): The subpath within the space.
        schema (str): The schema name.

    Returns:
        None
    """
    limit = 1000
    offset = 0
    total = 10000

    initial_time = time()
    async with RedisServices() as redis_services:
        while offset < total:
            redis_res = await redis_services.search(
                space_name=space,
                branch_name=settings.default_branch,
                schema_name=schema,
                search="",
                filters={
                    "subpath": [subpath],
                },
                exact_subpath=True,
                limit=limit,
                offset=offset,
            )
            if not redis_res or redis_res["total"] == 0:
                break
            search_res = redis_res["data"]

            for redis_document in search_res:
                record = json.loads(redis_document)
                # pp(record.get("created_at", ""))
                created_at = datetime.fromtimestamp(record.get("created_at", ""))
                if (datetime.now() - created_at).total_seconds() < 48 * 60 * 60:
                    continue

                # Move payload file
                os.makedirs(f"{settings.spaces_folder}/archive/{space}/{subpath}", exist_ok=True)
                shutil.move(
                    src=f"{settings.spaces_folder}/{space}/{subpath}/{record.get('shortname')}.json",
                    dst=f"{settings.spaces_folder}/archive/{space}/{subpath}/{record.get('shortname')}.json",
                )

                # Move meta folder / files
                os.makedirs(
                    f"{settings.spaces_folder}/archive/{space}/{subpath}/.dm", exist_ok=True
                )
                shutil.move(
                    src=f"{settings.spaces_folder}/{space}/{subpath}/.dm/{record.get('shortname')}",
                    dst=f"{settings.spaces_folder}/archive/{space}/{subpath}/.dm",
                )

                # Delete Payload Doc from Redis
                await redis_services.json().delete(key=record.get("payload_doc_id"))  # type: ignore

                # Delete Meta Doc from Redis
                if "meta_doc_id" in record:
                    await redis_services.json().delete(key=record.get("meta_doc_id"))  # type: ignore
                else:
                    await redis_services.delete_doc(
                        space,
                        settings.default_branch,
                        "meta",
                        record.get("shortname"),
                        record["subpath"],
                    )

            if (time() - initial_time) > timewindow:
                print("Time window exceeded.")
                break
    await RedisServices.POOL.aclose()
    await RedisServices.POOL.disconnect(True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Script for archiving records from different spaces and subpaths."
    )
    parser.add_argument("space", type=str, help="The name of the space")
    parser.add_argument("subpath", type=str, help="The subpath within the space")
    parser.add_argument(
        "schema",
        type=str,
        help="The subpath within the space. Optional, if not provided move everything",
        nargs="?",
    )
    parser.add_argument(
        "timewindow",
        type=int,
        help="Max execution time in seconds. Optional, default 6 hours",
        nargs="?",
    )

    args = parser.parse_args()
    space = args.space
    subpath = args.subpath
    timewindow = (
        args.timewindow * 60 * 60 if args.timewindow else 60 * 60 * 6
    )  # 6 Hours
    schema = args.schema or "meta"

    asyncio.run(archive(space, subpath, schema, timewindow))
    print("Done.")
