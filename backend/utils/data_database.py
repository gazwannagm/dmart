from object_adapters.base import BaseObjectAdapter
from object_adapters.file import FileAdapter
from object_adapters.sql import SQLAdapter
from utils.settings import settings


AVAILABLE_DATA_REPOSITORIES: dict[str, BaseObjectAdapter] = {
    'file': FileAdapter(),
    'postgres': SQLAdapter()
}


class DataAdapter:
    def __init__(self, adapter: BaseObjectAdapter) -> None:
        self.adapter = adapter


# active_data_adapter: FileAdapter = FileAdapter()
active_data_adapter = AVAILABLE_DATA_REPOSITORIES[settings.active_data_db]
data_adapter: BaseObjectAdapter = DataAdapter(active_data_adapter).adapter
