from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from unstructured.file_utils.filetype import EXT_TO_FILETYPE
from unstructured.ingest.error import SourceConnectionError
from unstructured.ingest.interfaces import (
    BaseConnector,
    BaseConnectorConfig,
    BaseIngestDoc,
    ConnectorCleanupMixin,
    IngestDocCleanupMixin,
    StandardConnectorConfig,
)
from unstructured.ingest.logger import logger
from unstructured.utils import requires_dependencies

if TYPE_CHECKING:
    from office365.onedrive.driveitems.driveItem import DriveItem

MAX_MB_SIZE = 512_000_000


@dataclass
class SimpleOneDriveConfig(BaseConnectorConfig):
    client_id: str
    client_credential: str = field(repr=False)
    user_pname: str
    tenant: str = field(repr=False)
    authority_url: Optional[str] = field(repr=False)
    path: Optional[str] = field(default="")
    recursive: bool = False

    def __post_init__(self):
        if not (self.client_id and self.client_credential and self.user_pname):
            raise ValueError(
                "Please provide all the following mandatory values:"
                "\n-ms-client_id\n-ms-client_cred\n-ms-user-pname",
            )
        self.token_factory = self._acquire_token

    @SourceConnectionError.wrap
    @requires_dependencies(["msal"])
    def _acquire_token(self):
        from msal import ConfidentialClientApplication

        try:
            app = ConfidentialClientApplication(
                authority=f"{self.authority_url}/{self.tenant}",
                client_id=self.client_id,
                client_credential=self.client_credential,
            )
            token = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        except ValueError as exc:
            logger.error("Couldn't set up credentials for OneDrive")
            raise exc
        return token


@dataclass
class OneDriveIngestDoc(IngestDocCleanupMixin, BaseIngestDoc):
    config: SimpleOneDriveConfig
    file_name: str
    file_path: str
    registry_name: str = "onedrive"

    def __post_init__(self):
        self.ext = "".join(Path(self.file_name).suffixes)
        if not self.ext:
            raise ValueError("Unsupported file without extension.")

        if self.ext not in EXT_TO_FILETYPE:
            raise ValueError(
                f"Extension not supported. "
                f"Value MUST be one of {', '.join([k for k in EXT_TO_FILETYPE if k is not None])}.",
            )

        self.server_relative_path = self.file_path + "/" + self.file_name
        self._set_download_paths()

    def _set_download_paths(self) -> None:
        """Parses the folder structure from the source and creates the download and output paths"""
        download_path = Path(f"{self.standard_config.download_dir}")
        output_path = Path(f"{self.standard_config.output_dir}")

        if parent_path := self.file_path:
            download_path = (
                download_path if parent_path == "" else (download_path / parent_path).resolve()
            )
            output_path = (
                output_path if parent_path == "" else (output_path / parent_path).resolve()
            )

        self.download_dir = download_path
        self.download_filepath = (download_path / self.file_name).resolve()
        oname = f"{self.file_name[:-len(self.ext)]}.json"
        self.output_dir = output_path
        self.output_filepath = (output_path / oname).resolve()

    @property
    def filename(self):
        return Path(self.download_filepath).resolve()

    @property
    def _output_filename(self):
        return Path(self.output_filepath).resolve()

    @SourceConnectionError.wrap
    @BaseIngestDoc.skip_if_file_exists
    @requires_dependencies(["office365"], extras="onedrive")
    def get_file(self):
        from office365.graph_client import GraphClient

        try:
            client = GraphClient(self.config.token_factory)
            root = client.users[self.config.user_pname].drive.get().execute_query().root
            self.file = root.get_by_path(self.server_relative_path).get().execute_query()
            fsize = self.file.get_property("size", 0)
            self.output_dir.mkdir(parents=True, exist_ok=True)

            if not self.download_dir.is_dir():
                logger.debug(f"Creating directory: {self.download_dir}")
                self.download_dir.mkdir(parents=True, exist_ok=True)

            if fsize > MAX_MB_SIZE:
                logger.info(f"Downloading file with size: {fsize} bytes in chunks")
                with self.filename.open(mode="wb") as f:
                    self.file.download_session(f, chunk_size=1024 * 1024 * 100).execute_query()
            else:
                with self.filename.open(mode="wb") as f:
                    self.file.download(f).execute_query()
        except Exception as e:
            logger.error(f"Error while downloading and saving file: {self.filename}.")
            logger.error(e)
            return
        logger.info(f"File downloaded: {self.filename}")
        return


class OneDriveConnector(ConnectorCleanupMixin, BaseConnector):
    config: SimpleOneDriveConfig

    def __init__(self, standard_config: StandardConnectorConfig, config: SimpleOneDriveConfig):
        super().__init__(standard_config, config)
        self._set_client()

    @requires_dependencies(["office365"], extras="onedrive")
    def _set_client(self):
        from office365.graph_client import GraphClient

        self.client = GraphClient(self.config.token_factory)

    def _list_objects(self, folder, recursive) -> List["DriveItem"]:
        drive_items = folder.children.get().execute_query()
        files = [d for d in drive_items if d.is_file]
        if not recursive:
            return files
        folders = [d for d in drive_items if d.is_folder]
        for f in folders:
            files += self._list_objects(f, recursive)
        return files

    def _gen_ingest_doc(self, file: "DriveItem") -> OneDriveIngestDoc:
        file_path = file.parent_reference.path.split(":")[-1]
        file_path = file_path[1:] if file_path[0] == "/" else file_path

        return OneDriveIngestDoc(
            self.standard_config,
            self.config,
            file.name,
            file_path,
        )

    def initialize(self):
        pass

    def get_ingest_docs(self):
        root = self.client.users[self.config.user_pname].drive.get().execute_query().root
        if fpath := self.config.path:
            root = root.get_by_path(fpath).get().execute_query()
            if root is None or not root.is_folder:
                raise ValueError(f"Unable to find directory, given: {fpath}")
        files = self._list_objects(root, self.config.recursive)
        return [self._gen_ingest_doc(f) for f in files]
