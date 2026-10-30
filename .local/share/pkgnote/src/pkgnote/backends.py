"""実システム側との接点(インストール済み一覧の取得・導入・削除)。

インストール済みの明示パッケージ判定は SPEC の方針に従い、pacman hook が生成する
``pkglist_$HOST.txt`` / ``pkglist_foreign_$HOST.txt``(``pacman -Qqen`` / ``-Qqem``
の生出力 = 明示インストールのみ)をそのまま入力に使う。依存で入ったパッケージは
これらの txt に出てこないので、自然に除外される。

flatpak には txt が無いので ``flatpak list --app`` を都度クエリする(読み取り専用)。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import paths


def _read_list(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def installed_pacman(host: str | None = None) -> set[str]:
    return _read_list(paths.pkglist_file(host))


def installed_foreign(host: str | None = None) -> set[str]:
    return _read_list(paths.pkglist_foreign_file(host))


def installed_flatpak() -> set[str]:
    if shutil.which("flatpak") is None:
        return set()
    try:
        out = subprocess.run(
            ["flatpak", "list", "--app", "--columns=application"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def installed_by_backend(host: str | None = None) -> dict[str, set[str]]:
    """backend 別のインストール済み(明示)集合。"""
    return {
        "pacman": installed_pacman(host),
        "foreign": installed_foreign(host),
        "flatpak": installed_flatpak(),
    }


# --------------------------------------------------------------------------
# 導入操作(deploy から呼ぶ)。AUR ヘルパーは SPEC 指定の yay。
# --------------------------------------------------------------------------


def install_command(backend: str, names: list[str]) -> list[str] | None:
    """backend ごとの導入コマンドを組み立てる(実行はしない)。"""
    if not names:
        return None
    if backend == "pacman":
        return ["sudo", "pacman", "-S", "--needed", "--noconfirm", *sorted(names)]
    if backend == "foreign":
        return ["yay", "-S", "--needed", "--noconfirm", *sorted(names)]
    if backend == "flatpak":
        return ["flatpak", "install", "-y", *sorted(names)]
    return None


def run_install(backend: str, names: list[str], dry_run: bool = False) -> int:
    from . import term

    cmd = install_command(backend, names)
    if cmd is None:
        return 0
    print(term.dim("  $ " + " ".join(cmd)))
    if dry_run:
        return 0
    return subprocess.run(cmd).returncode
