"""``pkgnote fetch`` — 実システムの状態を KDL に取り込む。

通常は pacman hook / flatpak ラッパーから自動呼び出しされる(手動実行も可)。
SPEC の方針どおり **diff ベース**: 「KDL から算出したあるべき集合」と
「pkglist_*.txt / flatpak list の明示インストール集合」を突き合わせて反映する。
依存で入ったパッケージは txt / ``--app`` に出てこないので自然に除外される。

反映ルール:

追加(実機にあるが KDL 未記録):
  - packages.kdl に未登録 → ``uncategorized/<name>`` に ``from`` +
    ``first_installed_on=<host>`` + ``installed_on "<host>"`` で追加。
  - 既に uncategorized 配下 → ``installed_on`` にこのホストを足す。
  - 既に正式カテゴリ配下で、解決結果が include≠true → machine_*.kdl の
    package ノードに ``include=#true`` を明示(= fetch が正典。カテゴリの
    ``#false`` より個別指定が勝つ)。既に true ならノータッチ。

削除(KDL 上 present だが実機に無い):
  - uncategorized で installed_on にこのホストがある → その ``installed_on`` を外す。
  - 正式カテゴリで **package ノードに明示 include=#true** がある(=以前 fetch/deploy
    で present と記録済み)→ ``include=#false`` に反転。
  - 継承のみで true(package ノードに明示なし)や未指定のものは、削除か未 deploy かを
    diff だけでは区別できないため **書き換えず drift 警告のみ**(手動 deploy を促す)。
"""

from __future__ import annotations

from .. import backends, term
from ..kdl import KNode
from ..model import UNCATEGORIZED
from ..resolve import resolve_package
from . import Context


def run(host: str | None = None, dry_run: bool = False) -> int:
    ctx = Context.load(host)
    installed = backends.installed_by_backend(ctx.host)
    known = {p.name: p for p in ctx.packages.packages()}

    added: list[str] = []
    removed: list[str] = []
    warnings: list[str] = []
    pkg_changed = False
    machine_changed = False

    # --- 追加方向: 実機にあるものを走査 -----------------------------------
    for backend, names in installed.items():
        for name in sorted(names):
            pkg = known.get(name)
            if pkg is None:
                _add_uncategorized(ctx, name, backend)
                added.append(f"uncategorized/{term.cyan(name)} (new, {term.dim('from=')}{backend})")
                pkg_changed = True
                continue
            if pkg.is_uncategorized:
                if ctx.host not in pkg.installed_on():
                    pkg.node.children.append(KNode(name="installed_on", args=[ctx.host]))
                    added.append(f"uncategorized/{term.cyan(name)}: {term.dim('installed_on')} += {ctx.host}")
                    pkg_changed = True
                continue
            # 正式カテゴリ配下: 解決結果が true でなければ package 個別 true を書く。
            res = resolve_package(pkg, ctx.machine)
            if res.include is not True:
                node = ctx.machine.package_node(pkg.path, pkg.name, create=True)
                node.props["include"] = True
                added.append(f"{'/'.join(pkg.path)}/{term.cyan(name)}: "
                             f"{term.dim('include=')}{term.green('#true')} (machine)")
                machine_changed = True

    # --- 削除方向: KDL に present だが実機に無いもの ------------------------
    for pkg in ctx.packages.packages():
        source_installed = installed.get(pkg.source, set())
        if pkg.name in source_installed:
            continue  # 実機にある → 削除方向の対象外

        if pkg.is_uncategorized:
            if ctx.host in pkg.installed_on():
                pkg.node.children = [
                    c
                    for c in pkg.node.children
                    if not (c.name == "installed_on" and c.args and str(c.args[0]) == ctx.host)
                ]
                removed.append(f"uncategorized/{term.cyan(pkg.name)}: {term.dim('installed_on')} -= {ctx.host}")
                pkg_changed = True
            continue

        # 正式カテゴリ: package ノードに明示 true があるものだけ false に反転。
        pkg_node = ctx.machine.package_node(pkg.path, pkg.name, create=False)
        has_explicit_true = pkg_node is not None and pkg_node.props.get("include") is True
        if has_explicit_true:
            pkg_node.props["include"] = False
            removed.append(f"{'/'.join(pkg.path)}/{term.cyan(pkg.name)}: "
                           f"{term.dim('include=')}{term.red('#false')} (machine)")
            machine_changed = True
        else:
            res = resolve_package(pkg, ctx.machine)
            if res.include is True:
                warnings.append(
                    f"{'/'.join(pkg.path)}/{term.cyan(pkg.name)}: KDL では導入対象(継承 true)だが"
                    "実機に無い(deploy 忘れ?)"
                )

    _report(added, removed, warnings, dry_run)

    if dry_run:
        return 0
    if pkg_changed:
        ctx.packages.save()
    if machine_changed:
        ctx.machine.save()
    return 0


def _add_uncategorized(ctx: Context, name: str, backend: str) -> None:
    parent = ctx.packages.find_category((UNCATEGORIZED,), create=True)
    node = KNode(
        name="package",
        args=[name],
        props={"from": backend, "first_installed_on": ctx.host},
        children=[KNode(name="installed_on", args=[ctx.host])],
    )
    parent.children.append(node)


def _report(added, removed, warnings, dry_run) -> None:
    tag = "[dry-run] " if dry_run else ""
    if added:
        print(f"{tag}追加 {len(added)} 件:")
        for a in added:
            print("  " + term.green("+") + f" {a}")
    if removed:
        print(f"{tag}削除 {len(removed)} 件:")
        for r in removed:
            print("  " + term.red("-") + f" {r}")
    if warnings:
        print(f"drift 警告 {len(warnings)} 件:")
        for w in warnings:
            print("  " + term.yellow("!") + f" {w}")
    if not (added or removed or warnings):
        print("変更なし。KDL と実機は同期しています。")
