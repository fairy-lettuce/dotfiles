"""ドメインモデル: packages.kdl と machine_*.kdl を木として読み、
パッケージ一覧やカテゴリパスを取り出す層。

- packages.kdl: トップレベルにラッパーを置かず、カテゴリノードが並ぶ。
  カテゴリはネストでき、末端に ``package "<name>" from="..."`` が並ぶ。
- machine_$HOST.kdl: 単一の ``machine "<name>" { ... }`` ノードの下に、
  packages.kdl のカテゴリツリーを反映したノードが並び、``include=#true/#false``
  を持つ。

いずれも汎用の :class:`~pkgnote.kdl.KNode` 木として保持し、ここで意味付けする。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import kdl, paths
from .kdl import KNode

# 対応する取得元(from の値)。将来 winget/scoop を追加する余地を残す。
BACKENDS = ("pacman", "foreign", "flatpak")

UNCATEGORIZED = "uncategorized"


@dataclass(frozen=True)
class Package:
    """packages.kdl 上の 1 パッケージ。"""

    name: str
    source: str  # from= の値 (pacman / foreign / flatpak / ...)
    path: tuple[str, ...]  # ルートからの祖先カテゴリ名(package ノード自身は含まない)
    alias: str | None = None
    node: KNode = field(default=None, repr=False, compare=False)  # 元ノード(書き戻し用)

    @property
    def is_uncategorized(self) -> bool:
        return bool(self.path) and self.path[0] == UNCATEGORIZED

    @property
    def display(self) -> str:
        return f"{self.name} ({self.alias})" if self.alias else self.name

    def installed_on(self) -> set[str]:
        """uncategorized 用: ``installed_on "<machine>"`` 子ノードの集合。"""
        result: set[str] = set()
        if self.node is not None:
            for c in self.node.children:
                if c.name == "installed_on" and c.args:
                    result.add(str(c.args[0]))
        return result


@dataclass
class PackagesDoc:
    """packages.kdl 全体。トップレベルはカテゴリノードの列。"""

    roots: list[KNode] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "PackagesDoc":
        return cls(roots=kdl.load_file(path or paths.packages_file()))

    def save(self, path: Path | None = None) -> None:
        kdl.dump_file(
            path or paths.packages_file(),
            self.roots,
            header="pkgnote packages.kdl — 手動編集可(pkgnote fetch/categorize が追記)",
        )

    def packages(self) -> list[Package]:
        """全カテゴリを DFS して全 package を列挙する。"""
        result: list[Package] = []

        def walk(node: KNode, path: tuple[str, ...]) -> None:
            for child in node.children:
                if child.name == "package":
                    pname = child.pkg_name
                    if pname is None:
                        continue
                    src = child.props.get("from")
                    alias = child.props.get("alias")
                    result.append(
                        Package(
                            name=pname,
                            source=str(src) if src is not None else "pacman",
                            path=path,
                            alias=str(alias) if isinstance(alias, str) else None,
                            node=child,
                        )
                    )
                elif child.name != "installed_on":
                    walk(child, path + (child.name,))

        for root in self.roots:
            walk(root, (root.name,))
        return result

    def find_category(self, path: tuple[str, ...], create: bool = False) -> KNode | None:
        """カテゴリパス(例: ("dev", "gui"))のノードを返す。create で不足分を作る。"""
        siblings = self.roots
        node: KNode | None = None
        for name in path:
            found = next(
                (n for n in siblings if n.name == name and n.name not in ("package", "installed_on")),
                None,
            )
            if found is None:
                if not create:
                    return None
                found = KNode(name=name)
                siblings.append(found)
            node = found
            siblings = node.children
        return node

    def find_package(self, name: str) -> Package | None:
        for p in self.packages():
            if p.name == name:
                return p
        return None


@dataclass
class MachineDoc:
    """machine_$HOST.kdl 全体。``machine "<name>" { ... }`` を保持する。"""

    host: str
    root: KNode  # machine ノード

    @classmethod
    def load(cls, host: str, path: Path | None = None) -> "MachineDoc":
        nodes = kdl.load_file(path or paths.machine_file(host))
        root = next((n for n in nodes if n.name == "machine"), None)
        if root is None:
            root = KNode(name="machine", args=[host])
        return cls(host=host, root=root)

    def save(self, path: Path | None = None) -> None:
        kdl.dump_file(
            path or paths.machine_file(self.host),
            [self.root],
            header=f"machine_{self.host}.kdl — {self.host} の導入意図(pkgnote 管理)",
        )

    def category_node(self, path: tuple[str, ...], create: bool = False) -> KNode | None:
        """machine 木の中でカテゴリパスに対応するノードを返す。"""
        node = self.root
        for name in path:
            found = node.find_category(name)
            if found is None:
                if not create:
                    return None
                found = KNode(name=name)
                node.children.append(found)
            node = found
        return node

    def package_node(
        self, path: tuple[str, ...], pkg_name: str, create: bool = False
    ) -> KNode | None:
        """カテゴリパス配下の ``package "<name>"`` ノードを返す。"""
        parent = self.category_node(path, create=create)
        if parent is None:
            return None
        found = parent.find_package(pkg_name)
        if found is None and create:
            found = KNode(name="package", args=[pkg_name])
            parent.children.append(found)
        return found
