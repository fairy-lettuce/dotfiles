# pkgnote — 仕様書

パッケージの導入理由・カテゴリ・マシンごとの導入条件を KDL で管理する個人用ツール。
初期設計の経緯は `~/src/misc/20260720-dotfiles-package-kdl-design/design.md` にある
(ただしマシンごとの要否の表現は、そこで決めた `machine_*.kdl` の include ツリー方式から、
`packages.kdl` 上の条件式方式に 2026-10 に作り直した。下記「旧方式からの変更」参照)。

## 開発方針

個人用ツール。OSS としてのメンテナンス(汎用性への配慮、後方互換性、他者からの Issue 対応等)は
やらない前提で、KDL が個人的に見やすく書きやすいという理由だけで採用し、自分が使いやすいように
好き勝手作る。

## 配置・運用(実装前に必ず守ること)

- **本体は `~/.local/share/pkgnote/` に置く。`~/src/pkgnote` のような dotfiles 管理外のディレクトリに
  依存させてはいけない。** dotfiles は yadm(リポジトリは `~/.dotfiles`、work-tree は `$HOME`)で
  複数マシンに展開されるため、`~/src/` 配下は各マシンで別途 clone しないと存在せず、ポータビリティが
  壊れる。yadm は常に `yadm --yadm-repo ~/.dotfiles ...` で呼ぶ(ラッパーは無い)。
- **`~/.local/share/pkgnote/` に独立した git リポジトリ(`.git`)を作ってはいけない。** dotfiles の
  work-tree 内にネストした git リポジトリを作ると、gitlink 化・無視など事故りやすい状態になる。
  `uv init` はデフォルトで `git init` を実行することがあるため、**`uv init --no-git`(または相当の
  オプション)を明示的に使うこと。**
  既存の `.pacman/` や `.local/bin/etcfiles` も同様に、独立リポジトリではなく dotfiles が一元管理している。
- **`~/.local/bin/pkgnote` は本体を呼ぶだけの薄いシムにする。**
  `uv run --project ~/.local/share/pkgnote pkgnote "$@"` のような数行のシムを **手書きして** dotfiles
  管理下に置く。`uv tool install` が自動生成するシムは venv への絶対パスを shebang に埋め込むため、
  git 管理して複数マシンにポータブルに展開する用途には向かない(生成する人のマシン・ユーザー名に紐づく)。
  ただし配置構造の考え方自体(本体は `.local/share/<name>/`、エントリーポイントだけ `.local/bin/`)は
  `uv tool install`/`pipx` のデフォルト挙動そのものを踏襲している。
- dotfiles 全体の `.gitignore` に `.venv/`/`__pycache__/` 等 Python プロジェクトの典型的な除外パターンが
  含まれていること。
- コマンド名の候補として `pacmeta` を検討したが、pacdef の後継ツール `metapac` と紛らわしいため却下し
  `pkgnote` にした。`pac` 始まりは pacman 専用ツールに見えて誤解を招く(pacman 以外に foreign/flatpak、
  将来的には winget/scoop も扱う multi-backend 想定のため)。

## 前提・言語選定

- フォーマットは KDL。KDL には配列リテラルがなく、プロパティ値はスカラー(文字列/数値/真偽値/null)のみ。
- KDL v2 では真偽値リテラルは `#true`/`#false`/`#null`(v1 の裸の `true`/`false`/`null` ではない)。
- **KDL パーサは `ckdl` を採用。** KDL 1.0/2.0 両対応かつ upstream テストスイート通過で、PyPI に
  正式リリースされている。書き戻しは自前の正準シリアライザ(下記「書き戻し」)。
- Python 環境は `uv` を使う(グローバル方針)。テストは `uv run pytest`。
- 名前(ノード名・プロパティ名)はすべて kebab-case。

## packages.kdl — パッケージの分類マスタ兼導入条件

配置: `~/.pacman/packages.kdl`(全マシン共通の 1 ファイル)

