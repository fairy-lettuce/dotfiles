# Created by newuser for 5.9

# The following lines were added by compinstall

zstyle ':completion:*' completer _complete _ignored
zstyle ':completion:*' matcher-list '' 'm:{[:lower:][:upper:]}={[:upper:][:lower:]}' 'r:|[._-]=* r:|=*' 'l:|=* r:|=*'
zstyle :compinstall filename '/home/mei/.zshrc'

autoload -Uz compinit
compinit
# End of lines added by compinstall

bindkey "${terminfo[kdch1]}" delete-char
bindkey "${terminfo[kbs]}"  backward-delete-char

bindkey -M viins "${terminfo[kdch1]}" delete-char
bindkey -M vicmd "${terminfo[kdch1]}" delete-char

# dotfiles
alias dotfiles='/usr/bin/git --git-dir=$HOME/.dotfiles/ --work-tree=$HOME'

# start lgx2userspace (capture board)

alias lgx2='/usr/bin/lgx2userspace -d /dev/video99'

# path
export PATH=$HOME/.local/bin:$PATH
