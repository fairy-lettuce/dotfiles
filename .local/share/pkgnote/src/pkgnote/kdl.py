"""KDL 入出力層。

パースは ``ckdl``(C 実装 bindings, KDL 2.0 準拠)を使うが、書き戻しは自前の
正準シリアライザを使う。理由:

- ckdl の ``Document.dump()`` は「ノード名・プロパティキーは裸、文字列の値だけ
  クオート」という SPEC のスタイルを出力できない
  (``prefer_bare_identifiers`` は値のクオートまで外し、``quote_all_identifiers``
  はキーやノード名までクオートしてしまう)。
- ``dump()`` はコメントも失う。

pkgnote が扱う木は「カテゴリ名 / ``package`` / ``installed_on`` / ``machine``」の
ノードと、文字列・真偽値・null の値だけという限定された構造なので、SPEC のスタイルを
決定論的に出力する自前エミッタは小さく書けて、かつ git 差分が安定する。

トレードオフ: 機械が書き換えるファイル(packages.kdl / machine_*.kdl)では
ユーザーの任意コメントは round-trip されない。ファイル先頭の生成ヘッダのみ扱う。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import ckdl

# KDL のスカラー値。pkgnote では実質 str / bool / None のみを使う。
Scalar = str | bool | int | float | None

# パッケージ/カテゴリノードのプロパティを出力する際の正準順序。
# ここに無いキーは末尾にアルファベット順で続ける(将来の拡張に備える)。
_PROP_ORDER = ("from", "alias", "first_installed_on", "include")

# 裸で出力してよい識別子(ノード名・プロパティキー)の保守的なパターン。
# これに合致しないものはクオートする。KDL2 では true/false/null 等は要 ``#`` だが
# pkgnote のノード名・キーには現れないので個別対応しない。
_BARE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_+.\-]*$")


class KdlError(Exception):
    """KDL の読み込み失敗。CLI 層でトレースバック無しに表示するための例外。

    ckdl の ``ParseError`` は位置情報を持たない(メッセージ文字列だけ)ので、
    ここで「どのファイルか」と「波括弧が閉じていない疑いのある行」を補って投げ直す。
    """


@dataclass
class KNode:
    """KDL ノードの可変表現。ckdl のノードをそのまま写し取る汎用コンテナ。"""

    name: str
    args: list[Scalar] = field(default_factory=list)
    props: dict[str, Scalar] = field(default_factory=dict)
    children: list["KNode"] = field(default_factory=list)

    @classmethod
    def from_ckdl(cls, node) -> "KNode":
        return cls(
            name=node.name,
            args=list(node.args),
            props=dict(node.properties),
            children=[cls.from_ckdl(c) for c in node.children],
        )

    # --- 便利アクセサ(ドメイン層から使う) -------------------------------

    def is_package(self) -> bool:
        return self.name == "package"

    @property
    def pkg_name(self) -> str | None:
        """``package "<name>"`` の第一引数(パッケージ名)。"""
        if self.name == "package" and self.args:
            return str(self.args[0])
        return None

    def child_categories(self) -> list["KNode"]:
        """カテゴリ子ノード(``package``/``installed_on`` 以外)。"""
        return [c for c in self.children if c.name not in ("package", "installed_on")]

    def child_packages(self) -> list["KNode"]:
        return [c for c in self.children if c.name == "package"]

    def find_category(self, name: str) -> "KNode | None":
        for c in self.children:
            if c.name == name and c.name not in ("package", "installed_on"):
                return c
        return None

    def find_package(self, pkg_name: str) -> "KNode | None":
        for c in self.children:
            if c.name == "package" and c.pkg_name == pkg_name:
                return c
        return None


# --------------------------------------------------------------------------
# パース
# --------------------------------------------------------------------------


def _scan_braces(text: str) -> tuple[list[int], int | None]:
    """波括弧の対応を走査する。

    文字列リテラル(``"..."``, エスケープ対応)と ``//`` 行コメント・``/* */``
    ブロックコメントの中は数えない。戻り値は
    ``(閉じられていない '{' の行番号リスト, 対応する '{' の無い '}' の行番号)``。
    """
    open_lines: list[int] = []
    stray_close: int | None = None
    line = 1
    i = 0
    n = len(text)
    in_str = False
    in_line_comment = False
    block_depth = 0
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            in_line_comment = False
            i += 1
            continue
        if in_line_comment:
            i += 1
            continue
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if block_depth:
            if text.startswith("/*", i):
                block_depth += 1
                i += 2
                continue
            if text.startswith("*/", i):
                block_depth -= 1
                i += 2
                continue
            i += 1
            continue
        if text.startswith("//", i):
            in_line_comment = True
            i += 2
            continue
        if text.startswith("/*", i):
            block_depth = 1
            i += 2
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            open_lines.append(line)
        elif ch == "}":
            if open_lines:
                open_lines.pop()
            elif stray_close is None:
                stray_close = line
        i += 1
    return open_lines, stray_close


def _line_text(text: str, lineno: int) -> str:
    lines = text.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


def _brace_hint(text: str) -> str | None:
    """波括弧の不整合から、疑わしい行を人間向けの一文にする(無ければ None)。"""
    open_lines, stray_close = _scan_braces(text)
    if stray_close is not None:
        return f"{stray_close} 行目の `}}` に対応する `{{` がありません"
    if open_lines:
        shown = ", ".join(f"{ln} 行目 (`{_line_text(text, ln)}`)" for ln in open_lines[:3])
        more = f" ほか {len(open_lines) - 3} 件" if len(open_lines) > 3 else ""
        return f"閉じられていない `{{` があります: {shown}{more}"
    return None


def loads(text: str, source: str | None = None) -> list[KNode]:
    """KDL 文字列をトップレベルノードのリストにパースする。

    ``source`` はエラーメッセージに出すファイル名(任意)。
    """
    try:
        doc = ckdl.parse(text)
    except ckdl.ParseError as exc:
        where = f"{source}: " if source else ""
        hint = _brace_hint(text)
        detail = f"{exc}" + (f" — {hint}" if hint else "")
        raise KdlError(f"{where}KDL の解析に失敗しました: {detail}") from exc
    return [KNode.from_ckdl(n) for n in doc.nodes]


def load_file(path) -> list[KNode]:
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return []
    return loads(p.read_text(encoding="utf-8"), source=str(p))


# --------------------------------------------------------------------------
# 正準シリアライズ
# --------------------------------------------------------------------------


def _fmt_value(v: Scalar) -> str:
    if v is True:
        return "#true"
    if v is False:
        return "#false"
    if v is None:
        return "#null"
    if isinstance(v, str):
        esc = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{esc}"'
    return str(v)  # int / float(通常は現れない)


def _fmt_ident(name: str) -> str:
    """ノード名・プロパティキー。裸で出せるならそのまま、無理ならクオート。"""
    if _BARE_IDENT.match(name):
        return name
    esc = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{esc}"'


def _ordered_props(props: dict[str, Scalar]) -> list[tuple[str, Scalar]]:
    def key(k: str):
        return (_PROP_ORDER.index(k) if k in _PROP_ORDER else len(_PROP_ORDER), k)

    return [(k, props[k]) for k in sorted(props, key=key)]


def _emit(node: KNode, depth: int, out: list[str]) -> None:
    pad = "    " * depth
    parts = [_fmt_ident(node.name)]
    parts += [_fmt_value(a) for a in node.args]
    parts += [f"{_fmt_ident(k)}={_fmt_value(v)}" for k, v in _ordered_props(node.props)]
    line = pad + " ".join(parts)
    if node.children:
        out.append(line + " {\n")
        _emit_children(node.children, depth + 1, out)
        out.append(pad + "}\n")
    else:
        out.append(line + "\n")


def _emit_children(nodes: list[KNode], depth: int, out: list[str]) -> None:
    # ブロックノード(子を持つ)同士・ブロックとリーフの境目は空行で区切り、
    # 連続するリーフ(package 等)は詰める。SPEC の例のような可読性を再現する。
    for i, node in enumerate(nodes):
        if i > 0:
            prev = nodes[i - 1]
            if prev.children or node.children:
                out.append("\n")
        _emit(node, depth, out)


def dumps(nodes: list[KNode], header: str | None = None) -> str:
    """トップレベルノード列を SPEC スタイルの KDL 文字列にする。"""
    out: list[str] = []
    if header:
        for hline in header.splitlines():
            out.append(f"// {hline}\n" if hline else "//\n")
        out.append("\n")
    _emit_children(nodes, 0, out)
    return "".join(out)


def dump_file(path, nodes: list[KNode], header: str | None = None) -> None:
    from pathlib import Path

    Path(path).write_text(dumps(nodes, header=header), encoding="utf-8")
