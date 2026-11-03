"""``pkgnote status`` — ドリフト検知の表示のみ(書き込みなし)。

条件から算出した「このマシンに入るべき集合」と、実システムの「インストール済み(明示)
集合」を backend ごとに突き合わせ、
- MISSING: 入るべきなのに未インストール(deploy 候補)
- EXTRA:   インストール済みだが条件上は入らない(未登録、または条件が偽)
を出す。カテゴリ側の条件で除外されていて package 側では覆せないものは理由を添える。
"""

from __future__ import annotations

from .. import backends, machines, term
from ..resolve import decide
from . import Context


def run(machine: str | None = None) -> int:
    ctx = Context.load(machine)
    installed = backends.installed_by_backend()
    pkgs = ctx.packages.packages()
    by_name = {p.name: p for p in pkgs}
    decisions = {p.name: decide(p, ctx.names) for p in pkgs}

    print(f"pkgnote status — machine: {ctx.machine}  "
          f"{term.dim('names=')}{' '.join(sorted(ctx.names))}")
    try:
        here = machines.current_machine()
    except machines.MachineError:
        here = None
    if here != ctx.machine:
        print(term.yellow("[note]") + " 比較対象の実機状態はこのシステムのものです"
              f"(現在のマシン: {here or '不明'})")
    print()

    # 記録と違う backend で入っているもの(AUR → 公式への移動など)は MISSING+EXTRA に
    # 二重計上せず、別枠で出す(fetch が from を直す)。
    mismatched: dict[str, str] = {}
    for name, pkg in by_name.items():
        if name in installed.get(pkg.source, set()):
            continue
        actual = [b for b, names in installed.items() if name in names]
        if len(actual) == 1:
            mismatched[name] = actual[0]

    total_missing = total_extra = 0
    for backend in ("pacman", "foreign", "flatpak"):
        want = {n for n, d in decisions.items() if d.install and by_name[n].source == backend}
        have = installed.get(backend, set())
        missing = sorted(n for n in want - have if n not in mismatched)
        extra = sorted(n for n in have - want if mismatched.get(n) != backend)
        total_missing += len(missing)
        total_extra += len(extra)

        print(f"[{backend}] {term.dim('want=')}{len(want)} {term.dim('installed=')}{len(have)}")
        for name in missing:
            print("  " + term.red("- MISSING") + " (条件上は入るが未導入): "
                  + term.cyan(by_name[name].label))
        for name in extra:
            d = decisions.get(name)
            if d is None:
                why = "packages.kdl に未登録"
                shown = name
            else:
                shown = by_name[name].label
                if d.category_skip or not d.category_install:
                    why = "カテゴリ側の条件で除外(package 側では覆せない)"
                elif d.own_skip:
                    why = "skip-if が真"
                else:
                    why = "install-if が偽"
            print("  " + term.yellow("+ EXTRA") + f"   ({why}): " + term.cyan(shown))
        if not missing and not extra:
            print("  " + term.green("= in sync"))
        print()

    if mismatched:
        print(term.yellow("[from 不一致]") + " 記録と違う backend で導入済み(`pkgnote fetch` で from を直せます):")
        for name, actual in sorted(mismatched.items()):
            pkg = by_name[name]
            ok = "" if decisions[name].install else "(しかも条件上は入らない)"
            print(f"  ~ {term.cyan(pkg.label)}: KDL from=\"{pkg.source}\" / 実機 {actual}{ok}")
        print()

    m = term.red(str(total_missing)) if total_missing else "0"
    e = term.yellow(str(total_extra)) if total_extra else "0"
    print(f"summary: MISSING={m} EXTRA={e} FROM-MISMATCH={len(mismatched)}")
    # status は情報表示のみ。ドリフトがあっても成功終了(スクリプトから使いやすく)。
    return 0
