"""pkgnote の CLI ディスパッチ(argparse, 追加依存なし)。"""

from __future__ import annotations

import argparse
import sys

from .backends import DEFAULT_AUR_HELPER


def _common(suppress: bool) -> argparse.ArgumentParser:
    """共通オプション。トップレベルにもサブコマンドにも書けるようにする。"""
    d = argparse.SUPPRESS if suppress else None
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--machine",
        default=d,
        help="対象マシンの論理名(既定: yadm の local.hostname)",
    )
    p.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default=argparse.SUPPRESS if suppress else "auto",
        help="カラー出力(既定: auto = TTY のときだけ着色)",
    )
    return p


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pkgnote",
        description="パッケージの導入理由・カテゴリ・マシンごとの導入条件を KDL で管理する",
        parents=[_common(suppress=False)],
    )
    common = [_common(suppress=True)]
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", parents=common, help="ドリフト検知の表示のみ(書き込みなし)")

    p_deploy = sub.add_parser("deploy", parents=common, help="条件上入るべき未導入パッケージを導入")
    p_deploy.add_argument("--dry-run", action="store_true", help="実行するコマンドを表示するだけ")
    p_deploy.add_argument(
        "--backend",
        choices=("pacman", "foreign", "flatpak"),
        action="append",
        help="対象 backend を限定(複数可)",
    )
    p_deploy.add_argument(
        "--aur-helper",
        default=DEFAULT_AUR_HELPER,
        metavar="NAME",
        help=f"AUR ヘルパー(yay 互換の -S --needed を受け付けるもの。既定: {DEFAULT_AUR_HELPER})",
    )
    p_deploy.add_argument(
        "--noconfirm",
        action="store_true",
        help="pacman/AUR ヘルパーに --noconfirm、flatpak に -y を渡す",
    )

    p_fetch = sub.add_parser("fetch", parents=common, help="実システムの状態を KDL に取り込む")
    p_fetch.add_argument("--dry-run", action="store_true", help="変更内容を表示するだけ")
    p_fetch.add_argument(
        "--allow-mass-removal",
        action="store_true",
        help="一度に多数のアンインストールを記録することを許可する(安全弁の解除)",
    )

    p_cat = sub.add_parser(
        "categorize", parents=common, help="uncategorized を対話的に正式カテゴリへ移す"
    )
    p_cat.add_argument("--dry-run", action="store_true", help="変更内容を表示するだけ")

    p_machine = sub.add_parser("machine", parents=common, help="マシンの論理名・クラスを表示")
    p_machine.add_argument(
        "what",
        choices=("name", "classes"),
        help="name = 論理名 / classes = 条件式で使えるクラス(1 行 1 つ)",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    from . import term
    from .errors import PkgnoteError

    args = build_parser().parse_args(argv)
    term.configure(args.color)

    # 設定・データの不整合は、pacman hook 経由だと生のトレースバックが
    # トランザクション出力に混ざって読みにくいので、要約だけ出す。
    try:
        return _dispatch(args)
    except PkgnoteError as exc:
        print(f"{term.red('error')}: {exc}", file=sys.stderr)
        if args.cmd == "fetch":
            print(
                term.dim("  packages.kdl には何も書き込んでいません。直してから再実行してください "
                         "(pacman hook からの失敗はトランザクションに影響しません)。"),
                file=sys.stderr,
            )
        return 1


def _dispatch(args) -> int:
    machine = args.machine

    if args.cmd == "status":
        from .commands import status

        return status.run(machine)
    if args.cmd == "deploy":
        from .commands import deploy

        return deploy.run(
            machine,
            dry_run=args.dry_run,
            backends_filter=args.backend,
            aur_helper=args.aur_helper,
            noconfirm=args.noconfirm,
        )
    if args.cmd == "fetch":
        from .commands import fetch

        return fetch.run(machine, dry_run=args.dry_run, allow_mass_removal=args.allow_mass_removal)
    if args.cmd == "categorize":
        from .commands import categorize

        return categorize.run(machine, dry_run=args.dry_run)
    if args.cmd == "machine":
        from .commands import machine as machine_cmd

        return machine_cmd.run(args.what, machine)

    return 2


if __name__ == "__main__":
    sys.exit(main())
