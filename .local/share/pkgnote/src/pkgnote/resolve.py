"""条件の解決: あるマシンに各パッケージを入れるかどうか。

規則(SPEC「条件式」):
- 根 → package のパス上にある条件をすべて合成する。
  - 実効 install = パス上の全 ``install-if`` の AND(1 つも無ければ真)
  - 実効 skip    = パス上の全 ``skip-if`` の OR(1 つも無ければ偽)
- 入れる ⇔ 実効 install かつ not 実効 skip。条件がどこにも無ければ全マシンに入る。
- カテゴリ(``uncategorized`` を含む)に属していること自体は判定に影響しない。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import expr
from .model import Package, PackagesDoc


@dataclass(frozen=True)
class Decision:
    package: Package
    install: bool
    # 内訳(fetch が「どこを直せば結果が変わるか」を判断するのに使う)
    category_install: bool  # カテゴリ側 install-if の AND
    own_install: bool  # package 自身の install-if(無ければ真)
    category_skip: bool  # カテゴリ側 skip-if の OR
    own_skip: bool  # package 自身の skip-if(無ければ偽)


def decide(pkg: Package, names: set[str]) -> Decision:
    def inst(c) -> bool:
        return c.install is None or c.install.eval(names)

    def skip(c) -> bool:
        return c.skip is not None and c.skip.eval(names)

    cat_i = all(inst(c) for c in pkg.category_conds)
    own_i = inst(pkg.own)
    cat_s = any(skip(c) for c in pkg.category_conds)
    own_s = skip(pkg.own)
    return Decision(
        package=pkg,
        install=cat_i and own_i and not (cat_s or own_s),
        category_install=cat_i,
        own_install=own_i,
        category_skip=cat_s,
        own_skip=own_s,
    )


def desired_set(packages: PackagesDoc, names: set[str]) -> dict[str, set[str]]:
    """マシン(名前集合 ``names``)に入れるべきパッケージ集合を backend 別に返す。"""
    by_backend: dict[str, set[str]] = {}
    for pkg in packages.packages():
        if decide(pkg, names).install:
            by_backend.setdefault(pkg.source, set()).add(pkg.name)
    return by_backend


def unknown_names(packages: PackagesDoc, known: set[str]) -> list[tuple[str, str]]:
    """条件式に現れる未知の名前を ``(ノードパス, 名前)`` で列挙する。

    未知 = どのマシンの論理名でも、どのマシンの導出クラスでもない名前。
    将来の属性を先回りして書けるよう、エラーではなく警告として扱う。
    """
    out: list[tuple[str, str]] = []
    for c in packages.all_conds():
        for e in (c.install, c.skip):
            if e is None:
                continue
            for n in sorted(expr.names_in(e) - known):
                out.append((c.where, n))
    return out
