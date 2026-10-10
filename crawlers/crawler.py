import abc
from pathlib import Path
from typing import Dict, Optional

from packaging.version import Version

from apps import AppConfig


class Crawler(abc.ABC):
    name: str

    @staticmethod
    @abc.abstractmethod
    def get_available_versions(app: AppConfig, count: Optional[int] = None) -> Dict[str, Version]:
        """The source's newest releases of the app: `count` of them, or its usual number when None."""
        pass

    @staticmethod
    @abc.abstractmethod
    def download_specific_version(output_path: Path, app: AppConfig, version: Version) -> Path:
        pass
