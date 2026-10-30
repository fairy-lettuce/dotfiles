# pkgnote — 仕様書

パッケージの導入理由・カテゴリ・マシンごとの要否を KDL で管理する個人用ツール。
設計相談の経緯は `~/src/misc/20260720-dotfiles-package-kdl-design/design.md` にある
(このファイルはそこからの引き継ぎ + 実装時の配置・運用に関する追加の注意点をまとめたもの)。

## 開発方針

個人用ツール。OSS としてのメンテナンス(汎用性への配慮、後方互換性、他者からの Issue 対応等)は
やらない前提で、KDL が個人的に見やすく書きやすいという理由だけで採用し、自分が使いやすいように
好き勝手作る。

## 配置・運用(実装前に必ず守ること)

- **本体は `~/.local/share/pkgnote/` に置く。`~/src/pkgnote` のような dotfiles 管理外のディレクトリに
  依存させてはいけない。** dotfiles は bare repo(`~/.dotfiles`, work-tree は `$HOME`)で複数マシンに
  展開されるため、`~/src/` 配下は各マシンで別途 clone しないと存在せず、ポータビリティが壊れる。
- **`~/.local/share/pkgnote/` に独立した git リポジトリ(`.git`)を作ってはいけない。** dotfiles bare
  repo の work-tree 内にネストした git リポジトリを作ると、gitlink 化・無視など事故りやすい状態になる。
  `uv init` はデフォルトで `git init` を実行することがあるため、**`uv init --no-git`(または相当の
  オプション)を明示的に使うこと。**
  既存の `.pacman/` や `.local/bin/etcfiles` も同様に、独立リポジトリではなく dotfiles bare repo が
  一元管理している。それに揃える。
- **`~/.local/bin/pkgnote` は本体を呼ぶだけの薄いシムにする。**
  `uv run --project ~/.local/share/pkgnote pkgnote "$@"` のような数行のシムを **手書きして** dotfiles
  管理下に置く。`uv tool install` が自動生成するシムは venv への絶対パスを shebang に埋め込むため、
  git 管理して複数マシンにポータブルに展開する用途には向かない(生成する人のマシン・ユーザー名に紐づく)。
  ただし配置構造の考え方自体(本体は `.local/share/<name>/`、エントリーポイントだけ `.local/bin/`)は
  `uv tool install`/`pipx` のデフォルト挙動そのものを踏襲している。
- 実装開始時に、dotfiles 全体の `.gitignore` に `.venv/`/`__pycache__/` 等 Python プロジェクトの典型的な
  除外パターンが含まれているか確認すること。
- コマンド名の候補として `pacmeta` を検討したが、pacdef の後継ツール `metapac` と紛らわしいため却下し
  `pkgnote` にした。`pac` 始まりは pacman 専用ツールに見えて誤解を招く(pacman 以外に foreign/flatpak、
  将来的には winget/scoop も扱う multi-backend 想定のため)。

## 前提・言語選定

- フォーマットは KDL。KDL には配列リテラルがなく、プロパティ値はスカラー(文字列/数値/真偽値/null)のみ。
  複数値は子ノードとして表現する。
- KDL v2 では真偽値リテラルは `#true`/`#false`/`#null`(v1 の裸の `true`/`false`/`null` ではない)。
- **KDL パーサは `ckdl` を採用。** KDL 1.0/2.0 両対応かつ upstream テストスイート通過で、PyPI に
  正式リリースされている。対抗馬だった `tabatkins/kdlpy` は KDL 2.0 対応が GitHub の main ブランチのみで
  PyPI 未公開のため見送った。自前パーサ実装は不要。
- Python 環境は `uv` を使う(グローバル方針)。

## packages.kdl — パッケージの分類マスタ

配置: `~/.pacman/packages.kdl`

トップレベルのラッパーノードは置かない(KDL はマルチルートを許すため意味がない)。
カテゴリは「用途」基準。`tool` のみ `cli`/`gui` の操作インターフェース軸を通し、他のカテゴリ
(`dev`/`creative` 等)は用途分野の中で必要に応じて `cli`/`gui` サブカテゴリを持つ(全カテゴリに強制しない)。

