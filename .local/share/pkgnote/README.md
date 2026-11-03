# pkgnote

パッケージの導入理由・カテゴリ・マシンごとの導入条件を KDL で管理する個人用ツール。
仕様は [`SPEC.md`](./SPEC.md)、実装時の配置・運用ルールは [`AGENTS.md`](./AGENTS.md) を参照。

## 配置

- 本体: `~/.local/share/pkgnote/`(このディレクトリ。独立 git リポジトリは作らない)
- エントリーポイント: `~/.local/bin/pkgnote`(`uv run` を呼ぶだけの薄いシム)
- データ:
  - `~/.pacman/packages.kdl` — パッケージの分類マスタ兼導入条件(`install-if` / `skip-if`)
  - `~/.config/machines.toml` — マシンの論理名と属性(条件式で使うクラス名の元)
  - `~/.local/state/pkgnote/installed_<machine>.txt` — fetch が前回観測した集合(マシンローカル)

## コマンド

```
pkgnote status                 # ドリフト検知の表示のみ(書き込みなし)
pkgnote deploy [--dry-run] [--noconfirm] [--aur-helper paru]
                               # 条件上入るべき未導入パッケージを pacman/AUR/flatpak で導入
pkgnote fetch  [--dry-run] [--allow-mass-removal]
                               # 実システムの状態を KDL に取り込む(現在は手動実行)
pkgnote categorize [--dry-run] # uncategorized を対話的に正式カテゴリへ移す
pkgnote machine name|classes   # 論理名 / 条件式で使えるクラス名(yadm local.class 用)
```

共通オプション:
- `--machine <name>` — 対象マシンの論理名を上書き(既定は yadm の `local.hostname`)。
  `fetch` / `deploy` はこのシステムの状態を扱うので、現在のマシン名以外は拒否する。
- `--color auto|always|never` — カラー出力(既定 `auto` = TTY のときだけ着色)。
  非 TTY(hook 経由・パイプ)や `NO_COLOR` 設定時は自動で無色になり、KDL/txt に ANSI は
  混ざらない。

## 自動取り込み(fetch)

- 入力はその場で問い合わせる: `pacman -Qqen`(公式・明示)/ `pacman -Qqem`(AUR 等・明示)/
  `flatpak list --app`。どれかが失敗したら何も書かずに終了する。
- pacman/AUR: `/etc/pacman.d/hooks/pkgnote-fetch.hook`(etcfiles で配置。元は
  `~/.local/share/etcfiles/pacman.d/hooks/`。root の持ち物になる)が PostTransaction で、
  `runuser -l` で呼び出しユーザー(`$SUDO_USER`)に降りてから `pkgnote fetch` を実行する。
  ヘルパースクリプトは無い(root が直接実行するのは `/bin/sh` と `/usr/bin/runuser` だけ)。
  sudo を経由しない root での実行では何もしない。
- flatpak: 宣言的 hook 機構が無いため `~/.config/fish/functions/flatpak.fish` で
  `flatpak` コマンドをラップし、install/uninstall 後に `pkgnote fetch` を呼ぶ。

## 開発

```
uv sync                        # 依存(ckdl)を取得
uv run pkgnote <subcommand>    # 直接実行
uv run pytest                  # テスト(実 ~/.pacman 等には触らない)
PKGNOTE_PACMAN_DIR=/path uv run pkgnote status   # データ置き場を差し替えて安全に試す
```

差し替え用の環境変数: `PKGNOTE_PACMAN_DIR` / `PKGNOTE_MACHINES_FILE` / `PKGNOTE_YADM_CONFIG` /
`PKGNOTE_STATE_DIR`。

## 実装メモ

- KDL のパースは `ckdl`(KDL 2.0 準拠)。ただし書き戻しは `src/pkgnote/kdl.py` の自前
  シリアライザを使う。ckdl の `dump()` は「値だけクオート」スタイルを出せず、コメントも
  失うため、git 差分が安定する正準出力を自前で持つ(トレードオフ: 機械書き換え対象の
  KDL ではユーザーの任意コメントは round-trip されない)。書き込みは原子的置換。
- 条件式(`src/pkgnote/expr.py`): `!` > `&` > `|` の手書き再帰下降パーサ。
- 解決(`src/pkgnote/resolve.py`): パス上の `install-if` は AND、`skip-if` は OR で合成。
  条件が無ければ全マシン。カテゴリは説明のみ。
- クラス(`src/pkgnote/machines.py`): machines.toml の値をそのままクラス名にする(`"none"` は除く。`intel-cpu` / `nvidia-gpu` / `desktop` 等)。読み込み時に形式を検査。
