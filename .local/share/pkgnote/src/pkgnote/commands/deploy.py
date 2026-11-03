"""``pkgnote deploy`` — 条件から算出した集合のうち未導入のものを導入する。

- 現在のマシン(``--machine`` は現在のマシン名と一致する場合のみ可)の名前集合で全パッケージの
  条件を評価し、入るべき集合を backend 別に出して、実機に無いものを導入する。
- pacman は ``sudo pacman -S --needed``、AUR(``from="foreign"``)は ``--aur-helper``
  (既定 paru。yay 互換の ``-S --needed`` を受け付けるもの)、flatpak は ``flatpak install``。
- 既定では ``--noconfirm`` を付けない(pacman/AUR ヘルパーの確認・PKGBUILD レビューを
  そのまま出す)。``--noconfirm`` 指定時のみ pacman/AUR ヘルパーに ``--noconfirm``、
  flatpak に ``-y`` を渡す。
- ``--dry-run`` は実行するコマンドを表示するだけ。削除は行わない。
- pacman / foreign では、未導入の名前を :func:`backends.classify` で分類する。依存として
  入っているもの(``pacman -D --asexplicit`` を案内)と、provides + conflicts/replaces する
  代替パッケージで入っているもの(``paru-bin`` → ``paru``)は導入しない。
"""

from __future__ import annotations

from .. import backends, term
from ..resolve import desired_set
from . import Context


def plan(
    ctx: Context,
    installed: dict[str, set[str]],
    backends_filter: list[str] | None = None,
    satisfaction: dict[str, backends.Satisfaction] | None = None,
) -> dict[str, list[str]]:
    """backend → 導入すべき未導入パッケージ名(ソート済み)。

    ``satisfaction`` を渡すと、pacman / foreign の分類結果をそこに backend 別に入れる。
    """
    desired = desired_set(ctx.packages, ctx.names)
    explicit: set[str] = set().union(*installed.values()) if installed else set()
    targets = ("pacman", "foreign", "flatpak")
    if backends_filter:
        targets = tuple(b for b in targets if b in backends_filter)
    out: dict[str, list[str]] = {}
    for backend in targets:
        missing = desired.get(backend, set()) - installed.get(backend, set())
        if missing and backend in backends.PROVIDES_BACKENDS:
            sat = backends.classify(missing, explicit)
            if satisfaction is not None:
                satisfaction[backend] = sat
            missing = sat.missing
        missing = sorted(missing)
        if missing:
            out[backend] = missing
    return out


def print_satisfied(sats: dict[str, backends.Satisfaction]) -> None:
    deps = sorted(set().union(*(s.as_dependency for s in sats.values()))) if sats else []
    provided = {k: v for s in sats.values() for k, v in s.provided.items()}
    for name, by in sorted(provided.items()):
        print(term.dim(f"  = {name}: {by} で導入済み(provides + conflicts/replaces)"))
    if deps:
        print(term.yellow("[note]") + " 依存として導入済み(導入はしない): " + ", ".join(deps))
        print("  明示インストールにするなら: " + backends.asexplicit_hint(deps))


def run(
    machine: str | None = None,
    dry_run: bool = False,
    backends_filter: list[str] | None = None,
    aur_helper: str = backends.DEFAULT_AUR_HELPER,
    noconfirm: bool = False,
) -> int:
    ctx = Context.load(machine, require_current=True)
    sats: dict[str, backends.Satisfaction] = {}
    to_install = plan(ctx, backends.installed_by_backend(), backends_filter, sats)
    print_satisfied(sats)

    if not to_install:
        print("導入対象なし。すべて同期済みです。")
        return 0

    print(f"deploy 対象 (machine: {ctx.machine}):")
    for backend, names in to_install.items():
        colored = ", ".join(term.cyan(n) for n in names)
        print(f"  [{backend}] {len(names)} 件: {colored}")

    cmds = [
        (backend, backends.install_command(backend, names, aur_helper, noconfirm))
        for backend, names in to_install.items()
    ]

    helper_missing = "foreign" in to_install and not backends.command_available(aur_helper)
    missing_msg = (
        term.red("[error]")
        + f" AUR ヘルパー `{aur_helper}` が見つかりません。AUR のパッケージの導入を飛ばします"
        + "(`--aur-helper` で別のヘルパーを指定できます)"
    )

    if dry_run:
        print("\n--dry-run: 実行するコマンド")
        for _backend, cmd in cmds:
            print(term.dim("  $ " + " ".join(cmd)))
        if helper_missing:
            print(missing_msg)
        return 0

    rc = 0
    for backend, cmd in cmds:
        if backend == "foreign" and helper_missing:
            print(missing_msg)
            rc = 1
            continue
        print(term.dim("  $ " + " ".join(cmd)))
        r = backends.run_command(cmd)
        if r != 0:
            print(term.red("[error]") + f" {backend} の導入が失敗しました (exit {r})")
            rc = r
    return rc
