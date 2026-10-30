# pkgnote

パッケージの導入理由・カテゴリ・マシンごとの要否を KDL で管理する個人用ツール。
仕様は [`SPEC.md`](./SPEC.md)、実装時の配置・運用ルールは [`AGENTS.md`](./AGENTS.md) を参照。

## 配置

- 本体: `~/.local/share/pkgnote/`(このディレクトリ。独立 git リポジトリは作らない)
- エントリーポイント: `~/.local/bin/pkgnote`(`uv run` を呼ぶだけの薄いシム)
- データ:
  - `~/.pacman/packages.kdl` — パッケージの分類マスタ
  - `~/.pacman/machine_$HOSTNAME.kdl` — マシンごとの導入意図(include ツリー)
  - `~/.pacman/pkglist_$HOSTNAME.txt` / `pkglist_foreign_$HOSTNAME.txt` — 既存 hook が
    生成する `pacman -Qqen` / `-Qqem`(明示インストール)の生出力。fetch/status の入力。

## コマンド

```
pkgnote status                 # ドリフト検知の表示のみ(書き込みなし)
pkgnote deploy [--dry-run]     # include=#true を算出し yay/pacman/flatpak で導入
pkgnote fetch  [--dry-run]     # 実システムの状態を KDL に取り込む(通常は hook 自動実行)
pkgnote compress [--all] [--dry-run]  # machine 木の圧縮候補を検出・適用
pkgnote categorize [--dry-run] # uncategorized を対話的に正式カテゴリへ移す
```

共通オプション:
- `--host <name>` — 論理ホスト名を上書き。
- `--color auto|always|never` — カラー出力(既定 `auto` = TTY のときだけ着色)。
  非 TTY(hook 経由・パイプ)や `NO_COLOR` 設定時は自動で無色になり、KDL/txt に ANSI は
  混ざらない。

## 自動取り込み(fetch)

- pacman/AUR: `~/.pacman/pkgnote-fetch.hook`(+ `pkgnote-fetch.sh`)が PostTransaction で
  `pkgnote fetch` を実行。`~/.pacman/` は `pacman.conf` の `HookDir` に登録済みなので
  ファイルを置くだけで有効(`/etc` 配置は不要)。既存 `pkglist*.hook` より辞書順で後に
  走るのでリスト再生成後の最新状態を取り込む。
- flatpak: 宣言的 hook 機構が無いため `~/.config/fish/functions/flatpak.fish` で
  `flatpak` コマンドをラップし、install/uninstall 後に `pkgnote fetch` を呼ぶ。

## 開発

```
uv sync                        # 依存(ckdl)を取得
uv run pkgnote <subcommand>    # 直接実行
PKGNOTE_PACMAN_DIR=/path uv run pkgnote status   # データ置き場を差し替えて安全にテスト
```

## 実装メモ

- KDL のパースは `ckdl`(KDL 2.0 準拠)。ただし書き戻しは `src/pkgnote/kdl.py` の自前
  シリアライザを使う。ckdl の `dump()` は「値だけクオート」スタイルを出せず、コメントも
  失うため、git 差分が安定する正準出力を自前で持つ(トレードオフ: 機械書き換え対象の
  KDL ではユーザーの任意コメントは round-trip されない)。
- include 解決(`src/pkgnote/resolve.py`): 根→パッケージのパス上で最深の明示 `include` が
  勝つ。`uncategorized` のみ `installed_on` による特殊判定。
