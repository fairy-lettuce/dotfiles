"""include 解決ロジック(SPEC「優先順位ルール」)。

あるマシンについて、packages.kdl 上の各パッケージが最終的に include=#true /
#false のどちらに評価されるかを算出する。

規則:
- 根(machine ノード)から対象パッケージまでのパス上で、``include`` の明示を持つ
  最も深い(=対象に最も近い)ノードの値が勝つ。
- 中間カテゴリノードは machine 木で省略してよい。省略された階層はスキップして、
  存在する範囲で最深の明示を採用する。
- パス上のどこにも明示が一つも無ければ「未指定」= 設定漏れ(エラーとして報告)。
- ``uncategorized`` 配下だけは特殊: machine 木を見ず、package ノードの
  ``installed_on`` にこのマシン名があれば include=#true とみなす。
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import UNCATEGORIZED, MachineDoc, Package, PackagesDoc


@dataclass(frozen=True)
class Resolution:
    package: Package
    include: bool | None  # True / False / None(=パス上に明示なし=未指定)

    @property
    def undecided(self) -> bool:
        return self.include is None


def resolve_package(pkg: Package, machine: MachineDoc) -> Resolution:
    """単一パッケージの include を解決する。"""
    # uncategorized は特殊ルール(installed_on で判定、machine 木は無視)。
    if pkg.is_uncategorized:
        included = machine.host in pkg.installed_on()
        return Resolution(package=pkg, include=included)

    # machine 木を、pkg.path(カテゴリ列)→ package ノードの順に降りながら、
    # 明示 include を最深優先で拾う。
    explicit: bool | None = None
    node = machine.root
    if "include" in node.props:
        v = node.props["include"]
        if isinstance(v, bool):
            explicit = v

    reached = True
    for name in pkg.path:
        child = node.find_category(name)
        if child is None:
            reached = False
            break
        node = child
        v = node.props.get("include")
        if isinstance(v, bool):
            explicit = v

    if reached:
        pkg_node = node.find_package(pkg.name)
        if pkg_node is not None:
            v = pkg_node.props.get("include")
            if isinstance(v, bool):
                explicit = v

    return Resolution(package=pkg, include=explicit)


def resolve_all(packages: PackagesDoc, machine: MachineDoc) -> list[Resolution]:
    return [resolve_package(p, machine) for p in packages.packages()]


@dataclass
class DesiredSet:
    """あるマシンで include=#true と評価されたパッケージ群(backend 別)。"""

    by_backend: dict[str, set[str]]
    undecided: list[Package]  # パス上に明示が無い設定漏れ

    def all_names(self) -> set[str]:
        out: set[str] = set()
        for names in self.by_backend.values():
            out |= names
        return out


def desired_set(packages: PackagesDoc, machine: MachineDoc) -> DesiredSet:
    """マシンで導入すべきパッケージ集合を backend 別に算出する。"""
    by_backend: dict[str, set[str]] = {}
    undecided: list[Package] = []
    for res in resolve_all(packages, machine):
        if res.undecided:
            undecided.append(res.package)
            continue
        if res.include:
            by_backend.setdefault(res.package.source, set()).add(res.package.name)
    return DesiredSet(by_backend=by_backend, undecided=undecided)
