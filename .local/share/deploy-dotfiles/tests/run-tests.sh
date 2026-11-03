#!/bin/bash
# Tests for deploy-dotfiles.sh, etcfiles, generate-color-scheme.sh and
# wallpaper-random.sh. Everything runs in a temp HOME with stub commands
# (sudo, pacman, systemctl, pkgnote, yadm, git, ...) first on a restricted PATH;
# no real system command with side effects is reachable.
#
# Usage: run-tests.sh [<test name substring>]
# uv is delegated to the real uv (offline, real HOME for its cache) so that
# the ckdl lookup is exercised for real.
# shellcheck disable=SC2015,SC2016  # A && ok || fail asserts; stub bodies are literal code
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
DEPLOY="$BIN_DIR/deploy-dotfiles.sh"
ETCFILES="$BIN_DIR/etcfiles"
GENCOLOR="$BIN_DIR/generate-color-scheme.sh"
WALLRANDOM="$BIN_DIR/wallpaper-random.sh"
REAL_HOME="$HOME"
REAL_UV="$(command -v uv)"
FILTER="${1:-}"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/deploy-tests.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

# Real tools allowed on PATH (no side effects outside the temp dirs)
SYSBIN="$WORK/sysbin"
mkdir -p "$SYSBIN"
for c in bash sh env cat sed grep awk find sort tr mktemp rm mkdir mv cp ls \
         basename dirname readlink realpath date head tail wc diff sleep shuf \
         touch chmod tee cut ln less cmp uniq python3 uname id true false yes unshare cksum mkfifo; do
    ln -s "$(command -v "$c")" "$SYSBIN/$c"
done

PASS=0
FAIL=0
FAILED=()
CURRENT=""

ok()   { PASS=$((PASS + 1)); }
fail() { FAIL=$((FAIL + 1)); FAILED+=("$CURRENT: $*"); echo "    FAIL: $*"; }
assert_eq()       { [[ "$1" == "$2" ]] && ok || fail "${3:-} expected '$2', got '$1'"; }
assert_contains() { grep -qE -- "$2" "$1" && ok || fail "'$1' should match /$2/"; }
assert_not()      { grep -qE -- "$2" "$1" && fail "'$1' should not match /$2/" || ok; }
assert_file()     { [[ -e "$1" ]] && ok || fail "missing file $1"; }
assert_no_file()  { [[ ! -e "$1" ]] && ok || fail "unexpected file $1"; }

# stub <name> <body>. If $STUB_DIR/fail-<name> exists and its content (a regex)
# matches the arguments, the stub records the call and exits 1 instead.
stub() {
    printf '#!/bin/bash\necho "%s $*" >> "$STUB_DIR/calls.log"\n' "$1" > "$T/bin/$1"
    printf 'f="$STUB_DIR/fail-%s"\nif [[ -e "$f" ]] && grep -qE -- "$(cat "$f")" <<< "$*"; then echo "stub %s failed" >&2; exit 1; fi\n' "$1" "$1" >> "$T/bin/$1"
    printf '%s\n' "$2" >> "$T/bin/$1"
    chmod +x "$T/bin/$1"
}
fail_on() { printf '%s' "$2" > "$T/fail-$1"; }  # fail_on <stub> <args regex>
latest_log() { find "$HOME" -maxdepth 1 -name 'deploy-*.log' | head -1; }

setup() {
    T=$(mktemp -d "$WORK/t.XXXXXX")
    export STUB_DIR="$T" REAL_HOME REAL_UV
    export HOME="$T/home"
    export PATH="$T/bin:$SYSBIN"
    export SYSTEM_PRESET_DIR="$T/root/etc/systemd/system-preset"
    export DEPLOY_COUNTDOWN=2
    unset PKGNOTE_MACHINES_FILE ETCFILES_DIR ETCFILES_ROOT ETCFILES_TTY MATUGEN_CONFIG DYNAMIC_JSON
    mkdir -p "$T/bin" "$HOME/.config/git" "$HOME/.config/matugen/themes" "$HOME/.dotfiles"
    : > "$T/calls.log"
    cd "$T"

    stub sudo 'exec "$@"'
    stub pacman ''
    stub matugen ''
    stub awww '[[ "$1" == query ]] && cat "$STUB_DIR/awww_current" 2>/dev/null; exit 0'
    stub hostnamectl 'case "$1" in hostname) echo newbox ;; chassis) echo laptop ;; *) exit 1 ;; esac'
    # read-only detection commands used by machine-init.py
    stub lspci 'echo "00:02.0 VGA compatible controller [0300]: Intel Corporation Foo [8086:a7a0]"'
    # bootctl as a normal user: is-installed cannot open the ESP; status reads EFI variables
    stub bootctl '
case "$1" in
    is-installed) echo "Failed to open file system \"/efi\": Permission denied" >&2; exit 1 ;;
    status) cat <<EOT
systemd-boot not installed in ESP.
System:
      Firmware: n/a (n/a)
   Secure Boot: disabled
  TPM2 Support: yes

Current Boot Loader:
        Product: systemd-boot 258.1-1-arch
       Features: x Boot counting
EOT
    ;;
esac'
    stub findmnt 'case "$*" in "-no FSTYPE /") echo btrfs ;; "-no SOURCE /") echo "/dev/mapper/root[/@]" ;; esac'
    stub lsblk 'printf "crypt\npart\ndisk\n"'
    printf 'vendor_id\t: GenuineIntel\n' > "$T/cpuinfo"
    export MACHINE_INIT_PROC_CPUINFO="$T/cpuinfo" MACHINE_INIT_GRUB_DIR="$T/nogrub" MACHINE_INIT_EFIVARS="$T/noefivars"
    stub fc-list 'cat "$STUB_DIR/fonts" 2>/dev/null; exit 0'
    stub uv 'if [[ "$1" == run ]]; then shift; exec env HOME="$REAL_HOME" "$REAL_UV" run --offline "$@"; fi; exit 1'
    stub pkgnote '
