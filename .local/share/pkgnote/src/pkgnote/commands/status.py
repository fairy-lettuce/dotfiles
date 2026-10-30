"""``pkgnote status`` — ドリフト検知の表示のみ(書き込みなし)。

KDL から算出した「あるべき集合(include=#true)」と、実システムの
「インストール済み(明示)集合」を backend ごとに突き合わせ、
- MISSING: あるべきなのに未インストール(deploy 候補)
- EXTRA:   インストール済みだが KDL では非対象(未登録 or include=#false)
を出す。加えて、パス上に include の明示が一つも無い「未指定」パッケージ
(設定漏れ)を警告する。
"""

from __future__ import annotations

from .. import backends, term
from ..resolve import desired_set
from . import Context


def run(host: str | None = None) -> int:
    ctx = Context.load(host)
    desired = desired_set(ctx.packages, ctx.machine)
    installed = backends.installed_by_backend(ctx.host)

    print(f"pkgnote status — machine: {ctx.host}")
    print()

    total_missing = 0
    total_extra = 0

    for backend in ("pacman", "foreign", "flatpak"):
        want = desired.by_backend.get(backend, set())
        have = installed.get(backend, set())
        missing = sorted(want - have)
        extra = sorted(have - want)
        total_missing += len(missing)
        total_extra += len(extra)

        print(f"[{backend}] {term.dim('want=')}{len(want)} {term.dim('installed=')}{len(have)}")
        for name in missing:
            print("  " + term.red("- MISSING") + " (KDL にあるが未導入): " + term.cyan(name))
        for name in extra:
            print("  " + term.yellow("+ EXTRA") + "   (導入済みだが KDL 非対象): " + term.cyan(name))
        if not missing and not extra:
            print("  " + term.green("= in sync"))
        print()

    if desired.undecided:
        print(term.yellow("[warn]") + f" include 未指定(パス上に明示なし)のパッケージ {len(desired.undecided)} 件:")
        for pkg in desired.undecided:
            path = "/".join(pkg.path)
            print("  " + term.yellow("?") + f" {path}/" + term.cyan(pkg.name))
        print()

    m = term.red(str(total_missing)) if total_missing else "0"
    e = term.yellow(str(total_extra)) if total_extra else "0"
    u = term.yellow(str(len(desired.undecided))) if desired.undecided else "0"
    print(f"summary: MISSING={m} EXTRA={e} UNDECIDED={u}")
    # status は情報表示のみ。ドリフトがあっても成功終了(スクリプトから使いやすく)。
    return 0
