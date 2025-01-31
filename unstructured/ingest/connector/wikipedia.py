import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

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
    from wikipedia import WikipediaPage


@dataclass
class SimpleWikipediaConfig(BaseConnectorConfig):
    title: str
    auto_suggest: bool


@dataclass
class WikipediaIngestDoc(IngestDocCleanupMixin, BaseIngestDoc):
    config: SimpleWikipediaConfig = field(repr=False)

    @property
    @requires_dependencies(["wikipedia"], extras="wikipedia")
    def page(self) -> "WikipediaPage":
        import wikipedia

        return wikipedia.page(
            self.config.title,
            auto_suggest=self.config.auto_suggest,
        )

    @property
    def filename(self) -> Path:
        raise NotImplementedError()

    @property
    def text(self) -> str:
        raise NotImplementedError()

    @property
    def _output_filename(self):
        raise NotImplementedError()

    def _create_full_tmp_dir_path(self):
        self.filename.parent.mkdir(parents=True, exist_ok=True)

    @SourceConnectionError.wrap
    @BaseIngestDoc.skip_if_file_exists
    def get_file(self):
        """Fetches the "remote" doc and stores it locally on the filesystem."""
        self._create_full_tmp_dir_path()
        logger.debug(f"Fetching {self} - PID: {os.getpid()}")
        with open(self.filename, "w", encoding="utf8") as f:
            f.write(self.text)


@dataclass
class WikipediaIngestHTMLDoc(WikipediaIngestDoc):
    registry_name: str = "wikipedia_html"

    @property
    def filename(self) -> Path:
        return (
            Path(self.standard_config.download_dir)
            / f"{self.page.title}-{self.page.revision_id}.html"
        ).resolve()

    @property
    def text(self):
        return self.page.html()

    @property
    def _output_filename(self):
        return (
            Path(self.standard_config.output_dir)
            / f"{self.page.title}-{self.page.revision_id}-html.json"
        )


@dataclass
class WikipediaIngestTextDoc(WikipediaIngestDoc):
    registry_name: str = "wikipedia_text"

    @property
    def filename(self) -> Path:
        return (
            Path(self.standard_config.download_dir)
            / f"{self.page.title}-{self.page.revision_id}.txt"
        ).resolve()

    @property
    def text(self):
        return self.page.content

    @property
    def _output_filename(self):
        return (
            Path(self.standard_config.output_dir)
            / f"{self.page.title}-{self.page.revision_id}-txt.json"
        )


@dataclass
class WikipediaIngestSummaryDoc(WikipediaIngestDoc):
    registry_name: str = "wikipedia_summary"

    @property
    def filename(self) -> Path:
        return (
            Path(self.standard_config.download_dir)
            / f"{self.page.title}-{self.page.revision_id}-summary.txt"
        ).resolve()

    @property
    def text(self):
        return self.page.summary

    @property
    def _output_filename(self):
        return (
            Path(self.standard_config.output_dir)
            / f"{self.page.title}-{self.page.revision_id}-summary.json"
        )


class WikipediaConnector(ConnectorCleanupMixin, BaseConnector):
    config: SimpleWikipediaConfig

    def __init__(self, config: SimpleWikipediaConfig, standard_config: StandardConnectorConfig):
        super().__init__(standard_config, config)

    def initialize(self):
        pass

    def get_ingest_docs(self):
        return [
            WikipediaIngestTextDoc(self.standard_config, self.config),
            WikipediaIngestHTMLDoc(self.standard_config, self.config),
            WikipediaIngestSummaryDoc(self.standard_config, self.config),
        ]