```kdl
system {
    package "bluez" from="pacman"
    package "adobe-source-han-sans-jp-fonts" from="pacman"
}

tool {
    cli {
        terminal {
            package "alacritty" from="pacman"
            package "zellij" from="pacman"
        }
    }
    gui {
        browser {
            package "brave-bin" from="foreign"
        }
    }
}

dev {
    c-sharp {
        package "dotnet-sdk-10.0" from="pacman"
    }
    gui {
        package "com.visualstudio.code" from="flatpak" alias="vscode"
    }
}

uncategorized {
    package "some-new-tool" from="pacman" first_installed_on="ruan" {
        installed_on "ruan"
    }
}
```

- `from` は `"pacman"` / `"foreign"`(AUR 等) / `"flatpak"`。将来 `"winget"`/`"scoop"` を追加する余地を
  残す(下記「将来の拡張」参照)。値は必ずクオートする。
- flatpak は package 名(第一引数)に ID をそのまま使う。理由: flatpak の `exports/bin` は ID そのままの
  名前でコマンドがエクスポートされる仕様で、「実行時に叩く識別子」で出典間の意味を統一すると自然に ID に
  なる。可読性は `alias` プロパティで補う。`alias` は flatpak 専用ではなく pacman/foreign でも自由に
  使ってよい。
- `uncategorized/<name>` は fetch が自動追加する未分類の一時置き場。
  - `first_installed_on="<machine>"`(property, 単一・不変): 最初に検出されたマシン名の記録。
  - `installed_on`(child node, 複数可): 現在実際にインストールされているマシンの集合。KDL の
    プロパティは配列を持てないため、複数マシンに広がった場合はこの子ノードを追加していく。
  - deploy 時はこのカテゴリだけ特殊扱いで machine_*.kdl を見ず、`installed_on` にそのマシン名がある
    場合のみ include する。カテゴリ移動後もこれらのプロパティ/ノードは残してよい(uncategorized 配下
    でのみ参照される、それ以外では無視される inert な情報として扱う)。

## machine_$HOSTNAME.kdl — マシンごとの導入意図 (deploy 型)

配置: `~/.pacman/machine_$HOSTNAME.kdl`(マシンごとに別ファイル)

各パッケージにマシンリストを持たせる方式ではなく、マシン側が「有効にするカテゴリ」を選ぶ方式。
開発専用マシンは `creative` を、WM 不要なサーバは `gui` 系を丸ごと外す、といった同期が容易になる。

### ファイル分割

マシンごとに別ファイル `machine_$HOSTNAME.kdl` に分割する(単一ファイルに全マシン分の
`machine "hostname" { }` ブロックを並べる案もあったが撤回)。理由:

- bare repo は全マシンで同じパスを共有するため、単一ファイルだと複数マシンからの非同期な fetch が
  同じファイルへの書き込みとして衝突しやすい。マシンごとに別ファイルにすれば、各マシンは自分のファイル
  しか触らないので git 上の衝突が構造的に起きにくい。
- 既存の `pkglist_$HOSTNAME.txt` という命名パターンとも一貫性がある。

ホスト名が将来的に重複・変更するケースに備えて、`$HOSTNAME`(物理ホスト名)とファイル/ノードで使う
論理識別子を分離できるよう、`~/.pacman/host-alias.kdl` のような小さな対応表(物理 `$HOSTNAME` →
論理名)を持たせる案がある(詳細は実装時に詰める)。

木構造は packages.kdl のカテゴリツリーをそのまま反映する形でネストし、属性は `include` に統一する
(`installed` という別名は設けない。理由は後述)。

```kdl
// machine_ruan.kdl
machine "ruan" {
    system include=#true {
        package "bluez" include=#true
    }

    tool include=#true

    dev include=#true {
        gui include=#false {
            package "com.visualstudio.code" include=#true
        }
    }

    creative include=#false
}
```

### 優先順位ルール

- 最も近い祖先(自ノード含む)の明示的な `include` 値が勝つ。DFS で「自分に明示指定があれば採用、なければ
  親を見に行く」。
- 判定は「根から対象パッケージまでのパス上に、どこか一箇所でも `include` の明示があるか」で行う。
  途中の中間ノード(`dev` や `gui` など)は省略してよく、より深い場所(個別 package ノードなど)にだけ
  明示があれば、それだけで十分に有効な指定として扱う。パス上のどこにも明示が一つも無い場合にのみ
  エラーにする。
- ネストによる木構造の specificity で優先順位を表現するので、フラットな `include "a/b/c"` /
  `exclude "a/b/c"` のようなパス文字列 + 宣言順ルールは採用しない。パス文字列方式は宣言順を人間が守ら
  ないと事故るが、木構造なら「より深くネストしている方が具体的」という構造上の制約で担保される。
  副産物として、parser が packages.kdl と machine_*.kdl の木を同時に辿れるので、存在しないカテゴリ名の
  検証もついてくる。
