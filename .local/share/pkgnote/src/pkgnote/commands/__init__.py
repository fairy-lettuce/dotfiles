"""サブコマンド群。"""

from __future__ import annotations

from dataclasses import dataclass

from .. import paths
from ..model import MachineDoc, PackagesDoc


@dataclass
class Context:
    """1 実行分のロード済みドキュメント。"""

    host: str
    packages: PackagesDoc
    machine: MachineDoc

    @classmethod
    def load(cls, host: str | None = None) -> "Context":
        host = host or paths.logical_hostname()
        return cls(
            host=host,
            packages=PackagesDoc.load(),
            machine=MachineDoc.load(host),
        )
