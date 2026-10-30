"""``pkgnote deploy`` — KDL の意図を実システムへ反映(導入)。

packages.kdl と machine_$HOST.kdl を DFS し、include=#true と評価される
パッケージ一覧を backend 別に算出、未導入のものを一括インストールする。
AUR ヘルパーは yay。uncategorized は installed_on の特殊ルールで判定
(いずれも :func:`pkgnote.resolve.desired_set` が処理済み)。

安全策: 既定では導入予定を提示して y/N 確認を取る。削除は行わない
(EXTRA は status/ fetch 側の管轄)。
"""

from __future__ import annotations

from .. import backends, term
from ..resolve import desired_set
from . import Context


def run(
    host: str | None = None,
    dry_run: bool = False,
    backends_filter: list[str] | None = None,
) -> int:
    ctx = Context.load(host)
    desired = desired_set(ctx.packages, ctx.machine)
    installed = backends.installed_by_backend(ctx.host)

    targets = ("pacman", "foreign", "flatpak")
    if backends_filter:
        targets = tuple(b for b in targets if b in backends_filter)

    to_install: dict[str, list[str]] = {}
    for backend in targets:
        want = desired.by_backend.get(backend, set())
        have = installed.get(backend, set())
        missing = sorted(want - have)
        if missing:
            to_install[backend] = missing

    if desired.undecided:
        print(term.yellow("[warn]") + f" include 未指定のパッケージ {len(desired.undecided)} 件はスキップします "
              "(machine_*.kdl に include を明示してください)")

    if not to_install:
        print("導入対象なし。すべて同期済みです。")
        return 0

    print(f"deploy 対象 (machine: {ctx.host}):")
    for backend, names in to_install.items():
        colored = ", ".join(term.cyan(n) for n in names)
        print(f"  [{backend}] {len(names)} 件: {colored}")

    if dry_run:
        print("\n--dry-run: 実行コマンドのみ表示")
        for backend, names in to_install.items():
            backends.run_install(backend, names, dry_run=True)
        return 0

    if not _confirm("上記を導入しますか?"):
        print("中止しました。")
        return 1

    rc = 0
    for backend, names in to_install.items():
        r = backends.run_install(backend, names, dry_run=False)
        if r != 0:
            print(term.red("[error]") + f" {backend} の導入が失敗しました (exit {r})")
            rc = r
    return rc


def _confirm(prompt: str) -> bool:
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")