args=("$@")
[[ "${args[0]}" == --machine ]] && args=("${args[@]:2}")
case "${args[0]} ${args[1]:-}" in
    "machine classes")
        [[ "$1" == --machine ]] && ! grep -q "^\[$2\]" "$HOME/.config/machines.toml" && exit 1
        cat "$STUB_DIR/pkgnote_classes" ;;
esac
exit 0'
    stub yadm '
[[ "$1" == --yadm-repo ]] && shift 2
case "$1" in
    config) if [[ $# -eq 2 && "$2" != --* ]]; then cat "$STUB_DIR/yadm_hostname" 2>/dev/null || exit 1; fi ;;
    remote) echo "https://github.com/example/dotfiles.git" ;;
esac
exit 0'
    stub git '
if [[ "$1" == clone ]]; then
    url="${*: -2:1}" dest="${*: -1}"
    mkdir -p "$dest/.git"
    [[ "$url" == *aur.archlinux.org* ]] && printf "pkgname=%s\n# fake PKGBUILD\n" "$(basename "$url" .git)" > "$dest/PKGBUILD"
fi
exit 0'
    stub makepkg '
h=$(basename "$PWD"); h=${h%-bin}
printf "#!/bin/bash\n" > "$STUB_DIR/bin/$h"; chmod +x "$STUB_DIR/bin/$h"'
    stub etcfiles '
[[ " $* " == *" -n "* ]] && exit 0
for f in "${ETCFILES_DIR:-$HOME/.local/share/etcfiles}"/systemd/system-preset/*; do
    [[ "$f" == *"##"* ]] && continue
    mkdir -p "$SYSTEM_PRESET_DIR"; cp -L "$f" "$SYSTEM_PRESET_DIR/"
done'
    stub systemctl '
scope=system; [[ "$1" == --user ]] && { scope=user; shift; }
cmd="$1"; shift
db="$STUB_DIR/units-$scope"; touch "$db"
case "$cmd" in
    is-enabled)
        st=$(awk -v u="$1" "\$1==u {print \$2}" "$db")
        [[ -n "$st" ]] || { echo not-found; exit 4; }
        echo "$st"; [[ "$st" == enabled ]] ;;
    is-active) [[ "$1" == --quiet ]] && shift; grep -qx "$1" "$STUB_DIR/active-$scope" 2>/dev/null ;;
    enable|preset) for u; do [[ "$u" == --* ]] && continue; sed -i "s/^$u .*/$u enabled/" "$db"; done ;;
esac'

    # Fictional machine database and dotfiles data (real list files are copied)
    cat > "$HOME/.config/machines.toml" <<'EOF'
# List of machines using this dotfiles
[knownbox]
form = "laptop"
cpu = "intel-cpu"
gpu = "intel-gpu"
bootloader = "systemd-boot"
filesystem = "btrfs"
encryption = "luks"
secureboot = "none"
roles = ["work"]
EOF
    mkdir -p "$HOME/.local/share/deploy-dotfiles"
    cp "$REAL_HOME/.local/share/deploy-dotfiles/machine-init.py" "$HOME/.local/share/deploy-dotfiles/"
    echo knownbox > "$T/yadm_hostname"
    printf 'laptop\nbtrfs\nwork\n' > "$T/pkgnote_classes"
    local pd="$HOME/.local/share/etcfiles/systemd/system-preset"
    mkdir -p "$pd" "$HOME/.config/dotfiles/user-services"
    cp "$REAL_HOME/.local/share/etcfiles/systemd/system-preset/"* "$pd/"
    ln -s '50-dotfiles-btrfs.preset##class.btrfs' "$pd/50-dotfiles-btrfs.preset"
    cp "$REAL_HOME/.config/dotfiles/user-services/common.list" "$HOME/.config/dotfiles/user-services/"
    cp "$REAL_HOME/.config/matugen/default-colors.kdl" "$HOME/.config/matugen/"
    # Packages "installed": all system/user units exist but are disabled
    printf '%s disabled\n' NetworkManager.service bluetooth.service firewalld.service \
        greetd.service sshd.service tailscaled.service snapper-timeline.timer snapper-cleanup.timer > "$T/units-system"
    printf '%s disabled\n' waybar.service awww-daemon.service wallpaper-random.timer > "$T/units-user"
    printf 'Pancake Sans,Pancake Sans Bold\nMaple Syrup Mono\nNoto Sans\n' > "$T/fonts"
}

# machine-init.py answers that keep an existing machine (hostname, 7 keys, roles)
KEEP='\n\n\n\n\n\n\n\n\n'

run_deploy() {  # run_deploy <stdin string> <args...>; sets RC, output in $T/out
    local input="$1"; shift
    RC=0
    (cd "$T" && printf '%b' "$input" | "$DEPLOY" "$@") > "$T/out" 2>&1 || RC=$?
}

snapshot() { (cd "$1" && find . -path ./.cache -prune -o -printf '%p %s %T@ %l\n' | sort); }

# ---------------------------------------------------------------- deploy-dotfiles.sh

test_root_refusal() {
    command -v unshare > /dev/null || { echo "    (skip: no unshare)"; return; }
    RC=0
    "$(command -v unshare)" -r "$DEPLOY" --dry-run > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 1 "exit code"
    assert_contains "$T/out" "do not run this as root"
    assert_eq "$(wc -l < "$T/calls.log")" 0 "no commands called"
}

test_help() {
    run_deploy "" --help
    assert_eq "$RC" 0
    assert_contains "$T/out" 'sudo pacman -S git yadm'
    assert_contains "$T/out" 'yadm --yadm-repo ~/.dotfiles clone https://github.com/fairy-lettuce/dotfiles.git'
}

