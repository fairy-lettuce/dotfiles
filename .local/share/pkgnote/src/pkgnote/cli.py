"""pkgnote の CLI ディスパッチ(argparse, 追加依存なし)。"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pkgnote",
        description="パッケージの導入理由・カテゴリ・マシンごとの要否を KDL で管理する",
    )
    p.add_argument("--host", help="論理ホスト名を上書き(既定: host-alias 解決)")
    p.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="カラー出力(既定: auto = TTY のときだけ着色)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="ドリフト検知の表示のみ(書き込みなし)")

    p_deploy = sub.add_parser("deploy", help="include=#true を算出し実際に導入")
    p_deploy.add_argument("--dry-run", action="store_true", help="コマンドを表示するだけ")
    p_deploy.add_argument(
        "--backend",
        choices=("pacman", "foreign", "flatpak"),
        action="append",
        help="対象 backend を限定(複数可)",
    )

    p_fetch = sub.add_parser("fetch", help="実システムの状態を KDL に取り込む")
    p_fetch.add_argument("--dry-run", action="store_true", help="変更内容を表示するだけ")

    p_compress = sub.add_parser("compress", help="machine 木の圧縮候補を検出・適用")
    p_compress.add_argument("--all", action="store_true", help="確認なしで一括適用")
    p_compress.add_argument("--dry-run", action="store_true", help="候補を表示するだけ")

    p_cat = sub.add_parser("categorize", help="uncategorized を対話的に正式カテゴリへ移す")
    p_cat.add_argument("--dry-run", action="store_true", help="変更内容を表示するだけ")

    return p


def main(argv: list[str] | None = None) -> int:
    from . import term
    from .kdl import KdlError

    args = build_parser().parse_args(argv)
    term.configure(args.color)

    # KDL が壊れている場合、pacman hook 経由だと生のトレースバックが
    # トランザクション出力に混ざって読みにくいので、一行の要約に落とす。
    try:
        return _dispatch(args)
    except KdlError as exc:
        print(f"{term.red('error')}: {exc}", file=sys.stderr)
        print(
            term.dim("  KDL を手で直してから再実行してください "
                     "(pacman hook からの失敗はトランザクションに影響しません)。"),
            file=sys.stderr,
        )
        return 1


def _dispatch(args) -> int:
    host = args.host

    if args.cmd == "status":
        from .commands import status

        return status.run(host)
    if args.cmd == "deploy":
        from .commands import deploy

        return deploy.run(host, dry_run=args.dry_run, backends_filter=args.backend)
    if args.cmd == "fetch":
        from .commands import fetch

        return fetch.run(host, dry_run=args.dry_run)
    if args.cmd == "compress":
        from .commands import compress

        return compress.run(host, apply_all=args.all, dry_run=args.dry_run)
    if args.cmd == "categorize":
        from .commands import categorize

        return categorize.run(host, dry_run=args.dry_run)

    return 2


if __name__ == "__main__":
    sys.exit(main())
