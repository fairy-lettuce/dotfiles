"""CLI 層でトレースバック無しに一行要約して表示する例外の基底。"""

from __future__ import annotations


class PkgnoteError(Exception):
    """利用者が直せる種類の失敗(設定・データの不整合など)。"""