test_dry_run_changes_nothing() {
    rm "$T/bin/uv"  # also: python/uv "missing" -> pacman only printed
    local before after
    before=$(snapshot "$HOME")
    run_deploy "" --dry-run
    after=$(snapshot "$HOME")
    assert_eq "$RC" 0 "exit code"
    assert_eq "$after" "$before" "HOME snapshot"
    assert_no_file "$SYSTEM_PRESET_DIR"
    local c="$T/calls.log"
    assert_not "$c" '^sudo '
    assert_not "$c" '^pacman '
    assert_not "$c" '^systemctl (--user )?(enable|preset|start|disable)'
    assert_not "$c" '^yadm .*(config (--add|--unset|local\.(hostname|class) )|alt)'
    assert_not "$c" '^git '
    assert_not "$c" '^makepkg'
    assert_not "$c" '^matugen'
    assert_contains "$T/out" '\+ python3 ~/.local/share/deploy-dotfiles/machine-init.py --machine knownbox --noconfirm --dry-run'
    assert_contains "$c" '^pkgnote deploy --machine knownbox --aur-helper paru --dry-run$'
    assert_contains "$c" '^etcfiles -n deploy$'
    assert_not "$c" '^etcfiles deploy'
    assert_contains "$T/out" 'would run: sudo pacman -S --needed uv'
    assert_contains "$T/out" 'would run: sudo systemctl preset --preset-mode=enable-only snapper-timeline.timer snapper-cleanup.timer NetworkManager.service .*tailscaled.service$'
    assert_contains "$T/out" 'would run: systemctl --user enable waybar.service awww-daemon.service wallpaper-random.timer'
    assert_contains "$T/out" 'would run: yadm alt'
    assert_contains "$T/out" 'would save this report'
    assert_eq "$(sed -n 1p "$T/out")" "Make sure this machine stays powered (plug in the AC adapter) during deployment." "power notice first"
    assert_contains "$T/out" 'yadm alt is not run, so per-machine alternates'
    assert_eq "$(find "$HOME" -maxdepth 1 -name 'deploy-*' | wc -l)" 0 "no log file"
}

test_machine_init_failure_is_fatal() {
    printf '[knownbox]
encryption = true
' > "$HOME/.config/machines.toml"
    run_deploy '' --noconfirm
    assert_eq "$RC" 1
    assert_contains "$T/out" 'machine-init: error: \[knownbox\] encryption: values must be strings'
    assert_contains "$T/out" 'machine-init.py failed'
    assert_not "$T/calls.log" '^pkgnote deploy'
    assert_contains "$(latest_log)" 'stopped early \(exit status 1\) during step: 2\. Machine identity'
}

test_broken_machines_toml_is_fatal_not_new() {
    printf '[knownbox\nform = "laptop"\n' > "$HOME/.config/machines.toml"
    run_deploy '' --noconfirm
    assert_eq "$RC" 1
    assert_contains "$T/out" 'cannot read ~/.config/machines.toml \(see above\)'
    assert_contains "$T/out" 'machines.toml: '
    assert_not "$T/out" 'WARNING!|machine-init.py --machine'
    run_deploy '' --dry-run --noconfirm
    assert_eq "$RC" 1 "dry-run too"
    assert_not "$T/out" 'is not in'
}

# Start deploy in its own process group reading from a FIFO; wait for <regex>
# in its output, then send SIGINT to the whole group (like Ctrl-C).
interrupt_at() {  # interrupt_at <regex> <stdin answers> <args...>
    local pattern="$1" input="$2"; shift 2
    mkfifo "$T/fifo"
    set -m
    (cd "$T" && exec "$DEPLOY" "$@" < "$T/fifo" > "$T/out" 2>&1) &
    local pid=$!
    set +m
    exec 3> "$T/fifo"
    printf '%b' "$input" >&3
    local i
    for ((i = 0; i < 100; i++)); do
        grep -qE -- "$pattern" "$T/out" 2> /dev/null && break
        sleep 0.1
    done
    sleep 0.2
    kill -INT -- "-$pid"
    RC=0
    wait "$pid" || RC=$?
    exec 3>&-
}

test_ctrl_c_in_deploy_prompt() {
    stub yay ''
    interrupt_at 'Clone the wallpapers repo' "${KEEP}y\n"
    assert_eq "$RC" 130 "exit code"
    assert_contains "$T/out" '^Interrupted\.$'
    assert_contains "$(latest_log)" 'Interrupted \(Ctrl-C\) during step: 5\. Wallpapers'
    assert_not "$T/calls.log" '^git clone|^etcfiles|systemctl --user enable'
}

test_ctrl_c_in_machine_init() {
    local before
    before=$(cksum < "$HOME/.config/machines.toml")
    interrupt_at 'hostname\*\* \(default' ''
    assert_eq "$RC" 130 "exit code"
    assert_contains "$T/out" 'machine-init: interrupted; nothing was written'
    assert_not "$T/out" 'Traceback'
    assert_contains "$(latest_log)" 'Interrupted \(Ctrl-C\) during step: 2\. Machine identity'
    assert_eq "$(cksum < "$HOME/.config/machines.toml")" "$before" "machines.toml unchanged"
    assert_not "$T/calls.log" '^pkgnote deploy'
}

test_dry_run_new_machine_prints_toml() {
    rm "$T/yadm_hostname"
    local before
    before=$(cat "$HOME/.config/machines.toml")
    run_deploy '' --dry-run --noconfirm
    assert_eq "$RC" 0
    assert_contains "$T/out" "'newbox' is not in"
    assert_contains "$T/out" '\[dry-run\] would write'
    assert_contains "$T/out" '^\[newbox\]$'
    assert_contains "$T/out" '^gpu = "intel-gpu"$'
    assert_eq "$(cat "$HOME/.config/machines.toml")" "$before" "machines.toml unchanged"
    assert_contains "$T/out" 'pkgnote machine classes failed'
}

