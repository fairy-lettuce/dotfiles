"""pkgnote — パッケージ導入メタデータを KDL で管理する個人用ツール。"""

from __future__ import annotations

import sys


def main() -> None:
    from .cli import main as cli_main

    sys.exit(cli_main())
