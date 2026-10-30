"""``pkgnote compress`` — machine 木の圧縮候補の検出・適用、および packages.kdl の整形。

## machine_*.kdl の木の圧縮

fetch が個々の package ノードに ``include=#true`` を書き続けると machine_*.kdl の
木が肥大化する。「あるカテゴリの直下の子が全て同じ ``include`` 値の葉になった」ら、
子を消してカテゴリ自身にその値を持たせる、という圧縮ができる。

ただし無条件の自動圧縮は危険(たまたま今の子が全部同じ、という状態を「将来追加される
ものも含めて全部同じ扱い」に格上げしてしまう)。そこで完全自動化はせず、候補を提示して
1 件ずつ、または ``--all`` で一括確認の上で適用する。

圧縮は葉から順(bottom-up)にカスケードする: 深い部分木を畳むと親も候補になりうる。

## packages.kdl の整形(正式カテゴリの inert メタデータ除去)

``first_installed_on``/``installed_on`` は uncategorized 配下でのみ参照される情報。
categorize 移動時には剥がすようにしたが、それ以前に手動でカテゴリ分けされたパッケージには
残ったままになりうる。これは実害のない inert 情報だが、全パッケージに付いて回ると
packages.kdl の可読性を損なうため、compress 実行時に正式カテゴリ配下から無条件に(危険性の
判断が要らないので確認なしで)剥がす。machine_*.kdl の圧縮とは異なり、これは何も新しい意味を
生まない単純な削除なので、確認プロンプトは挟まない。
"""

from __future__ import annotations

from .. import term
from ..kdl import KNode
from ..model import UNCATEGORIZED
from . import Context


def _is_leaf_with_bool(node: KNode) -> bool:
    return not node.children and isinstance(node.props.get("include"), bool)


def _candidates(root: KNode) -> list[tuple[KNode, tuple[str, ...], bool, int]]:
    """圧縮可能なカテゴリノードを (node, パス, 共通値, 深さ) で列挙。

    条件: machine ルート以外のカテゴリノードで、子を 1 つ以上持ち、その全ての子が
    「明示 include を持つ葉」で、値が全て同一。
    """
    found: list[tuple[KNode, tuple[str, ...], bool, int]] = []

    def walk(node: KNode, path: tuple[str, ...], depth: int) -> None:
        for child in node.children:
            if child.name in ("package", "installed_on"):
                continue
            walk(child, path + (child.name,), depth + 1)
        # ルート(machine)自身は畳まない
        if depth == 0:
            return
        cats_and_pkgs = [c for c in node.children if c.name != "installed_on"]
        if cats_and_pkgs and all(_is_leaf_with_bool(c) for c in cats_and_pkgs):
            values = {c.props["include"] for c in cats_and_pkgs}
            if len(values) == 1:
                found.append((node, path, values.pop(), depth))

    walk(root, (), 0)
    return found


def _apply(node: KNode, value: bool) -> None:
    node.props["include"] = value
    node.children = [c for c in node.children if c.name == "installed_on"]


def _cleanup_categorized_metadata(ctx, dry_run: bool) -> list[str]:
    """正式カテゴリ配下から first_installed_on/installed_on を剥がす。"""
    cleaned: list[str] = []
    for pkg in ctx.packages.packages():
        if pkg.is_uncategorized:
            continue
        node = pkg.node
        has_meta = "first_installed_on" in node.props or any(
            c.name == "installed_on" for c in node.children
        )
        if not has_meta:
            continue
        cleaned.append(f"{'/'.join(pkg.path)}/{term.cyan(pkg.name)}")
        if not dry_run:
            node.props.pop("first_installed_on", None)
            node.children = [c for c in node.children if c.name != "installed_on"]
    return cleaned


def run(host: str | None = None, apply_all: bool = False, dry_run: bool = False) -> int:
    ctx = Context.load(host)

    if not dry_run:
        unc = ctx.packages.find_category((UNCATEGORIZED,))
        unc_count = len(unc.child_packages()) if unc is not None else 0
        if unc_count:
            warn = (
                f"uncategorized に {unc_count} 件の未分類パッケージが残っています。\n"
                "  圧縮すると、後で categorize してこの配下に移したパッケージが、"
                "意図せず include を継承する可能性があります。\n"
                "  続行しますか? [y/N] "
            )
            if not _confirm(warn):
                print("中断しました。")
                return 1

    cleaned = _cleanup_categorized_metadata(ctx, dry_run)
    if cleaned:
        tag = "[dry-run] " if dry_run else ""
        print(f"{tag}packages.kdl: 正式カテゴリの inert メタデータを {len(cleaned)} 件削除:")
        for c in cleaned:
            print("  " + term.dim("-") + f" {c} の first_installed_on/installed_on")
        if not dry_run:
            ctx.packages.save()
    else:
        print("packages.kdl: 削除対象の inert メタデータはありません。")

    skip: set[int] = set()
    applied = 0

    while True:
        cands = [c for c in _candidates(ctx.machine.root) if id(c[0]) not in skip]
        if not cands:
            break
        # 最も深い候補から(カスケードのため)
        node, path, value, _depth = max(cands, key=lambda c: c[3])
        label = "/".join(path)
        n = len([c for c in node.children if c.name != "installed_on"])
        val = term.green("#true") if value else term.red("#false")
        desc = f"{label}: 子 {n} 件が全て include={val} → '{label} include={val}' に畳む"

        if dry_run:
            print(f"  候補: {desc}")
            _apply(node, value)  # メモリ上だけ畳んでカスケードを続ける(保存しない)
            applied += 1
            continue

        if apply_all:
            do = True
        else:
            do = _confirm(f"  {desc}\n  畳みますか? [y/N] ")

        if do:
            _apply(node, value)
            applied += 1
            print("  " + term.green("✓") + f" 畳みました: {label} include={val}")
        else:
            skip.add(id(node))

    if dry_run:
        print(f"\n--dry-run: 圧縮候補 {applied} 件(実際には保存しません)")
        return 0

    if applied:
        ctx.machine.save()
        print(f"{applied} 件を圧縮し machine_{ctx.host}.kdl を更新しました。")
    else:
        print("圧縮候補はありません。")
    return 0


def _confirm(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")