test_full_run_interactive() {
    # helper: paru (default), bin (default), makepkg y; wallpapers: clone y, default path;
    # etcfiles: d, then y; system Proceed: default; user Proceed: default
    run_deploy "$KEEP"'\n\ny\n\n\nd\ny\n\n\n'
    assert_eq "$RC" 0 "exit code"
    local c="$T/calls.log"
    assert_contains "$T/out" '\+ python3 ~/.local/share/deploy-dotfiles/machine-init.py --machine knownbox$'
    assert_contains "$T/out" '\*\*hostname\*\* \(default: knownbox\): '
    assert_contains "$c" '^pkgnote --machine knownbox machine classes$'
    assert_contains "$c" "^yadm --yadm-repo $HOME/.dotfiles config local.hostname knownbox$"
    assert_contains "$c" '^yadm .* config --unset-all local.class$'
    assert_contains "$c" '^yadm .* config --add local.class btrfs$'
    assert_contains "$c" '^yadm .* alt$'
    assert_contains "$c" '^git clone --depth 1 https://aur.archlinux.org/paru-bin.git '
    assert_contains "$T/out" 'fake PKGBUILD'
    assert_contains "$c" '^makepkg -si$'
    assert_contains "$c" '^pkgnote deploy --machine knownbox --aur-helper paru$'
    assert_contains "$c" "^git clone https://github.com/fairy-lettuce/wallpapers.git $HOME/.local/share/wallpapers$"
    assert_no_file "$HOME/.config/dotfiles/wallpaper-random.local"
    assert_contains "$c" '^matugen color hex ffffff$'
    assert_contains "$HOME/.config/matugen/themes/dynamic.json" '"#ecbe7f"'
    assert_eq "$(grep -E '^etcfiles' "$c" | tr '\n' '|')" 'etcfiles -n deploy|etcfiles deploy|' "etcfiles calls"
    assert_contains "$c" '^sudo systemctl preset --preset-mode=enable-only snapper-timeline.timer snapper-cleanup.timer NetworkManager.service bluetooth.service firewalld.service greetd.service sshd.service tailscaled.service$'
    assert_contains "$c" '^systemctl --user enable waybar.service awww-daemon.service wallpaper-random.timer$'
    assert_not "$c" 'systemctl.* (start|--now)'
    local log
    log=$(find "$HOME" -maxdepth 1 -name 'deploy-*.log' | head -1)
    assert_file "$log"
    [[ "$(basename "$log")" =~ ^deploy-[0-9]{8}-[0-9]{6}\.log$ ]] && ok || fail "log name $log"
    assert_contains "$log" 'sshd.service \(system\) was enabled but is not running: sudo systemctl start sshd.service'
    assert_contains "$log" 'waybar.service \(user\) was enabled but is not running: systemctl --user start waybar.service'
    assert_contains "$log" 'remote set-url origin git@github.com:fairy-lettuce/dotfiles.git'
    assert_contains "$log" 'create ~/.config/git/config.local'
    assert_contains "$log" 'tailscale up'
    assert_contains "$log" 'fwupdmgr'
    assert_not "$log" 'Missing fonts'
    assert_contains "$HOME/.local/state/deploy-dotfiles/managed-units.txt" '^system snapper-cleanup.timer$'
    assert_contains "$HOME/.local/state/deploy-dotfiles/managed-units.txt" '^user wallpaper-random.timer$'

    # Rerun: nothing left to enable, no second preset/enable, AUR helper skip prompt
    : > "$c"
    run_deploy "$KEEP"'y\n\n\ny\n'
    assert_eq "$RC" 0 "rerun exit code"
    assert_contains "$T/out" 'already has an AUR helper installed \(paru\)\. Skip installing AUR helper\(s\)\? \[y/n\]: '
    assert_contains "$T/out" 'wallpapers already cloned'
    assert_not "$c" '^makepkg'
    assert_not "$c" 'systemctl (--user )?(enable|preset)'
    assert_contains "$T/out" 'all listed system units are already enabled'
    assert_contains "$T/out" 'all listed user units are already enabled'
}

test_etcfiles_prompt_n() {
    stub yay ''
    run_deploy "$KEEP"'y\n\n\nx\nd\nd\nn\n\n'
    assert_eq "$RC" 0 "exit code"
    assert_contains "$T/out" 'Copy config files to /etc using etcfiles\? If you want to dry-run, type "d" and you can try again later\. \[y/n/d\]: '
    assert_contains "$T/out" 'Please answer y or n or d'
    assert_eq "$(grep -cE '^etcfiles -n deploy$' "$T/calls.log")" 2 "dry-run count"
    assert_not "$T/calls.log" '^etcfiles deploy'
    assert_not "$T/calls.log" 'systemctl preset'
    assert_contains "$T/calls.log" '^pkgnote deploy --machine knownbox --aur-helper yay$'
    assert_contains "$T/calls.log" '^systemctl --user enable'
    assert_not "$HOME/.local/state/deploy-dotfiles/managed-units.txt" '^system '
}

test_noconfirm_known_machine() {
    run_deploy '' --noconfirm
    assert_eq "$RC" 0 "exit code"
    local c="$T/calls.log"
    assert_contains "$T/out" 'machine-init.py --machine knownbox --noconfirm$'
    assert_not "$T/out" 'machines.toml was updated'
    assert_not "$T/out" 'WARNING!'
    assert_contains "$c" '^makepkg -si --noconfirm$'
    assert_contains "$T/out" 'fake PKGBUILD'
    assert_contains "$c" '^pkgnote deploy --machine knownbox --aur-helper paru --noconfirm$'
    assert_contains "$c" '^etcfiles deploy$'
}

