from dataclasses import dataclass
from typing import Type

from unstructured.ingest.connector.fsspec import (
    FsspecConnector,
    FsspecIngestDoc,
    SimpleFsspecConfig,
)
from unstructured.ingest.error import SourceConnectionError
from unstructured.ingest.interfaces import StandardConnectorConfig
from unstructured.utils import requires_dependencies


@dataclass
class SimpleGcsConfig(SimpleFsspecConfig):
    pass


@dataclass
class GcsIngestDoc(FsspecIngestDoc):
    config: SimpleGcsConfig
    registry_name: str = "gcs"

    @SourceConnectionError.wrap
    @requires_dependencies(["gcsfs", "fsspec"], extras="gcs")
    def get_file(self):
        super().get_file()


@requires_dependencies(["gcsfs", "fsspec"], extras="gcs")
class GcsConnector(FsspecConnector):
    ingest_doc_cls: Type[GcsIngestDoc] = GcsIngestDoc

    def __init__(
        self,
        config: SimpleGcsConfig,
        standard_config: StandardConnectorConfig,
    ) -> None:
        super().__init__(standard_config, config)
