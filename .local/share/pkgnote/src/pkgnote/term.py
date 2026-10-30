"""端末カラー出力のヘルパー(ANSI)。

- 既定は auto: stdout が TTY のときだけ着色。pacman hook / パイプ経由など非 TTY では
  自動的に無色になる(KDL ファイルや txt に ANSI が混ざらない)。
- ``NO_COLOR``(値は問わず存在するだけ)/ ``PKGNOTE_NO_COLOR`` が設定されていれば無効。
- ``FORCE_COLOR`` が設定されていれば強制有効。
- CLI の ``--color always|never|auto`` で :func:`configure` から上書きできる。
"""

from __future__ import annotations

import os
import sys

_ENABLED = False


def _auto_enabled() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("PKGNOTE_NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"


def configure(mode: str = "auto") -> None:
    """カラー有効/無効を決める。mode: 'auto' | 'always' | 'never'。"""
    global _ENABLED
    if mode == "always":
        _ENABLED = True
    elif mode == "never":
        _ENABLED = False
    else:
        _ENABLED = _auto_enabled()


def _wrap(code: str):
    def paint(s: str) -> str:
        if not _ENABLED:
            return s
        return f"\033[{code}m{s}\033[0m"

    return paint


red = _wrap("31")
green = _wrap("32")
yellow = _wrap("33")
blue = _wrap("34")
magenta = _wrap("35")
cyan = _wrap("36")
bold = _wrap("1")
dim = _wrap("2")


# 既定は auto(import 時点で評価)。CLI が configure() で上書きする。
configure("auto")