test_countdown_abort() {
    rm "$T/yadm_hostname"
    run_deploy '' --noconfirm
    assert_eq "$RC" 1 "exit code"
    assert_contains "$T/out" '^\[WARNING!\] Looks like this machine is new\. THE HOSTNAME ASSIGNED HERE \(newbox\) WILL BE PUBLIC ONLINE\.$'
    assert_contains "$T/out" '^  Press \*\*Enter\*\* to continue'
    assert_contains "$T/out" 'aborted in 2\.\.\.'
    assert_contains "$T/out" 'aborted in 1\.\.\.'
    assert_contains "$T/out" '^Deploy aborted\.$'
    assert_contains "$T/out" "write the hostname of this machine to \`$HOME/.config/machines.toml\` before"
    assert_not "$T/out" 'machine-init.py'
    assert_not "$T/calls.log" '^pkgnote deploy'
}

test_countdown_enter() {
    rm "$T/yadm_hostname"
    run_deploy '\n' --noconfirm
    assert_eq "$RC" 0 "exit code"
    assert_contains "$T/out" 'WARNING!'
    assert_contains "$T/out" 'machine-init.py --machine newbox --noconfirm$'
    assert_contains "$T/calls.log" '^pkgnote deploy --machine newbox '
    assert_contains "$HOME/.config/machines.toml" '^\[newbox\]$'
    assert_contains "$HOME/.config/machines.toml" '^encryption = "luks"$'
    assert_contains "$HOME/.config/machines.toml" '^\[knownbox\]$'
    assert_contains "$HOME/.config/machines.toml" '^# List of machines using this dotfiles$'
    assert_contains "$(latest_log)" 'machines.toml was updated; review and commit it \(it is public\)'
}

test_countdown_other_key() {
    rm "$T/yadm_hostname"
    RC=0
    # key -> interactive machine-init: hostname, public y, 7 keys (gpu typed), roles
    (cd "$T" && { printf ' '; sleep 0.5; printf '\ny\n\n\nintel-gpu, nvidia-gpu\n\n\n\n\nwork\nq\n'; } |
        "$DEPLOY" --noconfirm) > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 0 "exit code"
    assert_contains "$T/out" 'machine-init.py --machine newbox$'
    assert_contains "$T/out" 'will be PUBLIC on GitHub'
    assert_contains "$HOME/.config/machines.toml" '^gpu = \["intel-gpu", "nvidia-gpu"\]$'
    assert_contains "$HOME/.config/machines.toml" '^roles = \["work"\]$'
}

test_font_report() {
    printf 'Pancake Sans\nNoto Sans,Maple Sugar\nDejaVu Sans\n' > "$T/fonts"
    run_deploy '' --noconfirm
    local log
    log=$(find "$HOME" -maxdepth 1 -name 'deploy-*.log' | head -1)
    assert_contains "$log" 'Missing fonts:'
    assert_contains "$log" 'No font family matching /\^Maple Syrup/'
    assert_not "$log" 'matching /\^Pancake/'
    # comma-separated second family counts (Maple Syrup Mono as alias)
    printf 'Foo,Maple Syrup Mono\n' > "$T/fonts"
    rm "$HOME"/deploy-*.log
    run_deploy '' --noconfirm
    log=$(find "$HOME" -maxdepth 1 -name 'deploy-*.log' | head -1)
    assert_contains "$log" 'matching /\^Pancake/'
    assert_not "$log" 'matching /\^Maple Syrup/'
}

test_service_lists() {
    local ud="$HOME/.config/dotfiles/user-services"
    cat > "$ud/common.list" <<'EOF'
# comment
enable waybar.service

enable awww-daemon.service
disable foo.service
enable missing.service
EOF
    printf 'enable laptop-only.service\n' > "$ud/laptop.list##class.laptop"
    printf 'enable desktop-only.service\n' > "$ud/desk.list##class.desktop"
    ln -s 'laptop.list##class.laptop' "$ud/laptop.list"
    printf 'enable masked.service' > "$ud/nonl.list"   # no trailing newline
    printf '%s\n' 'waybar.service enabled' 'awww-daemon.service disabled' \
        'laptop-only.service disabled' 'desktop-only.service disabled' 'masked.service masked' \
        'old.service enabled' 'gone.service disabled' > "$T/units-user"
    echo awww-daemon.service > "$T/active-user"
    # system: only the btrfs alternate selected; base 50-dotfiles.preset removed
    local pd="$HOME/.local/share/etcfiles/systemd/system-preset"
    rm "$pd/50-dotfiles.preset"
    mkdir -p "$HOME/.local/state/deploy-dotfiles"
    printf '%s\n' 'system old-sys.service' 'user old.service' 'user gone.service' 'user waybar.service' \
        > "$HOME/.local/state/deploy-dotfiles/managed-units.txt"
    echo 'old-sys.service enabled' >> "$T/units-system"
    run_deploy '' --noconfirm
    assert_eq "$RC" 0 "exit code"
    local c="$T/calls.log" log
    log=$(find "$HOME" -maxdepth 1 -name 'deploy-*.log' | head -1)
    assert_contains "$c" '^systemctl --user enable awww-daemon.service laptop-only.service$'
    assert_not "$c" 'desktop-only'
    assert_contains "$c" '^sudo systemctl preset --preset-mode=enable-only snapper-timeline.timer snapper-cleanup.timer$'
    assert_contains "$T/out" 'ignoring unsupported line: disable foo.service'
    assert_contains "$log" 'missing.service \(user\): unit file not found'
    assert_contains "$log" 'masked.service \(user\) is masked'
    assert_contains "$log" 'old.service \(user\) is no longer listed but still enabled; if unneeded: systemctl --user disable old.service'
    assert_contains "$log" 'old-sys.service \(system\) is no longer listed but still enabled; if unneeded: sudo systemctl disable old-sys.service'
    assert_not "$log" 'gone.service'
    assert_not "$log" 'waybar.service \(user\) is no longer'
    assert_not "$log" 'awww-daemon.service \(user\) was enabled but is not running'
    assert_contains "$log" 'laptop-only.service \(user\) was enabled but is not running'
    local st="$HOME/.local/state/deploy-dotfiles/managed-units.txt"
    assert_eq "$(grep -c '^user ' "$st")" 5 "user state lines"
    assert_contains "$st" '^user masked.service$'
    assert_contains "$st" '^system snapper-timeline.timer$'
    assert_not "$st" 'old'
}

