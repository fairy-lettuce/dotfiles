# flatpak ラッパー — pkgnote 連携用。
#
# なぜ fish function なのか: pacman には宣言的な hook 機構(~/.pacman/*.hook)があり、
# install/remove を PostTransaction で捕捉できる。しかし flatpak には pacman hook 相当の
# 宣言的フック機構が存在しない(調査済み)。そこで flatpak コマンド自体を fish の
# function でラップし、install/uninstall の実行後に `pkgnote fetch` を呼んで KDL へ
# 取り込む。これで pacman 側(hook)と flatpak 側(このラッパー)で取り込み方法は違えど、
# 「install/remove 後に pkgnote fetch が走る」という挙動を揃える。
#
# 設計方針: flatpak 本体の実行結果(終了ステータス)は必ず保持し、pkgnote 連携は
# best-effort とする(fetch が失敗しても flatpak コマンドの結果を汚さない)。
function flatpak
    command flatpak $argv
    set -l flatpak_status $status

    # サブコマンドが install / uninstall のときだけ取り込みを走らせる。
    switch "$argv[1]"
        case install uninstall
            pkgnote fetch >/dev/null 2>&1
    end

    return $flatpak_status
end
