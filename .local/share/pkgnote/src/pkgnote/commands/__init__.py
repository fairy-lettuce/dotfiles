"""サブコマンド群。"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from .. import machines as machines_mod
from .. import term
from ..model import PackagesDoc
from ..resolve import unknown_names


@dataclass
class Context:
    """1 実行分のロード済みデータ。"""

    machine: str  # 対象マシンの論理名
    names: set[str]  # 条件式評価に使う名前集合(論理名 + 導出クラス)
    machines: dict[str, dict]
    packages: PackagesDoc

    @classmethod
    def load(
        cls,
        machine: str | None = None,
        warn_unknown: bool = True,
        require_current: bool = False,
    ) -> Context:
        """``require_current``: 実機の状態を記録・変更するコマンド(fetch/deploy)用。
        ``--machine`` が現在のマシン以外を指していたら拒否する(このシステムの状態を
        別マシンの名義で記録・導入してしまわないため)。"""
        machines = machines_mod.load()
        if require_current:
            current = machines_mod.current_machine()
            if machine is not None and machine != current:
                raise machines_mod.MachineError(
                    f"--machine {machine} は現在のマシン({current})ではありません。"
                    "このコマンドはこのシステムの状態を扱うので、現在のマシンにしか使えません"
                    "(別マシンの集合を見るだけなら `pkgnote status --machine` を使ってください)"
                )
            machine = current
        machine = machine or machines_mod.current_machine()
        names = machines_mod.names_for(machine, machines)
        packages = PackagesDoc.load()
        ctx = cls(machine=machine, names=names, machines=machines, packages=packages)
        if warn_unknown:
            ctx.warn_unknown_names()
        return ctx

    def warn_unknown_names(self) -> None:
        unknown = unknown_names(self.packages, machines_mod.known_names(self.machines))
        for where, name in unknown:
            print(
                term.yellow("[warn]") + f" {where}: 未知の名前 `{name}`"
                "(machines.toml のどのマシン名・属性にも該当しません)",
                file=sys.stderr,
            )