test_wallpaper_custom_path() {
    stub paru ''
    run_deploy "$KEEP"'y\ny\n~/pics/walls\nn\n\n'
    assert_eq "$RC" 0 "exit code"
    assert_contains "$HOME/.config/dotfiles/wallpaper-random.local" '^WALLPAPER_REPO="\$HOME/pics/walls"$'
    assert_contains "$T/calls.log" "^git clone https://github.com/fairy-lettuce/wallpapers.git $HOME/pics/walls$"
    # Rerun: the .local path is the new default; already cloned -> no clone
    : > "$T/calls.log"
    run_deploy "$KEEP"'y\ny\n\nn\n\n'
    assert_contains "$T/out" 'Path \(default: ~/pics/walls\): '
    assert_contains "$T/out" 'wallpapers already cloned at ~/pics/walls'
    assert_not "$T/calls.log" '^git clone'
}

test_aur_yay_source_declined() {
    run_deploy "$KEEP"'yay\nsource\nn\n\n\nn\n\n'
    assert_eq "$RC" 0 "exit code"
    assert_contains "$T/calls.log" '^git clone --depth 1 https://aur.archlinux.org/yay.git '
    assert_not "$T/calls.log" '^makepkg'
    assert_contains "$T/calls.log" '^pkgnote deploy --machine knownbox --aur-helper yay$'
    assert_contains "$(latest_log)" 'Installing yay was declined\. yay is not installed'
}

test_noconfirm_pkgbuild_not_asked() {
    run_deploy '' --noconfirm
    assert_contains "$T/out" 'fake PKGBUILD'
    assert_contains "$T/out" 'Build and install paru-bin with makepkg -si\? \[y/n\]: y \(--noconfirm\)'
    assert_contains "$T/calls.log" '^makepkg -si --noconfirm$'
}

test_confirm_pkgbuild() {
    run_deploy 'n\n' --noconfirm --confirm-pkgbuild
    assert_eq "$RC" 0 "exit code"
    assert_contains "$T/out" 'fake PKGBUILD'
    assert_not "$T/out" 'makepkg -si\? \[y/n\]: y \(--noconfirm\)'
    assert_not "$T/calls.log" '^makepkg'
    assert_contains "$(latest_log)" 'Installing paru-bin was declined'
    run_deploy '' --help
    assert_contains "$T/out" '--confirm-pkgbuild'
}

test_countdown_drains_escape_sequence() {
    rm "$T/yadm_hostname"
    RC=0
    # Up arrow (ESC [ A), then later the machine-init answers and the PKGBUILD answer
    (cd "$T" && { printf '\033[A'; sleep 0.5; printf '\ny\n\n\n\n\n\n\n\nq\ny\n'; } |
        "$DEPLOY" --noconfirm --confirm-pkgbuild) > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 0 "exit code"
    assert_contains "$T/out" 'machine-init.py --machine newbox$'
    assert_not "$T/out" 'may only contain'
    assert_contains "$HOME/.config/machines.toml" '^\[newbox\]$'
    assert_contains "$T/calls.log" '^makepkg -si --noconfirm$'
    assert_not "$T/out" 'Please answer'
}

test_path_and_missing_tools() {
    # pkgnote only in ~/.local/bin (not on the test PATH): found via the PATH addition
    mkdir -p "$HOME/.local/bin"
    mv "$T/bin/pkgnote" "$T/bin/etcfiles" "$HOME/.local/bin/"
    run_deploy '' --noconfirm
    assert_eq "$RC" 0 "exit code with tools in ~/.local/bin"
    assert_contains "$T/calls.log" '^pkgnote deploy'
    assert_contains "$T/calls.log" '^etcfiles deploy$'
    # etcfiles missing: step 7 skipped and reported, deploy continues
    rm "$HOME/.local/bin/etcfiles"; rm -f "$HOME"/deploy-*.log
    run_deploy '' --noconfirm
    assert_eq "$RC" 0 "exit code without etcfiles"
    assert_contains "$(latest_log)" 'etcfiles not found'
    assert_contains "$T/calls.log" '^systemctl --user'
    # pkgnote missing: fatal, with a clear message
    rm "$HOME/.local/bin/pkgnote"
    run_deploy '' --noconfirm
    assert_eq "$RC" 1 "exit code without pkgnote"
    assert_contains "$T/out" 'pkgnote not found'
}

test_failures_are_reported_not_fatal() {
    fail_on pkgnote '^deploy'
    fail_on etcfiles '^deploy'
    fail_on systemctl '^(--user enable|preset)'
    fail_on matugen 'color'
    rm "$T/bin/fc-list"; stub fc-list 'exit 1'
    # presets already in /etc from an earlier run (etcfiles fails this time)
    mkdir -p "$SYSTEM_PRESET_DIR"
    cp -L "$HOME/.local/share/etcfiles/systemd/system-preset/50-dotfiles.preset" "$SYSTEM_PRESET_DIR/"
    run_deploy '' --noconfirm
    assert_eq "$RC" 0 "exit code"
    local log
    log=$(latest_log)
    assert_file "$log"
    assert_contains "$log" 'Failed or incomplete steps:'
    assert_contains "$log" '\[4\. Packages \(pkgnote deploy\)\] failed \(exit status 1\): pkgnote deploy'
    assert_contains "$log" 'failed \(exit status 1\): etcfiles deploy'
    assert_contains "$log" 'failed \(exit status 1\): sudo systemctl preset'
    assert_contains "$log" 'failed \(exit status 1\): systemctl --user enable'
    assert_contains "$log" 'matugen failed'
    assert_contains "$log" 'fc-list failed'
    assert_not "$log" 'was enabled but is not running'
    assert_contains "$HOME/.config/matugen/themes/dynamic.json" '"#ecbe7f"'
}

