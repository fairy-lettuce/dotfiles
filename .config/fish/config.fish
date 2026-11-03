# PATH
fish_add_path -g $HOME/.local/bin $HOME/.cargo/bin $HOME/.dotnet/tools /opt/cuda/bin

# pnpm (pacman 版は `pnpm setup` が使えないため path を手動で設定)
set -gx PNPM_HOME $HOME/.local/share/pnpm
fish_add_path -g $PNPM_HOME/bin

set -gx EDITOR helix

# local overrides (not tracked in dotfiles)
test -f ~/.config/fish/local.fish; and source ~/.config/fish/local.fish

if status is-interactive
    # disable startup greeting
    set -g fish_greeting

    # prompt
    command -q starship; and starship init fish | source

    # aliases / abbreviations
    # dotfiles (yadm; the repository stays at ~/.dotfiles)
    alias yadm 'command yadm --yadm-repo $HOME/.dotfiles'
    alias dotfiles 'command yadm --yadm-repo $HOME/.dotfiles'

    # helix alias
    alias hx helix
end

command -q mise; and mise activate fish | source
