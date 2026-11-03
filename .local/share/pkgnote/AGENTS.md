# pkgnote

パッケージの導入理由・カテゴリ・マシンごとの導入条件を KDL で管理する個人用ツール。

仕様の詳細は `SPEC.md` を必ず読むこと。特に「配置・運用」セクションは実装前に必ず守ること
(`~/src/` への依存禁止、ネストした git リポジトリを作らない)。

初期の設計相談の経緯は `~/src/misc/20260720-dotfiles-package-kdl-design/design.md` にある
(マシンごとの要否の表現はその後、条件式方式に変えた。SPEC.md「旧方式からの変更」参照)。

## 開発方針

個人用ツール。OSS としてのメンテナンスは考えず、自分が使いやすいように作る。

## 実装・運用メモ

- `~/.local/share/pkgnote` に `.git` を作らない(`uv init` するなら `--no-git`)。dotfiles は yadm
  (`yadm --yadm-repo ~/.dotfiles ...`)が一元管理している。
- `~/.local/bin/pkgnote` は `uv run --project ~/.local/share/pkgnote pkgnote "$@"` を呼ぶだけの手書きシム。
- マシンごとの導入可否は `packages.kdl` の `install-if` / `skip-if` 条件だけで決まる(SPEC.md
  「条件式」)。カテゴリは説明のみ。旧 `machine_*.kdl` / `installed_on` / `compress` は廃止済み。
- `pkgnote fetch` は(hook を root 所有パスへ移して再有効化した後は)pacman hook からいつでも
  走りうる。データ不整合・インストール済み一覧の取得失敗のときは書かずに失敗する、大量の
  アンインストール記録は止める、書き込みは原子的置換、という性質を壊さないこと。
- インストール済み一覧は `pacman -Qqen` / `-Qqem` / `flatpak list` を直接問い合わせる
  (旧 `pkglist_*.txt` は廃止)。
- パッケージの導入・削除や `sudo` を伴うコマンドを試すときは `deploy --dry-run` を使う。テストでは
  backend をモックする(`tests/conftest.py`)。
- テスト: `uv run pytest`。