test_report_written_when_stopped_early() {
    # interactive run whose stdin ends in the middle (at the wallpapers prompt)
    run_deploy "$KEEP"'\n\ny\n'
    assert_eq "$RC" 1 "exit code"
    local log
    log=$(latest_log)
    assert_file "$log"
    assert_contains "$log" 'stopped early \(exit status 1\) during step: 5\. Wallpapers'
    assert_contains "$log" 'tailscale up'
    assert_contains "$T/calls.log" '^pkgnote deploy'
}

test_bootstrap() {
    # bootstrap execs $HOME/.local/bin/deploy-dotfiles.sh; HOME is the temp one
    mkdir -p "$HOME/.local/bin"
    printf '#!/bin/bash\necho "deploy called: $*"\n' > "$HOME/.local/bin/deploy-dotfiles.sh"
    chmod +x "$HOME/.local/bin/deploy-dotfiles.sh"
    "$REAL_HOME/.config/yadm/bootstrap" --noconfirm --dry-run > "$T/out" 2>&1
    assert_contains "$T/out" '^deploy called: --noconfirm --dry-run$'
}

# ---------------------------------------------------------------- etcfiles

setup_etcfiles() {
    export ETCFILES_DIR="$T/etcfiles" ETCFILES_ROOT="$T/root" ETCFILES_TTY="$T/tty"
    mkdir -p "$ETCFILES_DIR/a" "$ETCFILES_DIR/b" "$ETCFILES_DIR/c" "$ETCFILES_DIR/d##class.x" "$ETCFILES_ROOT/etc"
    echo plain > "$ETCFILES_DIR/a/plain.conf"
    echo ruan-content > "$ETCFILES_DIR/b/alt.conf##hostname.knownbox"
    echo other-content > "$ETCFILES_DIR/b/alt.conf##hostname.otherbox"
    ln -s 'alt.conf##hostname.knownbox' "$ETCFILES_DIR/b/alt.conf"
    echo unselected > "$ETCFILES_DIR/c/only.conf##class.desktop"
    echo dir-alt > "$ETCFILES_DIR/d##class.x/f.conf"
    printf 'y\n%.0s' {1..20} > "$ETCFILES_TTY"
}

test_etcfiles_dry_run() {
    setup_etcfiles
    "$ETCFILES" -n deploy > "$T/out" 2>&1
    assert_contains "$T/out" '^\[NEW\] /etc/a/plain.conf$'
    assert_contains "$T/out" '^\[NEW\] /etc/b/alt.conf$'
    assert_contains "$T/out" '\+ruan-content'
    assert_not "$T/out" '##'
    assert_not "$T/out" 'only.conf|other-content|dir-alt'
    assert_contains "$T/out" 'Summary: 0 changed, 2 new, 0 unchanged'
    assert_eq "$(find "$ETCFILES_ROOT/etc" -mindepth 1 | wc -l)" 0 "nothing written"
    assert_not "$T/calls.log" '^sudo'
}

test_etcfiles_deploy_and_fetch() {
    setup_etcfiles
    "$ETCFILES" deploy > "$T/out" 2>&1
    assert_eq "$(cat "$ETCFILES_ROOT/etc/b/alt.conf")" ruan-content "followed symlink"
    [[ -f "$ETCFILES_ROOT/etc/b/alt.conf" && ! -L "$ETCFILES_ROOT/etc/b/alt.conf" ]] && ok || fail "alt.conf should be a regular file"
    assert_file "$ETCFILES_ROOT/etc/a/plain.conf"
    assert_no_file "$ETCFILES_ROOT/etc/c"
    assert_eq "$(find "$ETCFILES_ROOT" -path '*##*' | wc -l)" 0 "no ## files deployed"
    # unchanged rerun
    "$ETCFILES" -n deploy > "$T/out" 2>&1
    assert_contains "$T/out" 'Summary: 0 changed, 0 new, 2 unchanged'
    # fetch writes through the symlink into the selected alternate
    echo edited > "$ETCFILES_ROOT/etc/b/alt.conf"
    "$ETCFILES" fetch > "$T/out" 2>&1
    assert_eq "$(cat "$ETCFILES_DIR/b/alt.conf##hostname.knownbox")" edited "fetched into alternate"
    [[ -L "$ETCFILES_DIR/b/alt.conf" ]] && ok || fail "alt.conf symlink kept"
    assert_eq "$(cat "$ETCFILES_DIR/b/alt.conf##hostname.otherbox")" other-content "other alternate untouched"
    # changed file: deploy makes a backup
    echo plain2 > "$ETCFILES_DIR/a/plain.conf"
    "$ETCFILES" deploy > "$T/out" 2>&1
    assert_contains "$T/out" '^\[CHANGED\] /etc/a/plain.conf$'
    assert_eq "$(find "$ETCFILES_ROOT/etc/a" -name 'plain.conf.bak.*' | wc -l)" 1 "backup"
}

# ---------------------------------------------------------------- generate-color-scheme.sh

