# PATH
fish_add_path $HOME/.local/bin

if status is-interactive
    # disable startup greeting
    set -g fish_greeting

    # prompt
    starship init fish | source

    # aliases / abbreviations
    alias dotfiles '/usr/bin/git --git-dir=$HOME/.dotfiles/ --work-tree=$HOME'
    abbr -a lgx2 '/usr/bin/lgx2userspace -d /dev/video99'

    # local overrides (not tracked in dotfiles)
    test -f ~/.config/fish/local.fish; and source ~/.config/fish/local.fish
end