- KDL の文法にパス圧縮記法(`a/b/c { }` のような中間ノード省略)は存在しない。全階層を明示的にネストする。
- KDL の property 構文はキー必須・値必須(`prop := string '=' value`)で、値省略のショートハンドはできない。
  「true の場合は書かなくてよい」ショートハンドは検討したが、冗長性の解消は木の圧縮コマンドに任せる方針
  とし、`include=` は常に明示する形のままにした。

### installed と include を分けない理由

当初「fetch が書く観測事実(installed)」と「deploy 用の意図(include)」を別属性にする案を検討したが、
machine_*.kdl 自体が「そのマシンにインストールされているべきという意図の表現」だと捉えれば、
fetch/deploy どちらの方向であっても書き込む値の意味は同じであり、属性を分ける理由がない。分けたところで、
木の圧縮操作が持つ危険性(下記)は属性名によらず存在するため、分離では解決しない。

### fetch(実システム→ KDL への取り込み)

用語: `etcfiles` の `deploy`(管理ファイル→実システム)/`fetch`(実システム→管理ファイル)という
既存の命名に揃え、`pull`/`push` ではなく **`fetch`/`deploy`** を使う
(`etcfiles` の `fetch` のヘルプ文言 "pull in changes made directly in /etc" で "pull" が
今回と逆方向の意味で既に使われており、`pull`/`push` のままでは混乱するため)。

- pacman/yay/flatpak の install/remove 実行時に hook で捕捉。
- **明示的インストールのみを拾う判定方法**: pacman hook のトランザクション情報(`%TARGETS%`)から
  依存関係を判別しようとはせず、「packages.kdl/machine_*.kdl から算出できるあるべきパッケージ一覧
  (ソート済み)」と「既存の `pkglist_$HOSTNAME.txt`/`pkglist_foreign_$HOSTNAME.txt` の内容(こちらも
  `pacman -Qqen`/`-Qqem` の生出力で明示的インストールのみ)」を diff して判定する。依存関係で入った
  パッケージはそもそもこの txt に出てこないので、この方式なら自然に除外される。
  - 副産物: この diff で「KDL にはあるが実機に無い」パッケージも同時に検出できるので、fetch 実行時に
    「deploy した方がいいかも」という軽い忠告を出せる(ドリフト検知を兼ねる)。
- インストール: packages.kdl に該当パッケージが未登録なら `uncategorized/<name>` に
  `first_installed_on="<machine>"` + `installed_on "<machine>"` 付きで追加。machine_*.kdl 側は、
  そのパッケージが属するカテゴリパスの最深部(package ノードそのもの)に `include=#true` を書き込む。
  これによりカテゴリレベルの `include=#false` より個別指定が優先される(= fetch が正典)。
- アンインストール: 該当 package ノードに `include=#false` を明示する。ノードを削除してはいけない
  (削除すると「明示なし」に戻り、祖先が `#true` なら継承されてインストールされたまま扱いに逆戻りして
  しまうため)。
- flatpak には pacman hook 相当の宣言的フック機構が存在しない(調査済み)。代わりに `flatpak` コマンド
  自体を fish の shell function でラップし、install/uninstall 実行後に fetch 相当の処理を呼ぶ方式を
  採る。**実装時、`.local/bin` 配下のスクリプト群にこの方式を選んだ理由をコメントで残しておくこと。**

### deploy(KDL の意図→実システムへの反映)

packages.kdl と machine_$HOSTNAME.kdl(自マシン分)の両方を DFS で降りて、そのマシンで最終的に
include=#true と評価されるパッケージ一覧を抽出し、一括インストールする。`uncategorized` は上記の
特殊ルールで判定する。AUR ヘルパーは **yay** を使う。

### 木の圧縮(整形)

fetch が個々の package ノードに `include=#true` を書き続けると木が肥大化するため、「子が全て同じ
`include` 値になった部分木は、根だけ残して子を消す」という圧縮操作が要る。

ただし無条件の自動圧縮は危険: 圧縮すると「たまたま今ある子が全部同じ値だった」という状態が
「配下は将来追加されるものも含めて全部同じ扱いにする」という意図に格上げされてしまう
(例: `dev/gui` 配下が vscode 1 個だけで `include=#true` のとき、圧縮して `dev/gui include=#true` に
すると、後で追加される未知のパッケージも自動的に include 対象になる)。

