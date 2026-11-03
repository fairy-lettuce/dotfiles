"""``install-if`` / ``skip-if`` の条件式(小さな手書き再帰下降パーサ)。

文法(空白は無視。AND は必ず ``&`` で明示し、名前の並置は構文エラー):

    or_expr  := and_expr ( "|" and_expr )*
    and_expr := unary ( "&" unary )*
    unary    := "!" unary | primary
    primary  := NAME | "(" or_expr ")"
    NAME     := [A-Za-z0-9_.+-]+   (machines.py の論理名・クラス名の規則より広い。実在しない名前は警告)

優先順位は ``!`` > ``&`` > ``|``。名前はマシンの論理名、または machines.toml の
値であるクラス名(:mod:`pkgnote.machines` 参照)。評価は「名前集合に含まれるか」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import PkgnoteError

_NAME_CHARS = re.compile(r"[A-Za-z0-9_.+\-]+")


class ExprError(PkgnoteError):
    """条件式の構文エラー。``where``(ファイル/ノードパス)は呼び出し側が付ける。"""

    def __init__(self, message: str, text: str, pos: int, where: str | None = None):
        self.message = message
        self.text = text
        self.pos = pos
        self.where = where
        super().__init__(str(self))

    def __str__(self) -> str:
        head = f"{self.where}: " if self.where else ""
        return (
            f"{head}条件式の構文エラー: {self.message}\n"
            f"    {self.text}\n"
            f"    {' ' * self.pos}^"
        )


# --- AST -------------------------------------------------------------------


@dataclass(frozen=True)
class Name:
    name: str

    def eval(self, names: set[str]) -> bool:
        return self.name in names


@dataclass(frozen=True)
class Not:
    operand: Expr

    def eval(self, names: set[str]) -> bool:
        return not self.operand.eval(names)


@dataclass(frozen=True)
class And:
    operands: tuple[Expr, ...]

    def eval(self, names: set[str]) -> bool:
        return all(o.eval(names) for o in self.operands)


@dataclass(frozen=True)
class Or:
    operands: tuple[Expr, ...]

    def eval(self, names: set[str]) -> bool:
        return any(o.eval(names) for o in self.operands)


Expr = Name | Not | And | Or


def names_in(e: Expr) -> set[str]:
    """式に現れる名前の集合。"""
    if isinstance(e, Name):
        return {e.name}
    if isinstance(e, Not):
        return names_in(e.operand)
    out: set[str] = set()
    for o in e.operands:
        out |= names_in(o)
    return out


def to_str(e: Expr) -> str:
    """最小限の括弧で文字列化(書き戻し用)。"""

    def go(e: Expr, parent_prec: int) -> str:
        if isinstance(e, Name):
            return e.name
        if isinstance(e, Not):
            return "!" + go(e.operand, 3)
        if isinstance(e, And):
            s, prec = " & ".join(go(o, 2) for o in e.operands), 2
        else:
            s, prec = " | ".join(go(o, 1) for o in e.operands), 1
        return f"({s})" if prec < parent_prec else s

    return go(e, 0)


def or_terms(e: Expr) -> list[Expr]:
    """トップレベルの OR 項に分解する(OR でなければ自身 1 項)。"""
    return list(e.operands) if isinstance(e, Or) else [e]


# --- パーサ -----------------------------------------------------------------


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def error(self, message: str, pos: int | None = None) -> ExprError:
        return ExprError(message, self.text, self.pos if pos is None else pos)

    def skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def peek(self) -> str:
        self.skip_ws()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def parse(self) -> Expr:
        if not self.text.strip():
            raise self.error("式が空です")
        e = self.or_expr()
        ch = self.peek()
        if ch:
            if ch == ")":
                raise self.error("対応する `(` の無い `)` です")
            if _NAME_CHARS.match(ch) or ch in "!(":
                raise self.error(
                    "名前の並置はできません。AND は `&`、OR は `|` で明示してください"
                )
            raise self.error(f"予期しない文字 `{ch}` です")
        return e

    def or_expr(self) -> Expr:
        ops = [self.and_expr()]
        while self.peek() == "|":
            self.pos += 1
            ops.append(self.and_expr())
        return ops[0] if len(ops) == 1 else Or(tuple(ops))

    def and_expr(self) -> Expr:
        ops = [self.unary()]
        while self.peek() == "&":
            self.pos += 1
            ops.append(self.unary())
        return ops[0] if len(ops) == 1 else And(tuple(ops))

    def unary(self) -> Expr:
        if self.peek() == "!":
            self.pos += 1
            return Not(self.unary())
        return self.primary()

    def primary(self) -> Expr:
        ch = self.peek()
        if ch == "(":
            open_pos = self.pos
            self.pos += 1
            e = self.or_expr()
            if self.peek() != ")":
                raise self.error("`)` が足りません(ここで閉じる `(` は左の位置)", open_pos)
            self.pos += 1
            return e
        m = _NAME_CHARS.match(self.text, self.pos)
        if m:
            self.pos = m.end()
            return Name(m.group(0))
        if not ch:
            raise self.error("式が途中で終わっています(名前か `(` が必要です)")
        if ch in "&|":
            raise self.error(f"`{ch}` の左側に名前か `(` が必要です")
        if ch == ")":
            raise self.error("`()` の中が空、または `)` の前に名前がありません")
        raise self.error(f"使えない文字 `{ch}` です(名前は英数字と `_ . + -`)")


def parse(text: str, where: str | None = None) -> Expr:
    """条件式をパースする。失敗時は :class:`ExprError`(``where`` 付き)。"""
    try:
        return _Parser(text).parse()
    except ExprError as exc:
        exc.where = where
        raise