setup_colors() {
    WP="$HOME/.local/share/wallpapers"
    mkdir -p "$WP/16x9"
    export DYNAMIC_JSON="$T/out.json"
}
colors_of() { grep -oE '"light": \{ "color": "#[0-9a-f]{6}"' "$DYNAMIC_JSON" | grep -oE '[0-9a-f]{6}' | tr '\n' ' '; }

test_colors_repo_entry() {
    setup_colors
    cat > "$WP/colors.kdl" <<'EOF'
color "_default" {
    primary "#111111"
    secondary "#222222"
}
color "ruan-mei" {
    primary "#a7e1d8"
}
EOF
    "$GENCOLOR" ruan-mei > "$T/out" 2>&1
    assert_eq "$(colors_of)" "a7e1d8 222222 " "name then repo _default per field"
    assert_contains "$DYNAMIC_JSON" '"dark": \{ "color": "#b5ece4" \}'
    assert_contains "$T/calls.log" '^matugen color hex ffffff$'
    assert_contains "$T/calls.log" '^uv run --no-project --quiet --with ckdl python3 '
    "$GENCOLOR" unknown > "$T/out" 2>&1
    assert_eq "$(colors_of)" "111111 222222 " "repo _default"
}

test_colors_default_file() {
    setup_colors
    printf 'color "other" {\n    primary "#333333"\n}\n' > "$WP/colors.kdl"
    "$GENCOLOR" unknown > "$T/out" 2>&1
    assert_eq "$(colors_of)" "ecbe7f e89f71 " "default-colors.kdl"
    rm -rf "$WP"
    "$GENCOLOR" > "$T/out" 2>&1
    assert_eq "$(colors_of)" "ecbe7f e89f71 " "no repo, no name"
    # MATUGEN_CONFIG relocates default-colors.kdl and dynamic.json
    unset DYNAMIC_JSON
    export MATUGEN_CONFIG="$T/mconf"
    mkdir -p "$MATUGEN_CONFIG"
    printf 'color "_default" {\n    primary "#444444"\n    secondary "#555555"\n}\n' > "$MATUGEN_CONFIG/default-colors.kdl"
    "$GENCOLOR" > "$T/out" 2>&1
    DYNAMIC_JSON="$MATUGEN_CONFIG/themes/dynamic.json" colors_of > "$T/c"
    assert_eq "$(cat "$T/c")" "444444 555555 " "MATUGEN_CONFIG"
    assert_no_file "$HOME/.config/matugen/themes/dynamic.json"
}

test_colors_malformed_kdl() {
    setup_colors
    printf 'color "foo" {\n    primary "#123456"\n' > "$WP/colors.kdl"   # unclosed
    RC=0
    "$GENCOLOR" foo > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 0 "exit code"
    assert_eq "$(colors_of)" "ecbe7f e89f71 " "fell back to default-colors.kdl"
    assert_contains "$T/out" "Warning: skipping $WP/colors.kdl"
    assert_not "$T/out" 'Traceback'
}

test_colors_matugen_fails() {
    setup_colors
    fail_on matugen 'color'
    RC=0
    "$GENCOLOR" > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 2 "exit code"
    assert_contains "$T/out" 'matugen exited with status 1'
    assert_contains "$DYNAMIC_JSON" '"#ecbe7f"'
}

test_colors_legacy_toml() {
    setup_colors
    cat > "$WP/colors.toml" <<'EOF'
[color._default]
primary = "#666666"

[color.foo]
primary = "#777777"
secondary = "#888888"
EOF
    "$GENCOLOR" foo > "$T/out" 2>&1
    assert_eq "$(colors_of)" "777777 888888 " "toml entry"
    "$GENCOLOR" bar > "$T/out" 2>&1
    assert_eq "$(colors_of)" "666666 e89f71 " "toml _default, then default-colors.kdl"
}

test_colors_local_override() {
    setup_colors
    mkdir -p "$T/elsewhere" "$HOME/.config/dotfiles"
    printf 'color "foo" {\n    primary "#999999"\n    secondary "#aaaaaa"\n}\n' > "$T/elsewhere/colors.kdl"
    echo "WALLPAPER_REPO=\"$T/elsewhere\"" > "$HOME/.config/dotfiles/wallpaper-random.local"
    "$GENCOLOR" foo > "$T/out" 2>&1
    assert_eq "$(colors_of)" "999999 aaaaaa " "wallpaper-random.local"
}

test_colors_no_colors_fails() {
    setup_colors
    rm "$HOME/.config/matugen/default-colors.kdl"
    RC=0
    "$GENCOLOR" > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 1
    assert_contains "$T/out" 'no valid color found'
    assert_not "$T/calls.log" '^matugen'
}

test_wallpaper_random() {
    setup_colors
    printf 'color "pic" {\n    primary "#123456"\n    secondary "#654321"\n}\n' > "$WP/colors.kdl"
    touch "$WP/16x9/pic.png"
    "$WALLRANDOM" > "$T/out" 2>&1
    assert_contains "$T/calls.log" "^awww img $WP/16x9/pic.png -t none$"
    assert_eq "$(colors_of)" "123456 654321 " "colors for the chosen wallpaper"
}

# ---------------------------------------------------------------- main

for t in $(declare -F | awk '{print $3}' | grep '^test_'); do
    [[ -z "$FILTER" || "$t" == *"$FILTER"* ]] || continue
    CURRENT="$t"
    echo "  $t"
    setup
    before=$FAIL
    "$t" || fail "test aborted (exit $?)"
    if [[ $FAIL -gt $before ]]; then
        echo "    --- output ---"; sed 's/^/    | /' "$T/out" 2> /dev/null | tail -40
        echo "    --- calls ---"; sed 's/^/    | /' "$T/calls.log" | tail -40
    fi
done

echo
echo "$PASS passed, $FAIL failed"
for f in "${FAILED[@]}"; do echo "  $f"; done
[[ $FAIL -eq 0 ]]
