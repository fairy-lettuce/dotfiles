"""実システム側との接点(インストール済み一覧の取得・導入)。

インストール済み(明示)の判定はシステムに直接問い合わせる(root 不要・読み取り専用):

- pacman(公式リポジトリ): ``pacman -Qqen``
- foreign(AUR 等): ``pacman -Qqem``
- flatpak: ``flatpak list --app``

依存で入ったパッケージは ``-e`` で除外される。問い合わせの **失敗** は空集合と区別して
:class:`BackendError` にする(失敗を「全部アンインストールされた」と誤認して fetch が
大量の ``skip-if`` を書かないため)。flatpak コマンド自体が無い場合だけは「flatpak の
アプリは 0 個」として空集合を返す。

常に「このシステム」の状態を表す(``--machine`` で別マシンを指定しても同じ)。
"""

from __future__ import annotations

import shutil
import subprocess

from .errors import PkgnoteError


class BackendError(PkgnoteError):
    """インストール済み一覧の問い合わせに失敗した。"""


def _query(cmd: list[str]) -> set[str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise BackendError(f"`{' '.join(cmd)}` を実行できません: {exc}") from exc
    # pacman -Q は該当 0 件のとき出力なしで exit 1 を返す(エラーではない)
    if res.returncode == 1 and not res.stdout.strip() and not res.stderr.strip():
        return set()
    if res.returncode != 0:
        detail = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else f"exit {res.returncode}"
        raise BackendError(f"`{' '.join(cmd)}` が失敗しました: {detail}")
    return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}


def installed_pacman() -> set[str]:
    names = _query(["pacman", "-Qqen"])
    if not names:
        # 公式リポジトリの明示パッケージが 0 個(base すら無い)は現実的にありえないので失敗扱い
        raise BackendError("`pacman -Qqen` の結果が空です(問い合わせ失敗とみなします)")
    return names


def installed_foreign() -> set[str]:
    return _query(["pacman", "-Qqem"])


def installed_flatpak() -> set[str]:
    if shutil.which("flatpak") is None:
        return set()
    return _query(["flatpak", "list", "--app", "--columns=application"])


def installed_by_backend() -> dict[str, set[str]]:
    """このシステムの backend 別インストール済み(明示)集合。失敗時は BackendError。"""
    return {
        "pacman": installed_pacman(),
        "foreign": installed_foreign(),
        "flatpak": installed_flatpak(),
    }


# --------------------------------------------------------------------------
# 導入操作(deploy から呼ぶ)
# --------------------------------------------------------------------------

DEFAULT_AUR_HELPER = "paru"


def install_command(
    backend: str,
    names: list[str],
    aur_helper: str = DEFAULT_AUR_HELPER,
    noconfirm: bool = False,
) -> list[str] | None:
    """backend ごとの導入コマンドを組み立てる(実行はしない)。

    既定では確認を飛ばさない(pacman/AUR ヘルパーの確認や PKGBUILD レビューをそのまま出す)。
    ``noconfirm`` のときだけ pacman/AUR ヘルパーに ``--noconfirm``、flatpak に ``-y`` を渡す。
    AUR ヘルパーは yay 互換の ``-S --needed`` を受け付けるものなら何でもよい(既定 paru)。
    """
    if not names:
        return None
    pkgs = sorted(names)
    yes = ["--noconfirm"] if noconfirm else []
    if backend == "pacman":
        return ["sudo", "pacman", "-S", "--needed", *yes, *pkgs]
    if backend == "foreign":
        return [aur_helper, "-S", "--needed", *yes, *pkgs]
    if backend == "flatpak":
        return ["flatpak", "install", *(["-y"] if noconfirm else []), *pkgs]
    return None


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(cmd: list[str]) -> int:
    return subprocess.run(cmd, check=False).returncode