トップレベルのラッパーノードは置かない(KDL はマルチルートを許すため意味がない)。
カテゴリは「用途」基準で、**「なぜ入れたか」の説明でしかない**。どのマシンに入れるかは
下記の条件式だけで決まり、カテゴリに属すること(`uncategorized` であることを含む)自体は判定に
影響しない。カテゴリの切り方は、`tool` のみ `cli`/`gui` の操作インターフェース軸を通し、他
(`dev`/`creative` 等)は用途分野の中で必要に応じて `cli`/`gui` サブカテゴリを持つ。

```kdl
system {
    package "bluez" from="pacman"
    boot {
        package "grub" from="pacman" install-if="grub"
    }
}

game install-if="gaming" {
    package "steam" from="pacman"
    package "gamescope" from="pacman" skip-if="laptop"
}

dev {
    gui {
        package "com.visualstudio.code" from="flatpak" alias="vscode"
    }
}

uncategorized {
    package "some-new-tool" from="pacman" install-if="ruan" first-installed-on="ruan"
}
```

- `from` は `"pacman"` / `"foreign"`(AUR 等) / `"flatpak"`。将来 `"winget"`/`"scoop"` を追加する余地を
  残す。値は必ずクオートする。
- flatpak は package 名(第一引数)に ID をそのまま使う(flatpak の `exports/bin` は ID そのままの名前で
  コマンドをエクスポートするため、「実行時に叩く識別子」で統一すると ID になる)。可読性は `alias` で
  補う。`alias` は pacman/foreign でも自由に使ってよい。
- `first-installed-on="<machine>"`: 最初に検出されたマシンの記録(履歴。判定には使わない)。
- `uncategorized` は fetch が新規パッケージを入れる一時置き場。`pkgnote categorize` で正式カテゴリへ移す。

### 条件式(`install-if` / `skip-if`)

package にもカテゴリにも `install-if="<式>"` / `skip-if="<式>"` を書ける。

- 文法: 名前、`&`(AND)、`|`(OR)、`!`(NOT)、括弧。優先順位は `!` > `&` > `|`。空白は無視。
  **AND は必ず `&` で書く**(名前の並置 `a b` は構文エラー)。手書きの再帰下降パーサで、エラーは
  ファイル名・ノードパス・位置(`^`)付きで出す。
- 合成: 根 → package のパス上の条件をすべて合成する。
  - 実効 install = パス上の全 `install-if` の AND(1 つも無ければ真)
  - 実効 skip = パス上の全 `skip-if` の OR(1 つも無ければ偽)
  - 入れる ⇔ 実効 install かつ not 実効 skip。**条件がどこにも無ければ全マシンに入る。**
    skip が真なら install-if に関係なく入らない。
- 使える名前: マシンの論理名と、マシン属性の値(クラス名。次節)。どのマシンの論理名でも
  クラス名でもない名前は **警告**(エラーではない。将来の属性を先回りして書けるように)。

### マシン属性 — `~/.config/machines.toml`

```toml
[ruan]
form = "desktop"
cpu = "intel-cpu"
gpu = "nvidia-gpu"            # ハイブリッドなら ["intel-gpu", "nvidia-gpu"]
bootloader = "grub"
filesystem = "ext4"
encryption = "none"
secureboot = "none"
roles = ["personal", "gaming", "dualboot"]
```

テーブルキーがマシンの論理名。クラス名の規則(`src/pkgnote/machines.py` にだけ書く):

- キーはラベルにすぎない。文字列の値と、文字列の配列の各要素が、**そのまま**クラス名になる
  (接尾辞などの変換はしない。`cpu = "intel-cpu"` → `intel-cpu`)。どのキーも文字列か文字列の配列を取れる
- 例外として値 `"none"` はクラスを出さない(`encryption = "none"` のように「ない」ことを書く)
- 真偽値・数値・入れ子のテーブル・空文字列はエラー。1 マシンの中で同じクラスが 2 回出てくるのもエラー
- 論理名とクラス名はホスト名のラベルの規則(RFC 1123): 英数字と `-`、先頭・末尾は `-` 不可、1〜63 文字(`_` は不可)。
  クラス名が他のマシンの論理名と同じでもよい。条件式の名前の文法はこれより広い(実在しない名前は警告)
