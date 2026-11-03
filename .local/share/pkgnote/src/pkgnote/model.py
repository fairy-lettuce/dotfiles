"""ドメインモデル: packages.kdl を木として読み、パッケージ一覧と条件を取り出す層。

- トップレベルにラッパーを置かず、カテゴリノードが並ぶ。カテゴリはネストでき、
  末端に ``package "<name>" from="..."`` が並ぶ。
- カテゴリツリーは「なぜ入れたか」の説明でしかなく、どのマシンに入れるかは
  ``install-if`` / ``skip-if`` 条件(カテゴリにも package にも書ける)だけで決まる。
  ``uncategorized`` も特別扱いしない(fetch の一時置き場というだけ)。
- ``first-installed-on`` は最初に検出されたマシンの記録(履歴。判定には使わない)。

汎用の :class:`~pkgnote.kdl.KNode` 木として保持し、ここで意味付けする。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import expr, kdl, paths
from .errors import PkgnoteError
from .expr import Expr
from .kdl import KNode

# 対応する取得元(from の値)。将来 winget/scoop を追加する余地を残す。
BACKENDS = ("pacman", "foreign", "flatpak")

UNCATEGORIZED = "uncategorized"

INSTALL_IF = "install-if"
SKIP_IF = "skip-if"
FIRST_INSTALLED_ON = "first-installed-on"

# 旧形式(machine_*.kdl 時代)の名残。残っていれば移行前のデータとみなして拒否する。
_LEGACY_PROPS = ("first_installed_on", "include", "install_if", "skip_if", "installed-on")
_LEGACY_NODES = ("installed_on", "installed-on")

HEADER = "pkgnote packages.kdl — 手動編集可(pkgnote fetch/categorize が追記)"


class SchemaError(PkgnoteError):
    """packages.kdl の内容が現行モデルと整合しない(旧形式・同時編集など)。"""


@dataclass(frozen=True)
class Cond:
    """パス上の 1 ノード(カテゴリ or package)が持つ条件。"""

    where: str  # エラー/警告表示用のノードパス
    install: Expr | None
    skip: Expr | None


@dataclass(frozen=True)
class Package:
    """packages.kdl 上の 1 パッケージ。"""

    name: str
    source: str  # from= の値 (pacman / foreign / flatpak / ...)
    path: tuple[str, ...]  # ルートからの祖先カテゴリ名(package ノード自身は含まない)
    alias: str | None = None
    node: KNode = field(default=None, repr=False, compare=False)  # 元ノード(書き戻し用)
    # 根側から順に、カテゴリの条件 … 最後に package 自身の条件。
    conds: tuple[Cond, ...] = field(default=(), repr=False, compare=False)

    @property
    def is_uncategorized(self) -> bool:
        return bool(self.path) and self.path[0] == UNCATEGORIZED

    @property
    def display(self) -> str:
        return f"{self.name} ({self.alias})" if self.alias else self.name

    @property
    def label(self) -> str:
        return "/".join((*self.path, self.name))

    @property
    def own(self) -> Cond:
        return self.conds[-1]

    @property
    def category_conds(self) -> tuple[Cond, ...]:
        return self.conds[:-1]

    @property
    def has_conditions(self) -> bool:
        return any(c.install is not None or c.skip is not None for c in self.conds)


def _cond_of(node: KNode, where: str) -> Cond:
    def get(key: str) -> Expr | None:
        if key not in node.props:
            return None
        v = node.props[key]
        if not isinstance(v, str):
            raise SchemaError(f"{where}: {key} の値は文字列で書いてください(例 {key}=\"ruan\")")
        return expr.parse(v, where=f"{where} の {key}")

    return Cond(where=where, install=get(INSTALL_IF), skip=get(SKIP_IF))


_PACKAGE_PROPS = ("from", "alias", INSTALL_IF, SKIP_IF, FIRST_INSTALLED_ON)
_CATEGORY_PROPS = (INSTALL_IF, SKIP_IF)


def _unknown_prop_error(where: str, key: str, allowed: tuple[str, ...]) -> SchemaError:
    return SchemaError(
        f"{where}: 未知のプロパティ `{key}` です(使えるのは {', '.join(allowed)})。"
        "綴り間違いで条件が無視されるのを防ぐため、読み込みを中止しました"
    )


def _check_package(node: KNode, where: str) -> None:
    if len(node.args) != 1 or not isinstance(node.args[0], str):
        raise SchemaError(f"{where}: package にはパッケージ名を文字列 1 つで書いてください")
    for key, value in node.props.items():
        if key not in _PACKAGE_PROPS:
            raise _unknown_prop_error(where, key, _PACKAGE_PROPS)
        if not isinstance(value, str):
            raise SchemaError(f"{where}: {key} の値は文字列で書いてください")
    src = node.props.get("from", "pacman")
    if src not in BACKENDS:
        raise SchemaError(f"{where}: 未知の from=\"{src}\" です(使えるのは {', '.join(BACKENDS)})")
    if node.children:
        raise SchemaError(f"{where}: package ノードに子ノードは置けません(`{node.children[0].name}`)")


def _check_category(node: KNode, where: str) -> None:
    if node.args:
        raise SchemaError(f"{where}: カテゴリノードに引数は置けません(package の書き忘れ?)")
    for key in node.props:
        if key not in _CATEGORY_PROPS:
            raise _unknown_prop_error(where, key, _CATEGORY_PROPS)


@dataclass
class PackagesDoc:
    """packages.kdl 全体。トップレベルはカテゴリノードの列。"""

    roots: list[KNode] = field(default_factory=list)
    source: Path | None = None
    # 読み込んだ時点のファイル内容(保存時に、他から書き換えられていないかの確認に使う)
    loaded_text: str | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> PackagesDoc:
        p = path or paths.packages_file()
        text = p.read_text(encoding="utf-8") if p.exists() else None
        roots = kdl.loads(text, source=str(p)) if text is not None else []
        doc = cls(roots=roots, source=p, loaded_text=text)
        doc.validate()
        return doc

    def validate(self) -> None:
        """旧形式の名残を拒否し、全条件式をパースして構文エラーを早期に出す。"""
        src = str(self.source or "packages.kdl")

        def walk(node: KNode, path: tuple[str, ...]) -> None:
            here = "/".join(path)
            for key in _LEGACY_PROPS:
                if key in node.props:
                    raise SchemaError(
                        f"{src}: {here} に旧形式のプロパティ `{key}` があります。"
                        "移行前のデータです(`uv run --project ~/.local/share/pkgnote "
                        "python -m pkgnote.migrate_v2` で移行してください)"
                    )
            for c in node.children:
                if c.name in _LEGACY_NODES:
                    raise SchemaError(
                        f"{src}: {here} に旧形式の `{c.name}` ノードがあります。"
                        "移行前のデータです(`python -m pkgnote.migrate_v2` で移行してください)"
                    )
            if node.name == "package":
                _check_package(node, f"{src}: {here}")
                return
            _check_category(node, f"{src}: {here}")
            for c in node.children:
                if c.name == "package":
                    walk(c, path + (f'package "{c.pkg_name}"',))
                else:
                    walk(c, path + (c.name,))

        for root in self.roots:
            if root.name == "package":
                raise SchemaError(
                    f"{src}: package \"{root.pkg_name}\" がトップレベルにあります"
                    "(カテゴリの中に置いてください)"
                )
            walk(root, (root.name,))
        self.packages()  # 条件式の構文チェック

    def save(self, path: Path | None = None) -> None:
        """書き戻す。読み込み後にファイルが他から変更されていたら書かずに失敗する。"""
        p = path or self.source or paths.packages_file()
        current = p.read_text(encoding="utf-8") if p.exists() else None
        if p == self.source and current != self.loaded_text:
            raise SchemaError(
                f"{p} は読み込み後に別の手段で変更されています。上書きせずに中止しました"
                "(もう一度実行してください)"
            )
        text = kdl.dumps(self.roots, header=HEADER)
        # 書き出す内容が自分自身で読み戻せること・パッケージが減っていないことを確認する。
        check = PackagesDoc(roots=kdl.loads(text, source=f"{p} (書き込み予定の内容)"), source=p)
        check.validate()
        before = [x.name for x in self.packages()]
        after = [x.name for x in check.packages()]
        if sorted(before) != sorted(after):
            raise SchemaError(f"{p}: 書き込み予定の内容でパッケージ集合が変わるため中止しました")
        kdl.write_text_atomic(p, text)
        self.loaded_text = text
        self.source = p

    def packages(self) -> list[Package]:
        """全カテゴリを DFS して全 package を列挙する(条件式もここでパース)。"""
        result: list[Package] = []
        src = str(self.source or "packages.kdl")

        def walk(node: KNode, path: tuple[str, ...], conds: tuple[Cond, ...]) -> None:
            for child in node.children:
                if child.name == "package":
                    pname = child.pkg_name
                    if pname is None:
                        continue
                    where = f"{src}: {'/'.join(path)}/package \"{pname}\""
                    src_v = child.props.get("from")
                    alias = child.props.get("alias")
                    result.append(
                        Package(
                            name=pname,
                            source=str(src_v) if src_v is not None else "pacman",
                            path=path,
                            alias=str(alias) if isinstance(alias, str) else None,
                            node=child,
                            conds=conds + (_cond_of(child, where),),
                        )
                    )
                else:
                    sub = path + (child.name,)
                    where = f"{src}: {'/'.join(sub)}"
                    walk(child, sub, conds + (_cond_of(child, where),))

        for root in self.roots:
            where = f"{src}: {root.name}"
            walk(root, (root.name,), (_cond_of(root, where),))
        return result

    def all_conds(self) -> list[Cond]:
        """カテゴリ・package すべての条件(未知名チェック用。重複なし)。"""
        seen: dict[str, Cond] = {}
        for p in self.packages():
            for c in p.conds:
                seen.setdefault(c.where, c)
        return list(seen.values())

    def find_category(self, path: tuple[str, ...], create: bool = False) -> KNode | None:
        """カテゴリパス(例: ("dev", "gui"))のノードを返す。create で不足分を作る。"""
        siblings = self.roots
        node: KNode | None = None
        for name in path:
            found = next((n for n in siblings if n.name == name and n.name != "package"), None)
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
