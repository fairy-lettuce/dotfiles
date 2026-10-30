"""``pkgnote categorize`` — uncategorized に溜まったパッケージを対話的に正式カテゴリへ移す。

各パッケージについて移動先カテゴリパス(例 ``dev/gui``)を尋ね、packages.kdl 上で
``uncategorized`` から目的カテゴリへ package ノードを移す。``first_installed_on`` /
``installed_on`` は uncategorized 配下でのみ参照される情報なので、移動と同時に剥がす
(残しても実害はないが、正式カテゴリのパッケージ全部に付いて回ると可読性を損なうため)。

移動により判定が installed_on 特殊ルールから machine 木の include 継承に変わるため、
このホストが installed_on に含まれていたパッケージは、現在の導入状態を保つよう
machine_*.kdl の新パスの package ノードに ``include=#true`` を明示する
(installed_on を剥がす前に判定しておく)。
"""

from __future__ import annotations

from .. import term
from ..model import UNCATEGORIZED
from . import Context


def run(host: str | None = None, dry_run: bool = False) -> int:
    ctx = Context.load(host)
    unc = ctx.packages.find_category((UNCATEGORIZED,))
    if unc is None or not unc.child_packages():
        print(term.green("uncategorized は空です。"))
        return 0

    pkgs = list(unc.child_packages())
    print(f"uncategorized に {len(pkgs)} 件のパッケージがあります (machine: {ctx.host})")

    if dry_run:
        for node in pkgs:
            src = node.props.get("from")
            print("  - " + term.cyan(str(node.pkg_name)) + f" ({term.dim('from=')}{src})")
        print("\n--dry-run: 実際の移動は行いません。")
        return 0

    print("移動先カテゴリを 'dev/gui' の形式で入力。空 Enter/s=スキップ, q=終了。\n")

    moved = 0
    machine_changed = False
    for node in pkgs:
        name = node.pkg_name
        src = node.props.get("from")
        installed_on = {
            str(c.args[0]) for c in node.children if c.name == "installed_on" and c.args
        }
        prompt = (f"[{term.cyan(str(name))}] {term.dim('from=')}{src} "
                  f"{term.dim('installed_on=')}{sorted(installed_on) or '-'} → カテゴリ: ")
        try:
            ans = input(prompt).strip()
        except EOFError:
            break
        if ans in ("", "s"):
            continue
        if ans == "q":
            break

        path = tuple(p for p in ans.strip("/").split("/") if p)
        if not path or path[0] == UNCATEGORIZED:
            print("  " + term.red("無効なカテゴリです。") + "スキップします。")
            continue

        # uncategorized から外し、目的カテゴリへ移す
        unc.children.remove(node)
        node.props.pop("first_installed_on", None)
        node.children = [c for c in node.children if c.name != "installed_on"]
        target = ctx.packages.find_category(path, create=True)
        target.children.append(node)
        moved += 1
        print("  " + term.green("✓") + " " + term.cyan(str(name)) + f" を {'/'.join(path)} へ移動")

        # このホストで導入中なら machine 木に include=#true を明示して状態を保つ
        if ctx.host in installed_on:
            mnode = ctx.machine.package_node(path, name, create=True)
            mnode.props["include"] = True
            machine_changed = True

    if moved:
        ctx.packages.save()
        if machine_changed:
            ctx.machine.save()
        print(f"\n{moved} 件を移動し packages.kdl を更新しました。")
    else:
        print("\n移動はありませんでした。")
    return 0