- 値の許可リストは持たない(未知の値もそのまま名前になる)
- machines.toml は公開される。ディスクの解除方法(TPM2 / パスフレーズ / FIDO2)や鍵の管理は書かない

形式の検査は読み込み時に全マシンに対して行う(どれか 1 台でも不正なら全コマンドがエラー)。
マシンの追加・更新はデプロイ用のスクリプト側(`~/.local/share/deploy-dotfiles/machine-init.py`)が行う。

`pkgnote machine classes [--machine X]` が 1 行 1 つで出力する。セットアップスクリプトはこれを
yadm の `local.class` に流し込めばよい(規則を二重に持たない)。

現在のマシンの論理名は yadm の `local.hostname`(`git config -f ~/.dotfiles/config local.hostname`)。
未設定ならエラー(設定方法を案内する)。全コマンドで `--machine <name>` で上書きできる。
machines.toml に無いマシンを対象にするとエラー(条件を誤評価して書き込まないため)。

## コマンド

### fetch(実システム → KDL への取り込み)

用語は `etcfiles` の `deploy`(管理ファイル→実システム)/`fetch`(実システム→管理ファイル)に揃える。

- pacman hook(`/etc/pacman.d/hooks/pkgnote-fetch.hook`、下記「hook」参照)と flatpak ラッパー
  (`~/.config/fish/functions/flatpak.fish`。flatpak には宣言的 hook 機構が無いため)から呼ばれる想定。
  手動実行も可。対象は常に現在のマシンで、`--machine` は現在のマシン名と一致する場合のみ受け付ける
  (このシステムの状態を別マシンの名義で記録しないため。deploy も同様)。
- 明示インストールの判定は、その場で `pacman -Qqen`(公式)/ `pacman -Qqem`(AUR 等)/
  `flatpak list --app` を問い合わせる(root 不要)。依存で入ったパッケージは `-e` で除外される。
  問い合わせの **失敗は空集合と区別** し、1 つでも失敗したら何も書かず(観測集合も更新せず)に終了する。
- 「インストールした / アンインストールした」は、前回 fetch 時の観測集合
  (`~/.local/state/pkgnote/installed_<machine>.txt`、マシンローカル・dotfiles 管理外)との差分で判定する。
  手で条件を書き換えた直後(まだ deploy・削除していない)のパッケージを fetch が勝手に「実機に合わせて」
  書き戻さないため。観測集合が無い・空の初回は未登録パッケージの追加だけ行う(空集合は保存しない)。
- 反映ルール(ノードは決して削除しない):
  - 未登録のパッケージ → `uncategorized` に `install-if="<machine>"` + `first-installed-on="<machine>"`。
  - インストールされたが条件上は入らない:
    - package 自身の `install-if` が偽 → `" | <machine>"` を追記。
    - package 自身の `skip-if` が真 → OR 項からマシン名を除く(空になれば `skip-if` ごと消す)。それでも
      真(`desktop` 等のクラスで当たっている)なら `(<残り>) & !<machine>` に書き換える。
    - **カテゴリ側の条件で除外されている場合**(祖先の `install-if` が偽、または `skip-if` が真)は、
      package 側の条件では覆せない(install は AND、skip は OR で合成されるので、package に何を書いても
      結果は偽のまま)。黙って無意味な書き込みをするより、**何も書かずに警告**し、package を別カテゴリへ
      移すかカテゴリの条件を見直すよう促す。`pkgnote status` でも理由付きの EXTRA として出続ける。
      (package 側にカテゴリ条件を上書きする仕組みを足す案もあるが、「カテゴリ条件は配下すべてに効く」と
      いう読みやすさを崩すので採らない。)
  - アンインストールされたが条件上は入る → package 自身の `skip-if` に `" | <machine>"` を追記(無ければ作る)。
    一度に 5 件を超えるときは取得異常を疑って何も書かずに止める(`--allow-mass-removal` で続行)。
  - 記録と違う backend で入っている(AUR から公式リポジトリへの移動など)→ `from` を実際の値に直す。
