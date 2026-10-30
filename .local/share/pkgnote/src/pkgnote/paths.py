"""ファイル配置と論理ホスト名の解決。

配置は SPEC 準拠:
- packages.kdl / machine_$HOST.kdl / pkglist_$HOST.txt はすべて ``~/.pacman/`` 配下。
- テスト時は環境変数 ``PKGNOTE_PACMAN_DIR`` でディレクトリを差し替えられる
  (実 ``~/.pacman`` に触らずに動作確認するため)。

ホスト名は「物理 $HOSTNAME」と「ファイル/ノードで使う論理名」を分離できるよう、
``host-alias.kdl`` があれば物理→論理の対応表として引く(SPEC の host-alias 案の
最小実装)。無ければ物理ホスト名をそのまま論理名として使う。
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

from . import kdl


def pacman_dir() -> Path:
    override = os.environ.get("PKGNOTE_PACMAN_DIR")
    if override:
        return Path(override)
    return Path.home() / ".pacman"


def physical_hostname() -> str:
    return socket.gethostname()


def logical_hostname() -> str:
    """物理ホスト名を host-alias.kdl 経由で論理名へ変換(無ければそのまま)。

    host-alias.kdl の形式(例):
        alias "physical-name" logical="logical-name"
    """
    phys = physical_hostname()
    alias_path = pacman_dir() / "host-alias.kdl"
    if alias_path.exists():
        for node in kdl.load_file(alias_path):
            if node.name == "alias" and node.args and str(node.args[0]) == phys:
                logical = node.props.get("logical")
                if isinstance(logical, str):
                    return logical
    return phys


def packages_file() -> Path:
    return pacman_dir() / "packages.kdl"


def machine_file(host: str | None = None) -> Path:
    return pacman_dir() / f"machine_{host or logical_hostname()}.kdl"


def pkglist_file(host: str | None = None) -> Path:
    return pacman_dir() / f"pkglist_{host or logical_hostname()}.txt"


def pkglist_foreign_file(host: str | None = None) -> Path:
    return pacman_dir() / f"pkglist_foreign_{host or logical_hostname()}.txt"
