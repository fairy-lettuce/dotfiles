"""``pkgnote categorize`` — uncategorized に溜まったパッケージを対話的に正式カテゴリへ移す。

各パッケージについて移動先カテゴリパス(例 ``dev/gui``)を尋ね、package ノードを
``uncategorized`` から目的カテゴリへ移す。package 自身の ``install-if`` / ``skip-if`` /
``first-installed-on`` はそのまま持っていく(どのマシンに入るかは条件だけで決まり、
uncategorized であること自体は判定に影響しないため、移動だけでは結果は変わらない)。

ただし移動先カテゴリ(や祖先)に条件があると AND/OR で合成されるので、移動によって
結果が変わるマシンがあれば表示する。
"""

from __future__ import annotations

from .. import machines as machines_mod
from .. import term
from ..model import FIRST_INSTALLED_ON, INSTALL_IF, SKIP_IF, UNCATEGORIZED
from ..resolve import decide
from . import Context


def _decisions(ctx: Context, name: str) -> dict[str, bool]:
    pkg = ctx.packages.find_package(name)
    return {
        m: decide(pkg, machines_mod.names_for(m, ctx.machines)).install
        for m in sorted(ctx.machines)
    }


def run(machine: str | None = None, dry_run: bool = False) -> int:
    ctx = Context.load(machine)
    unc = ctx.packages.find_category((UNCATEGORIZED,))
    if unc is None or not unc.child_packages():
        print(term.green("uncategorized は空です。"))
        return 0

    pkgs = list(unc.child_packages())
    print(f"uncategorized に {len(pkgs)} 件のパッケージがあります")

    def describe(node) -> str:
        bits = [f"{term.dim('from=')}{node.props.get('from')}"]
        for key in (INSTALL_IF, SKIP_IF, FIRST_INSTALLED_ON):
            if key in node.props:
                bits.append(f"{term.dim(key + '=')}{node.props[key]}")
        return " ".join(bits)

    if dry_run:
        for node in pkgs:
            print("  - " + term.cyan(str(node.pkg_name)) + f" ({describe(node)})")
        print("\n--dry-run: 実際の移動は行いません。")
        return 0

    print("移動先カテゴリを 'dev/gui' の形式で入力。空 Enter/s=スキップ, q=終了。\n")

    moved = 0
    for node in pkgs:
        name = str(node.pkg_name)
        try:
            ans = input(f"[{term.cyan(name)}] {describe(node)} → カテゴリ: ").strip()
        except EOFError:
            break
        if ans in ("", "s"):
            continue
        if ans == "q":
            break

        path = tuple(p for p in ans.strip("/").split("/") if p)
        if not path or path[0] == UNCATEGORIZED or "package" in path:
            print("  " + term.red("無効なカテゴリです。") + "スキップします。")
            continue

        before = _decisions(ctx, name)
        unc.children.remove(node)
        ctx.packages.find_category(path, create=True).children.append(node)
        moved += 1
        print("  " + term.green("✓") + " " + term.cyan(name) + f" を {'/'.join(path)} へ移動")
        after = _decisions(ctx, name)
        for m in sorted(m for m in after if after[m] != before[m]):
            change = "入らなくなります" if before[m] else "入るようになります"
            print("    " + term.yellow("!") + f" 移動先の条件により {m} には{change}")

    if moved:
        ctx.packages.save()
        print(f"\n{moved} 件を移動し packages.kdl を更新しました。")
    else:
        print("\n移動はありませんでした。")
    return 0