- 安全策: packages.kdl に旧形式の名残(`installed_on` ノード、`first_installed_on` 等)がある、条件式の
  構文エラー、未知のプロパティ(`skipif=` などの綴り間違い)や未知の `from` 値、マシンが未定義など、
  データが不整合なら **何も書かずに失敗**する(読み込み時の検査なので status / deploy も同様に止まる)。書き込みは一時ファイル
  + rename の原子的置換で、読み込み後にファイルが他から変更されていたら上書きしない。書き出す内容は
  自分で読み直してパッケージ集合が変わっていないことを確認してから置き換える。

### deploy(KDL → 実システム)

対象マシンの名前集合で全パッケージの条件を評価し、入るべきなのに未導入のものを導入する(削除はしない)。

- pacman: `sudo pacman -S --needed …`
- foreign(AUR): `--aur-helper <name>`(既定 `paru`。yay 互換の `-S --needed` を受け付けるもの)
  - 指定した AUR ヘルパーが PATH に無いときは、エラーを表示して foreign の導入だけを飛ばし、終了コード 1 を返す(他の backend は続ける。`--dry-run` では表示のみで終了コード 0)
- flatpak: `flatpak install …`
- 既定では `--noconfirm` を付けない(pacman/AUR ヘルパーの確認や PKGBUILD レビューをそのまま出す)。
  `pkgnote deploy --noconfirm` のときだけ pacman/AUR ヘルパーに `--noconfirm`、flatpak に `-y`。
- `--dry-run` で実行するコマンドを表示するだけ。`--backend` で対象を限定できる。
- pacman / foreign では、明示インストールの一覧に無い名前を次のように分類する(`backends.classify`):
  - `pacman -T -- <名前...>` で満たされない名前 → 導入が必要
  - その名前のパッケージが依存として入っている(`pacman -Qq -- <名前>` で見つかる)→ 導入しない。
    明示にするコマンド `sudo pacman -D --asexplicit -- <名前...>` を案内する
  - インストール済みのパッケージがその名前を provides し、**かつ** conflicts または replaces している
    (`LC_ALL=C pacman -Qi` の Provides / Conflicts With / Replaces。バージョン指定は名前部分で比較)→
    代替パッケージで導入済み(例: `paru-bin` は `paru` を provides + conflicts)。導入しない
  - provides だけで conflicts / replaces しないもの(`dotnet-sdk-9.0-bin` の `dotnet-sdk=9.0` など)は
    共存する別物なので、導入が必要
  - `pacman -T` は全部満たされれば exit 0、満たされない名前があれば exit 127。それ以外の終了は `BackendError`。
    flatpak は対象外

### status / categorize / machine

- `status`: 算出した集合と実機を突き合わせ、MISSING(入るべきなのに未導入)/ EXTRA(導入済みだが
  条件上は入らない。理由付き)/ from 不一致(記録と違う backend で導入済み)を表示する。書き込みなし。
  `--machine` で他マシンの集合も見られる(比較対象の実機状態はこのシステムのもの)。
  deploy と同じ分類で、代替パッケージで入っているものは PROVIDED、依存として入っているものは
  DEPENDENCY(`pacman -D --asexplicit` を案内)と表示し、MISSING に数えない。
  fetch の「未記録のずれ」の表示も同じ分類を使う。ただし fetch の書き込み(条件の記録)は
  明示インストールの一覧の差分だけで決め、この分類は使わない。
- `categorize`: `uncategorized` のパッケージを対話的に正式カテゴリへ移す。package 自身の条件と
  `first-installed-on` はそのまま持っていく。移動先カテゴリの条件で結果が変わるマシンがあれば表示する。
- `machine name|classes`: 論理名 / クラスの表示。

### CLI 一覧

```
pkgnote status
pkgnote deploy [--dry-run] [--noconfirm] [--aur-helper NAME] [--backend B]
pkgnote fetch  [--dry-run] [--allow-mass-removal]
pkgnote categorize [--dry-run]
pkgnote machine name|classes
共通: --machine <論理名>  --color auto|always|never
```

## 書き戻し

