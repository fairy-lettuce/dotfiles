# pkgnote

パッケージの導入理由・カテゴリ・マシンごとの要否を KDL で管理する個人用ツール。

仕様の詳細は `SPEC.md` を必ず読むこと。特に「配置・運用」セクションは実装前に必ず守ること
(`~/src/` への依存禁止、ネストした git リポジトリを作らない、`uv init --no-git` を使うこと)。

設計相談の経緯(なぜこの構造になったか、検討して却下した案)は
`~/src/misc/20260720-dotfiles-package-kdl-design/design.md` にある。判断に迷ったらそちらも参照する。

## 開発方針

個人用ツール。OSS としてのメンテナンスは考えず、自分が使いやすいように作る。

## 最初にやること

1. `~/.local/share/pkgnote` で `uv init --no-git` してプロジェクトを初期化する
   (`--no-git` を忘れると dotfiles bare repo の work-tree 内にネストした git リポジトリができるので注意)。
2. `uv add ckdl` で KDL パーサを追加する。
3. dotfiles 全体の `.gitignore`(`~/.gitignore`)に `.venv/`/`__pycache__/` 等が含まれているか確認し、
   無ければ追加する。
4. データモデルを実装する: `packages.kdl`/`machine_$HOSTNAME.kdl` を読み込み、木構造として扱えるように
   パースする層。
5. DFS 解決ロジックを実装する: あるマシンについて、packages.kdl 上の各パッケージが最終的に
   include=#true/#false のどちらと評価されるかを算出する関数(SPEC.md の「優先順位ルール」参照)。
   `uncategorized` は特殊ルール(`installed_on` で判定)なので忘れないこと。
6. 上記ができたら、まず読み取り専用の `pkgnote status`(ドリフト検知、書き込みなし)から作る。
   実システムに影響を与えないので安全にテストできる。`deploy`/`fetch`/`compress`/`categorize` は
   その後、SPEC.md の記述に沿って順に実装する。
7. `~/.local/bin/pkgnote` に、`uv run --project ~/.local/share/pkgnote pkgnote "$@"` を呼ぶだけの
   薄いシムスクリプトを手書きで置く(`uv tool install` の自動生成には頼らない。理由は SPEC.md 参照)。
