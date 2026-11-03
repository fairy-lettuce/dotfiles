"""ファイル配置。

- packages.kdl は ``~/.pacman/`` 配下。テスト時は環境変数
  ``PKGNOTE_PACMAN_DIR`` でディレクトリを差し替えられる(実 ``~/.pacman`` に触らない)。
- マシン属性は ``~/.config/machines.toml``(``PKGNOTE_MACHINES_FILE`` で差し替え可)。
- 現在のマシンの論理名は yadm の repo config(``~/.dotfiles/config``)の
  ``local.hostname``(``PKGNOTE_YADM_CONFIG`` で差し替え可)。
"""

from __future__ import annotations

import os
from pathlib import Path


def pacman_dir() -> Path:
    override = os.environ.get("PKGNOTE_PACMAN_DIR")
    if override:
        return Path(override)
    return Path.home() / ".pacman"


def machines_file() -> Path:
    override = os.environ.get("PKGNOTE_MACHINES_FILE")
    if override:
        return Path(override)
    return Path.home() / ".config" / "machines.toml"


def yadm_config_file() -> Path:
    override = os.environ.get("PKGNOTE_YADM_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".dotfiles" / "config"


def packages_file() -> Path:
    return pacman_dir() / "packages.kdl"


def state_dir() -> Path:
    """マシンローカルな状態の置き場(dotfiles 管理外)。

    fetch が「前回観測したインストール済み集合」を覚えておき、今回との差分で
    「インストールした/アンインストールした」を判定するのに使う。
    """
    override = os.environ.get("PKGNOTE_STATE_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "pkgnote"


def seen_file(machine: str) -> Path:
    return state_dir() / f"installed_{machine}.txt"