ckdl の `dump()` は「ノード名・キーは裸、文字列値だけクオート」のスタイルを出せずコメントも失うため、
`src/pkgnote/kdl.py` の自前シリアライザで正準出力する(git 差分が安定する)。プロパティ順は
`from`, `alias`, `install-if`, `skip-if`, `first-installed-on`, その他。

既知の制限(TODO): ファイル先頭の生成ヘッダ以外のコメントは round-trip されない。退避済みの手書き
コメントは `~/.pacman/packages-comments.md` にある。

## git 運用

- packages.kdl は全マシンで共有する 1 ファイル。fetch は自マシン名を含む条件を追記するだけなので、
  複数マシンで同時に書き換えても衝突は行単位で小さく、手で解消できる。
- fetch/deploy 先の複数マシン間の同期・コンフリクト解消(push・merge)は自動化せず手動。

## hook

- hook は `~/.local/share/etcfiles/pacman.d/hooks/pkgnote-fetch.hook` を etcfiles で
  `/etc/pacman.d/hooks/` にコピーする(root の持ち物になる)。以前は `pacman.conf` の `HookDir` に
  `~/.pacman/` を登録していたが、ユーザーが書き換えられる hook / スクリプトを root が実行することに
  なり危険なのでやめた。
- `Exec` は `/bin/sh -c` の 1 行で、`$SUDO_USER` があれば `runuser -l -c "pkgnote fetch" -- "$SUDO_USER"`
  でそのユーザーのログイン環境に降りてから `pkgnote fetch` を実行する。ヘルパースクリプトは無い
  (root が直接実行するのは root 所有の `/bin/sh` と `/usr/bin/runuser` だけ)。sudo を経由しない
  root での実行では `$SUDO_USER` が無いので何もしない。pacman の hook の解析は `#` 以降をコメントとして
  切るので、`Exec` に `#` を書かない。
- fetch は自分でインストール済み一覧を問い合わせるので、他の hook との実行順序には依存しない。
- `PostTransaction` フックは非ゼロ終了してもトランザクションに影響しない(念のため `|| true` もしてある)。

## 旧方式からの変更(2026-10)

当初は `machine_$HOSTNAME.kdl` にカテゴリツリーを写した include ツリーを持ち、最深の明示 `include` が勝つ
方式だった。これを廃止した理由:

- カテゴリツリーが「説明」と「導入先の判定」を兼ねていて、分類を変えると導入先まで変わる。
- fetch が package ごとに `include=#true` を書き続けて木が肥大化し、それを畳む圧縮(`compress`)は
  「たまたま全部同じ」を「将来も全部同じ」に格上げしてしまう危険があった。
- `uncategorized` だけ `installed_on` で判定する特殊ルールが必要だった。

条件式方式では、マシンの共通点(desktop / nvidia-gpu / gaming 等)で書けるので新マシン追加時に
packages.kdl を書き換えずに済み、カテゴリは純粋に説明になる。`compress`・`installed_on`・
`--host`・`host-alias.kdl` 案は廃止。移行は `python -m pkgnote.migrate_v2` で一度だけ実施済み
(旧 `machine_ruan.kdl` は参照されないが削除はしていない)。

## 旧 pkglist.hook / txt

以前は `pkglist.hook` / `pkglist_foreign.hook` が生成する `pkglist_$HOSTNAME.txt` /
`pkglist_foreign_$HOSTNAME.txt` を fetch/status の入力にしていたが、ファイルが無い・空のときに
「全部アンインストールされた」と誤認する危険があったため、直接の問い合わせに切り替えて廃止・削除した。

## 将来の拡張候補

- **winget/scoop 対応**: `from` の値に `"winget"`/`"scoop"` を追加するだけで packages.kdl 側は対応できるはず。
  ただし pacman hook 相当の自動検知の仕組みが Windows 側に無いため、fetch の実現方法は別途調査が必要。
  優先度は低い。

## 未解決・保留

- コメントの round-trip 保持(上記「書き戻し」)。
- カテゴリ条件で除外されたパッケージを手で入れた場合の扱いは「警告のみ」。頻発するようなら再検討。