対応: 圧縮は完全自動化せず、圧縮候補を検出してユーザーに提示し、1 箇所ずつ、または一括で確認の上
適用するコマンドとして設計する。

## CLI コマンド一覧(暫定)

`pkgnote` 単一コマンドにサブコマンドをぶら下げる形。

- `pkgnote deploy` — 対象マシンの include=#true を算出し実際にインストール
- `pkgnote fetch` — 通常は hook から自動呼び出し。手動実行用にも用意
- `pkgnote compress [--all]` — 木の圧縮候補を検出、デフォルトは1件ずつ確認、`--all` で一括
- `pkgnote status` — ドリフト検知の diff を表示するだけ(書き込みなし)
- `pkgnote categorize` — `uncategorized` に溜まったパッケージを対話的に正式カテゴリへ移す

## git 運用

- packages.kdl / machine_*.kdl は独立した設定ファイルで他ファイルと相互依存しないため、dotfiles 本体と
  同じブランチで問題ない(別ブランチ化は bare repo の worktree モデル上、$HOME 全体が巻き込まれるため
  そもそも単純には実現できない)。
- fetch hook は commit をこれらのファイルにスコープして自動実行してよい(記録の取りこぼし防止)。
- hook の実行順序と失敗時の挙動:
  - 既存の `pkglist.hook`/`pkglist_foreign.hook` はそのまま残し、新 hook は独立したファイルとして
    追加する(統合しない)。pacman はトリガー条件が一致する hook をファイル名のソート順で実行するため、
    新 hook のファイル名を旧 hook より辞書順で後になるよう命名すれば「旧→新」の順序を保証できる。
  - 失敗時の挙動: 調査の結果 **`PostTransaction` フックは非ゼロ終了してもトランザクション自体には
    一切影響しない**(トランザクションはフック実行前に完了済みのため。中断できるのは `PreTransaction`
    フックの `AbortOnFail` オプションのみ)。既存 hook・新 hook とも `PostTransaction` なので、fetch
    側のスクリプトが失敗しても `pacman -S` 自体は成功する。念のため `|| true` 等でエラーを握りつぶす
    防御はしておいて損はないが必須ではない。
- fetch/deploy 先の複数マシン間の同期・コンフリクト解消(git push・merge)は自動化せず手動。

## 将来の拡張候補

- **winget/scoop 対応**: Windows 環境でも同じ仕組みを使いたい。`from` の値に `"winget"`/`"scoop"` を
  追加するだけで packages.kdl 側は対応できるはず。ただし pacman hook 相当の自動検知の仕組みが
  Windows 側に無いため、fetch の実現方法(ラッパー関数、タスクスケジューラでのポーリング等)は別途調査
  が必要。優先度は低く、今は構造だけ塞がないようにしておく程度で良い。

## 既存 pkglist.hook / txt の扱い

方針決定: **当面は両方(hook と生成される txt)残す。**

既存の `~/.pacman/pkglist.hook` / `pkglist_foreign.hook` とその生成物
`pkglist_ruan.txt` / `pkglist_foreign_ruan.txt` は、`pacman -Qqen`/`-Qqem` の生出力をそのまま持っている。
これは上記の「明示的インストールのみを拾う判定」と「ドリフト検知」の両方を実装コストゼロで肩代わりする
入力そのものになった。「hook は残すが txt だけ消す」は意味がない(hook の `Exec` は txt を生成すること
自体が仕事なので)。

新システム(packages.kdl/machine_*.kdl + `pkgnote`)が実装されて安定稼働したら、この txt を
恒久的な入力として使い続けるか、退役させるか改めて判断する。

## 未解決・保留(実装時に詰める)

- 明示的インストール/依存関係の切り分け方式(diff ベース)は方針決定済みだが、実際のコード化は未着手。
- ドリフト検知(`pkgnote status`)の具体的な出力フォーマットは未設計。
- flatpak 用の shell wrapper はまだ存在しない(実装対象)。
- 圧縮後のカテゴリに新規パッケージが fetch された場合の挙動(継承に任せるか、個別ノードを足すか)は
  一考の余地ありとして保留のまま。
- ホスト名エイリアス機構(`host-alias.kdl` 案)の詳細は未設計。
- KDL ライブラリの正確な依存バージョン指定は実装開始時に確認すること。
