#!/bin/bash
# deploy-dotfiles.sh - set up this machine from the dotfiles (yadm) repo
#
# Safe to rerun: every step checks the current state first.
# Called by ~/.config/yadm/bootstrap.
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
    echo "Error: do not run this as root. Run it as your normal user; sudo is used where needed." >&2
    exit 1
fi

# On a fresh machine ~/.local/bin (pkgnote, etcfiles, ...) is not on PATH yet.
PATH="$HOME/.local/bin:$PATH"

DRY_RUN=false
NOCONFIRM=false
CONFIRM_PKGBUILD=false

MACHINES_TOML="${PKGNOTE_MACHINES_FILE:-$HOME/.config/machines.toml}"
SYSTEM_SERVICES_DIR="$HOME/.config/dotfiles/system-services"
SSHD_CONFIG_DIR="${SSHD_CONFIG_DIR:-/etc/ssh}"                     # overridable for tests
SNAPPER_CONFIGS_DIR="${SNAPPER_CONFIGS_DIR:-/etc/snapper/configs}"  # overridable for tests
USER_SERVICES_DIR="$HOME/.config/dotfiles/user-services"
STATE_FILE="$HOME/.local/state/deploy-dotfiles/managed-units.txt"
WALLPAPER_LOCAL="$HOME/.config/dotfiles/wallpaper-random.local"
WALLPAPER_DEFAULT="$HOME/.local/share/wallpapers"
WALLPAPER_URL="https://github.com/fairy-lettuce/wallpapers.git"
DOTFILES_SSH_URL="git@github.com:fairy-lettuce/dotfiles.git"
MACHINE_INIT="$HOME/.local/share/deploy-dotfiles/machine-init.py"
COUNTDOWN="${DEPLOY_COUNTDOWN:-10}"
LOG_FILE="$HOME/deploy-$(date +%Y%m%d-%H%M%S).log"
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Self-made fonts not distributed as packages (family name regexes for fc-list)
FONT_PATTERNS=('^Pancake' '^Maple Syrup')

usage() {
    cat <<'EOF'
deploy-dotfiles.sh - set up this machine from the dotfiles repo

Prerequisites (manual, on a fresh install):
  sudo pacman -S git yadm diffutils
  yadm --yadm-repo ~/.dotfiles clone https://github.com/fairy-lettuce/dotfiles.git

Steps: python/uv -> machine identity (machine-init.py, yadm alt)
  -> AUR helper -> pkgnote deploy -> wallpapers -> initial color scheme
  -> /etc files (etcfiles) -> system services -> user services -> things to do (also
  saved to ~/deploy-<YYYYMMDD-HHMMSS>.log)

Usage: deploy-dotfiles.sh [--dry-run] [--noconfirm [--confirm-pkgbuild]]

Options:
  --dry-run           Show what each step would do; change nothing
  --noconfirm         Use defaults for all prompts (pkgnote deploy gets
                      --noconfirm). The AUR helper's PKGBUILD is still printed
                      but built without asking; etcfiles still asks per file.
  --confirm-pkgbuild  Ask before building the AUR helper even with --noconfirm
  -h, --help          Show this help

Run as a normal user (not root); sudo is used only where needed.
A failing step is reported at the end and the deploy continues; the report is
written even if the script stops early.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)   DRY_RUN=true ;;
        --noconfirm) NOCONFIRM=true ;;
        --confirm-pkgbuild) CONFIRM_PKGBUILD=true ;;
        -h|--help)   usage ;;
        *) echo "Error: unknown argument '$1'" >&2; usage 1 ;;
    esac
    shift
done

NC=()
[[ "$NOCONFIRM" == true ]] && NC=(--noconfirm)

yadm() { command yadm --yadm-repo "$HOME/.dotfiles" "$@"; }

TMPDIR_DEPLOY=""
CURRENT_STEP=""
REPORT_ARMED=false   # set once the steps start; the EXIT trap then writes the report
REPORT_DONE=false

on_exit() {
    local rc=$?
    set +e
    [[ -n "$TMPDIR_DEPLOY" ]] && rm -rf "$TMPDIR_DEPLOY"
    if [[ "$REPORT_ARMED" == true && "$REPORT_DONE" == false ]]; then
        if [[ "$INTERRUPTED" == true ]]; then
            REPORT_FAILED+=("Interrupted (Ctrl-C) during step: $CURRENT_STEP. Later steps did not run; rerun to continue.")
        else
            REPORT_FAILED+=("The deploy stopped early (exit status $rc) during step: $CURRENT_STEP. Later steps did not run; fix the cause and rerun.")
        fi
        step_report
    fi
    exit "$rc"
}
INTERRUPTED=false
on_int() {
    trap '' INT
    INTERRUPTED=true
    printf '\nInterrupted.\n' >&2
    exit 130
}
trap on_exit EXIT
trap on_int INT

# ---------------------------------------------------------------- helpers

step() { CURRENT_STEP="$*"; printf '\n==> %s\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '  [WARN] %s\n' "$*" >&2; }
die()  { printf 'Error: %s\n' "$*" >&2; exit 1; }

# Run a mutating command, or only print it in dry-run mode.
run() {
    if [[ "$DRY_RUN" == true ]]; then
        printf '  [dry-run] would run:'; printf ' %q' "$@"; echo
    else
        printf '  +'; printf ' %q' "$@"; echo
        [[ "$1" == sudo ]] && SUDO_USED=true
        "$@"
    fi
}
SUDO_USED=false     # sudo was used in this run (credentials are probably cached)
ETCFILES_STATUS=""  # deployed / declined / failed (empty: not asked, e.g. dry-run)
SYSTEM_LISTED=()    # units in the system-services lists

# Like run, but a failure is non-fatal: warn, add to the report, return 1.
try() {
    local rc=0
    run "$@" || rc=$?
    if [[ $rc -ne 0 ]]; then
        warn "failed (exit status $rc): $*"
        REPORT_FAILED+=("[$CURRENT_STEP] failed (exit status $rc): $*")
        return 1
    fi
}

# ask <prompt> <noconfirm default> <default on empty input, or ""> <choices regex>
# Prints the (lowercased) answer on stdout; the prompt goes to stderr.
ask() {
    local prompt="$1" nc_default="$2" empty_default="$3" valid="$4" ans
    if [[ "$NOCONFIRM" == true ]]; then
        printf '%s%s (--noconfirm)\n' "$prompt" "$nc_default" >&2
        echo "$nc_default"
        return
    fi
    while true; do
        printf '%s' "$prompt" >&2
        IFS= read -r ans || die "no input (stdin closed); use --noconfirm for unattended runs"
        ans="${ans,,}"
        [[ -z "$ans" ]] && ans="$empty_default"
        if [[ -n "$ans" && "$ans" =~ ^($valid)$ ]]; then
            echo "$ans"
            return
        fi
        echo "  Please answer ${valid//|/ or }." >&2
    done
}

# Free text input; empty (or --noconfirm) yields "".
ask_text() {
    local prompt="$1" ans=""
    if [[ "$NOCONFIRM" == true ]]; then
        printf '%s(default, --noconfirm)\n' "$prompt" >&2
        return
    fi
    printf '%s' "$prompt" >&2
    IFS= read -r ans || die "no input (stdin closed); use --noconfirm for unattended runs"
    echo "$ans"
}

tilde() { [[ "$1" == "$HOME"* ]] && echo "~${1#"$HOME"}" || echo "$1"; }

contains() {
    local needle="$1" x; shift
    for x; do [[ "$x" == "$needle" ]] && return 0; done
    return 1
}

# Report sections ("Things you may want to do")
REPORT_FONTS=()
REPORT_SERVICES=()
REPORT_MISSING_UNITS=()
REPORT_MANUAL=()
REPORT_FAILED=()
ENABLED_SYSTEM=()
ENABLED_USER=()

# ---------------------------------------------------------------- 1. python, uv

step_python() {
    step "1. Python and uv"
    local missing=()
    command -v python3 > /dev/null || missing+=(python)
    command -v uv > /dev/null || missing+=(uv)
    if [[ ${#missing[@]} -eq 0 ]]; then
        info "python and uv are installed"
        return
    fi
    run sudo pacman -S --needed "${NC[@]}" "${missing[@]}"
}

# ---------------------------------------------------------------- 2. machine identity

# True if <name> is a table in machines.toml.
# Exit status 0 if <name> is a table in machines.toml, 1 if not (or no file),
# 2 if the file cannot be parsed (message on stderr).
machine_known() {
    [[ -f "$MACHINES_TOML" ]] || return 1
    command -v python3 > /dev/null || return 1
    python3 - "$MACHINES_TOML" "$1" <<'PY'
import sys, tomllib
try:
    with open(sys.argv[1], "rb") as f:
        data = tomllib.load(f)
except (OSError, tomllib.TOMLDecodeError) as exc:
    print(f"  {sys.argv[1]}: {exc}", file=sys.stderr)
    sys.exit(2)
sys.exit(0 if sys.argv[2] in data else 1)
PY
}

# --noconfirm on an unknown machine. Returns 0 to continue with the default
# name, 1 to set up interactively; exits when nothing is pressed.
new_machine_countdown() {
    local name="$1" n key rc
    cat <<EOF
[WARNING!] Looks like this machine is new. THE HOSTNAME ASSIGNED HERE ($name) WILL BE PUBLIC ONLINE.
  Press **Enter** to continue, if you know what you're doing.
  Press **any key** (excluding Enter) to set up hostname/classes interactively.
  If you don't press any key, the whole deploying process will be aborted.
EOF
    for ((n = COUNTDOWN; n > 0; n--)); do
        printf '\rDeploying process will be aborted in %d...' "$n"
        rc=0
        IFS= read -rsn1 -t 1 key || rc=$?
        if [[ $rc -eq 0 ]]; then
            echo
            [[ -z "$key" ]] && return 0
            # drain the rest of a multi-byte key (e.g. arrow-key escape sequences)
            while IFS= read -rsn1 -t 0.1 key; do :; done
            return 1
        fi
        # EOF (not a timeout): keep counting at the same pace
        [[ $rc -gt 128 ]] || sleep 1
    done
    echo
    REPORT_ARMED=false
    echo "Deploy aborted."
    echo "If you want to suppress this warning, write the hostname of this machine to \`$MACHINES_TOML\` before running this deploy script."
    exit 1
}

MACHINE_NAME=""
MACHINE_CLASSES=()

step_machine() {
    step "2. Machine identity"
    local default_name
    default_name=$(yadm config local.hostname 2> /dev/null || true)
    [[ -n "$default_name" ]] || default_name=$(hostnamectl hostname 2> /dev/null || uname -n)

    command -v pkgnote > /dev/null ||
        die "pkgnote not found (expected ~/.local/bin/pkgnote from the dotfiles)"
    [[ -f "$MACHINE_INIT" ]] || die "machine-init.py not found at $MACHINE_INIT"
    command -v python3 > /dev/null || {
        [[ "$DRY_RUN" == true ]] || die "python3 not found"
        warn "python3 not found; dry-run skips machine-init.py"
    }

    local known=false
    local krc=0
    machine_known "$default_name" || krc=$?
    case $krc in
        0) known=true ;;
        1) ;;
        *) die "cannot read $(tilde "$MACHINES_TOML") (see above); fix the file, then rerun" ;;
    esac

    # machine-init.py prompts unless --noconfirm; dry-run never prompts.
    local init_args=(--machine "$default_name")
    if [[ "$DRY_RUN" == true ]]; then
        init_args+=(--noconfirm --dry-run)
        [[ "$NOCONFIRM" == true && "$known" == false ]] &&
            info "[dry-run] '$default_name' is not in $(tilde "$MACHINES_TOML"); the new-machine warning and countdown would be shown"
    elif [[ "$NOCONFIRM" == true ]]; then
        if [[ "$known" == true ]] || new_machine_countdown "$default_name"; then
            init_args+=(--noconfirm)
        fi
    fi

    local before after
    before=$(cksum "$MACHINES_TOML" 2> /dev/null || true)
    if command -v python3 > /dev/null; then
        printf '  + python3 %s' "$(tilde "$MACHINE_INIT")"; printf ' %q' "${init_args[@]}"; echo
        local irc=0
        MACHINE_NAME=$(PKGNOTE_MACHINES_FILE="$MACHINES_TOML" python3 "$MACHINE_INIT" "${init_args[@]}") || irc=$?
        [[ $irc -eq 130 ]] && on_int
        [[ $irc -eq 0 ]] ||
            die "machine-init.py failed; fix $(tilde "$MACHINES_TOML") or answer the prompts, then rerun"
    else
        MACHINE_NAME="$default_name"
    fi
    [[ -n "$MACHINE_NAME" ]] || die "machine-init.py returned no name"
    after=$(cksum "$MACHINES_TOML" 2> /dev/null || true)
    if [[ "$before" != "$after" ]]; then
        machines_toml_commit_note
    fi

    local classes rc=0
    classes=$(pkgnote --machine "$MACHINE_NAME" machine classes) || rc=$?
    if [[ $rc -ne 0 ]]; then
        [[ "$DRY_RUN" == true ]] || die "pkgnote machine classes failed for '$MACHINE_NAME'"
        warn "pkgnote machine classes failed (machine not in machines.toml yet?)"
    fi
    [[ -n "$classes" ]] && mapfile -t MACHINE_CLASSES <<< "$classes"

    info "name: $MACHINE_NAME"
    info "classes: ${MACHINE_CLASSES[*]:-(unknown)}"
    try yadm config local.hostname "$MACHINE_NAME" || true
    if [[ "$DRY_RUN" == true ]]; then
        run yadm config --unset-all local.class
    else
        yadm config --unset-all local.class || true
    fi
    local c
    for c in "${MACHINE_CLASSES[@]}"; do
        try yadm config --add local.class "$c" || true
    done
    try yadm alt || true
    if [[ "$DRY_RUN" == true ]]; then
        info "[dry-run] note: yadm alt is not run, so per-machine alternates (##class/##hostname) are not created;"
        info "          files and units selected by alternates may be missing from this preview."
    fi
}

# Report item for committing machines.toml, with a leak-check / user.email check.
# Only the hook commands (grepped, never printed) and user.email are read from git config.
machines_toml_commit_note() {
    REPORT_MANUAL+=("$(tilde "$MACHINES_TOML") was updated; review and commit it (it is public): yadm --yadm-repo ~/.dotfiles add ~/.config/machines.toml && yadm --yadm-repo ~/.dotfiles commit")
    local email
    email=$(yadm gitconfig --get user.email 2> /dev/null || true)
    REPORT_MANUAL+=("The dotfiles repo would commit as user.email: ${email:-(not set)}")
    if ! yadm gitconfig --get-regexp '^hook\..*\.command' 2> /dev/null | grep -q git-leakcheck; then
        REPORT_MANUAL+=("WARNING: the leak-check hook (git-leakcheck) is not registered, so the leak check is not active; verify that user.email above is your personal address before committing")
    fi
}

# ---------------------------------------------------------------- 3. AUR helper

AUR_HELPER=""

step_aur_helper() {
    step "3. AUR helper"
    local installed=() h
    for h in paru yay; do
        command -v "$h" > /dev/null && installed+=("$h")
    done

    if [[ ${#installed[@]} -gt 0 ]]; then
        local names="${installed[*]}"
        if [[ "$DRY_RUN" == true ]]; then
            info "[dry-run] already installed: ${names// /, } (would ask whether to skip)"
            AUR_HELPER="${installed[0]}"
            return
        fi
        local skip
        skip=$(ask "This machine already has an AUR helper installed (${names// /, }). Skip installing AUR helper(s)? [y/n]: " y "" 'y|n')
        if [[ "$skip" == y ]]; then
            AUR_HELPER="${installed[0]}"
            info "using $AUR_HELPER"
            return
        fi
    fi

    if [[ "$DRY_RUN" == true ]]; then
        info "[dry-run] would ask which helper (default: paru) and binary/source (default: binary)"
        info "[dry-run] would clone https://aur.archlinux.org/paru-bin.git, show the PKGBUILD, ask, then makepkg -si"
        AUR_HELPER=paru
        return
    fi

    local helper build pkg
    helper=$(ask "Which AUR helper? [paru/yay] (default: paru): " paru paru 'paru|yay')
    build=$(ask "Install the prebuilt binary (${helper}-bin) or build from source (${helper})? [bin/source] (default: bin): " bin bin 'bin|source|b|s')
    pkg="$helper"
    [[ "$build" == b* ]] && pkg="$helper-bin"

    # pkgnote deploy still runs with this helper name; its AUR part fails if missing.
    AUR_HELPER="$helper"
    local not_installed="$helper is not installed; AUR packages will fail in pkgnote deploy. Rerun this script to install it."
    try sudo pacman -S --needed "${NC[@]}" base-devel git || { REPORT_FAILED+=("$not_installed"); return; }
    TMPDIR_DEPLOY=$(mktemp -d)
    try git clone --depth 1 "https://aur.archlinux.org/$pkg.git" "$TMPDIR_DEPLOY/$pkg" ||
        { REPORT_FAILED+=("$not_installed"); return; }
    if [[ ! -f "$TMPDIR_DEPLOY/$pkg/PKGBUILD" ]]; then
        warn "no PKGBUILD in the cloned $pkg repo"
        REPORT_FAILED+=("No PKGBUILD in https://aur.archlinux.org/$pkg.git. $not_installed")
        return
    fi
    echo "----- PKGBUILD of $pkg -----"
    cat "$TMPDIR_DEPLOY/$pkg/PKGBUILD"
    echo "----- end of PKGBUILD -----"
    local ok prompt="Build and install $pkg with makepkg -si? [y/n]: "
    if [[ "$CONFIRM_PKGBUILD" == true ]]; then
        ok=$(NOCONFIRM=false ask "$prompt" y "" 'y|n')
    else
        ok=$(ask "$prompt" y "" 'y|n')
    fi
    if [[ "$ok" != y ]]; then
        info "not building $pkg"
        REPORT_FAILED+=("Installing $pkg was declined. $not_installed")
        return
    fi
    # not in a subshell: try's report entry must reach this shell
    pushd "$TMPDIR_DEPLOY/$pkg" > /dev/null
    local mrc=0
    try makepkg -si "${NC[@]}" || mrc=$?
    popd > /dev/null
    [[ $mrc -eq 0 ]] || { REPORT_FAILED+=("$not_installed"); return; }
    if ! command -v "$helper" > /dev/null; then
        warn "$helper is not available after makepkg"
        REPORT_FAILED+=("$not_installed")
    fi
}

# ---------------------------------------------------------------- 4. packages

step_packages() {
    step "4. Packages (pkgnote deploy)"
    local args=(deploy --machine "$MACHINE_NAME" --aur-helper "$AUR_HELPER" "${NC[@]}")
    if [[ "$DRY_RUN" == true ]]; then
        printf '  +'; printf ' %q' pkgnote "${args[@]}" --dry-run; echo
        pkgnote "${args[@]}" --dry-run || warn "pkgnote deploy --dry-run failed"
    else
        try pkgnote "${args[@]}" || true
    fi
}

# ---------------------------------------------------------------- 5. wallpapers

step_wallpapers() {
    step "5. Wallpapers"
    local current="$WALLPAPER_DEFAULT"
    if [[ -f "$WALLPAPER_LOCAL" ]]; then
        # shellcheck source=/dev/null
        current=$(WALLPAPER_REPO="$WALLPAPER_DEFAULT"; source "$WALLPAPER_LOCAL"; echo "$WALLPAPER_REPO")
    fi

    local clone=y path="$current"
    if [[ "$DRY_RUN" == true ]]; then
        info "[dry-run] would ask whether to clone $WALLPAPER_URL and where (current: $(tilde "$current"))"
    else
        clone=$(ask "Clone the wallpapers repo ($WALLPAPER_URL)? [Y/n]: " y y 'y|n')
        local input
        input=$(ask_text "Path (default: $(tilde "$current")): ")
        if [[ -n "$input" ]]; then
            # shellcheck disable=SC2088  # literal "~" typed by the user
            [[ "$input" == "~" || "$input" == "~/"* ]] && input="$HOME${input#"~"}"
            path=$(realpath -m -- "$input")
        fi
    fi

    if [[ "$path" != "$current" ]]; then
        local rel="${path#"$HOME"/}" line
        if [[ "$path" == "$HOME/"* && "$rel" != *[\"\$\`\\]* ]]; then
            line="WALLPAPER_REPO=\"\$HOME/$rel\""
        else
            line="WALLPAPER_REPO=$(printf '%q' "$path")"
        fi
        if [[ "$DRY_RUN" == true ]]; then
            info "[dry-run] would write '$line' to $WALLPAPER_LOCAL"
        else
            mkdir -p "$(dirname "$WALLPAPER_LOCAL")"
            printf '# Location of the wallpapers repo (written by deploy-dotfiles.sh)\n%s\n' "$line" > "$WALLPAPER_LOCAL"
            info "wrote $(tilde "$WALLPAPER_LOCAL")"
        fi
    fi

    [[ "$clone" == y ]] || { info "not cloning wallpapers"; return; }
    if [[ -d "$path/.git" ]]; then
        info "wallpapers already cloned at $(tilde "$path")"
    elif [[ -e "$path" && -n "$(ls -A "$path" 2> /dev/null)" ]]; then
        warn "$path exists and is not a git repo; not cloning"
        REPORT_MANUAL+=("Wallpapers were not cloned: $path exists and is not a git repo")
    else
        try git clone "$WALLPAPER_URL" "$path" || true
    fi
}

# ---------------------------------------------------------------- 6. colors

step_colors() {
    step "6. Initial color scheme"
    if [[ "$DRY_RUN" == true ]]; then
        info "[dry-run] would run: generate-color-scheme.sh (default colors)"
        return
    fi
    local rc=0
    "$SCRIPT_DIR/generate-color-scheme.sh" || rc=$?
    case $rc in
        0) ;;
        2) warn "matugen failed (dynamic.json was written)"
           REPORT_FAILED+=("[$CURRENT_STEP] matugen failed (e.g. its post_hooks outside a graphical session); rerun generate-color-scheme.sh after logging in") ;;
        *) warn "generate-color-scheme.sh failed (exit status $rc)"
           REPORT_FAILED+=("[$CURRENT_STEP] generate-color-scheme.sh failed (exit status $rc); fix it and rerun generate-color-scheme.sh") ;;
    esac
}

# ---------------------------------------------------------------- services

# Print units from "enable <unit>" lines of the given files ("##" files skipped).
read_units() {
    local f kw unit rest
    for f; do
        [[ "$(basename "$f")" == *'##'* ]] && continue
        [[ -f "$f" ]] || continue
        while read -r kw unit rest || [[ -n "$kw" ]]; do
            [[ -z "$kw" || "$kw" == \#* || "$kw" == \;* ]] && continue
            if [[ "$kw" == enable && -n "$unit" && -z "$rest" ]]; then
                echo "$unit"
            else
                warn "$f: ignoring unsupported line: $kw $unit $rest"
            fi
        done < "$f"
    done | awk '!seen[$0]++'
}

# Report units listed last run (state file) but no longer listed, still enabled.
check_dropped() {
    local scope="$1"; shift
    local sc=(systemctl) prefix="sudo systemctl"
    [[ "$scope" == user ]] && sc=(systemctl --user) prefix="systemctl --user"
    [[ -f "$STATE_FILE" ]] || return 0
    local s u
    while read -r s u; do
        [[ "$s" == "$scope" && -n "$u" ]] || continue
        contains "$u" "$@" && continue
        if [[ "$("${sc[@]}" is-enabled "$u" 2> /dev/null || true)" == enabled ]]; then
            REPORT_SERVICES+=("$u ($scope) is no longer listed but still enabled; if unneeded: $prefix disable $u")
        fi
    done < "$STATE_FILE"
}

# Record the units listed this run for <scope>.
save_state() {
    local scope="$1"; shift
    [[ "$DRY_RUN" == true ]] && return
    mkdir -p "$(dirname "$STATE_FILE")"
    local tmp
    tmp=$(mktemp "$STATE_FILE.XXXXXX")
    { [[ -f "$STATE_FILE" ]] && grep -v "^$scope " "$STATE_FILE" || true
      local u; for u; do echo "$scope $u"; done; } > "$tmp"
    mv "$tmp" "$STATE_FILE"
}

# enable_units <system|user> <units...>
enable_units() {
    local scope="$1"; shift
    local sc=(systemctl)
    [[ "$scope" == user ]] && sc=(systemctl --user)
    check_dropped "$scope" "$@"
    save_state "$scope" "$@"
    if [[ $# -eq 0 ]]; then
        info "no $scope units listed"
        return
    fi

    local to_enable=() u state skipped=0
    for u; do
        state=$("${sc[@]}" is-enabled "$u" 2> /dev/null) || true
        case "$state" in
            enabled|enabled-runtime|alias) ;;
            disabled|indirect) to_enable+=("$u") ;;
            ""|not-found)
                warn "$u: unit file not found; skipped"
                skipped=$((skipped + 1))
                REPORT_MISSING_UNITS+=("$u ($scope): unit file not found (package not installed?)") ;;
            *)
                warn "$u is $state; skipped"
                skipped=$((skipped + 1))
                REPORT_SERVICES+=("$u ($scope) is $state; not enabled by this script") ;;
        esac
    done

    if [[ ${#to_enable[@]} -eq 0 ]]; then
        if [[ $skipped -eq 0 ]]; then
            info "all listed $scope units are already enabled"
        else
            info "nothing to enable ($skipped listed $scope unit(s) skipped, see above)"
        fi
        return
    fi
    echo "  The following $scope units will be enabled:"
    printf '    %s\n' "${to_enable[@]}"
    local cmd=(systemctl --user enable "${to_enable[@]}")
    [[ "$scope" == system ]] && cmd=(sudo systemctl enable "${to_enable[@]}")
    if [[ "$DRY_RUN" == true ]]; then
        run "${cmd[@]}"
        return
    fi
    local ok
    ok=$(ask "Proceed? [Y/n]: " y y 'y|n')
    [[ "$ok" == y ]] || { info "skipped"; return; }
    try "${cmd[@]}" || return 0
    if [[ "$scope" == system ]]; then ENABLED_SYSTEM+=("${to_enable[@]}"); else ENABLED_USER+=("${to_enable[@]}"); fi
}

# ---------------------------------------------------------------- 7. /etc files

step_etcfiles() {
    step "7. /etc files (etcfiles)"
    if ! command -v etcfiles > /dev/null; then
        ETCFILES_STATUS=failed
        warn "etcfiles not found; skipping /etc files"
        REPORT_FAILED+=("[$CURRENT_STEP] etcfiles not found (expected ~/.local/bin/etcfiles); /etc files were skipped")
        return
    fi
    if [[ "$DRY_RUN" == true ]]; then
        printf '  + etcfiles -n deploy\n'
        etcfiles -n deploy || warn "etcfiles -n deploy failed"
        return
    fi
    local ans
    while true; do
        ans=$(ask 'Copy config files to /etc using etcfiles? If you want to dry-run, type "d" and you can try again later. [y/n/d]: ' y "" 'y|n|d')
        case "$ans" in
            d) etcfiles -n deploy || warn "etcfiles -n deploy failed" ;;
            y) if try etcfiles deploy; then ETCFILES_STATUS=deployed; else ETCFILES_STATUS=failed; fi
               return ;;
            n) ETCFILES_STATUS=declined; info "skipped /etc files"; return ;;
        esac
    done
}

# ---------------------------------------------------------------- 8, 9. services

# service_step <system|user> <list dir>
service_step() {
    local scope="$1" dir="$2" units files
    shopt -s nullglob
    files=("$dir"/*.list)
    shopt -u nullglob
    mapfile -t units < <(read_units "${files[@]}")
    [[ "$scope" == system ]] && SYSTEM_LISTED=("${units[@]}")
    enable_units "$scope" "${units[@]}"
}

step_system_services() {
    step "8. System services"
    service_step system "$SYSTEM_SERVICES_DIR"
}

step_user_services() {
    step "9. User services"
    service_step user "$USER_SERVICES_DIR"
}

# ---------------------------------------------------------------- 10. report

check_fonts() {
    if ! command -v fc-list > /dev/null; then
        REPORT_FONTS+=("fc-list not found; could not check self-made fonts (${FONT_PATTERNS[*]})")
        return
    fi
    local families pat
    if ! families=$(fc-list : family | tr ',' '\n'); then
        REPORT_FONTS+=("fc-list failed; could not check self-made fonts (${FONT_PATTERNS[*]})")
        return
    fi
    for pat in "${FONT_PATTERNS[@]}"; do
        grep -Eq "$pat" <<< "$families" ||
            REPORT_FONTS+=("No font family matching /$pat/; install it manually (copy its font directory to ~/.local/share/fonts/, then fc-cache)")
    done
}

check_not_active() {
    local u
    for u in "${ENABLED_SYSTEM[@]}"; do
        systemctl is-active --quiet "$u" ||
            REPORT_SERVICES+=("$u (system) was enabled but is not running: sudo systemctl start $u")
    done
    for u in "${ENABLED_USER[@]}"; do
        systemctl --user is-active --quiet "$u" ||
            REPORT_SERVICES+=("$u (user) was enabled but is not running: systemctl --user start $u")
    done
}

manual_reminders() {
    local url
    url=$(yadm remote get-url origin 2> /dev/null || true)
    if [[ "$url" == https://* ]]; then
        REPORT_MANUAL+=("Register this machine's SSH key on GitHub (in the browser), check with 'ssh -T git@github.com', then switch the dotfiles remote to SSH: yadm --yadm-repo ~/.dotfiles remote set-url origin $DOTFILES_SSH_URL")
    fi
    [[ -e "$HOME/.config/git/config.local" ]] ||
        REPORT_MANUAL+=("Create ~/.config/git/config.local with [user] name/email (not tracked; on a work machine also add the includeIf for the work directory)")
    [[ -e "$HOME/.config/git/leakcheck.local" ]] ||
        REPORT_MANUAL+=("If this is a work machine, create ~/.config/git/leakcheck.local")
    REPORT_MANUAL+=("Join the tailnet: sudo tailscale up")
    REPORT_MANUAL+=("Check firmware updates: fwupdmgr refresh && fwupdmgr get-updates")
}

print_section() {
    local title="$1"; shift
    [[ $# -gt 0 ]] || return 0
    printf '\n%s\n' "$title"
    printf '  - %s\n' "$@"
}

# First value of an sshd_config keyword (lowercased), "" if not set, "unknown" if an
# unreadable file comes before a decision. sshd -T needs root, so read the files:
# drop-ins (Included at the top of sshd_config on Arch) first, then sshd_config; the
# first occurrence outside a Match block wins; "Key value" and "Key=value" both work.
sshd_option() {
    local files=() f v=""
    shopt -s nullglob
    files=("$SSHD_CONFIG_DIR"/sshd_config.d/*.conf "$SSHD_CONFIG_DIR/sshd_config")
    shopt -u nullglob
    for f in "${files[@]}"; do
        [[ -r "$f" ]] || { echo unknown; return; }
        v=$(awk -v keys="$*" 'BEGIN { FS = "[ \t]*[ \t=][ \t]*"; n = split(tolower(keys), k, " ") }
            { sub(/^[ \t]+/, ""); sub(/[ \t\r]+$/, "") }
            /^#/ || $0 == "" { next }
            tolower($1) == "match" { exit }
            { for (i = 1; i <= n; i++) if (tolower($1) == k[i]) { print tolower($2); exit } }' "$f")
        [[ -n "$v" ]] && { echo "$v"; return 0; }
    done
    return 0
}

# sshd enabled but password login not (provably) disabled. Conservative: unknown = warn.
check_sshd() {
    if ! contains sshd.service "${ENABLED_SYSTEM[@]}" &&
        [[ "$(systemctl is-enabled sshd.service 2> /dev/null || true)" != enabled ]]; then
        return
    fi
    local pw kbd pam
    pw=$(sshd_option PasswordAuthentication)
    kbd=$(sshd_option KbdInteractiveAuthentication ChallengeResponseAuthentication)
    pam=$(sshd_option UsePAM)
    if [[ "$pw" != no ]]; then
        REPORT_MANUAL+=("sshd is enabled and password login may be allowed: register your SSH public key, confirm key login works, then disable password authentication (e.g. /etc/ssh/sshd_config.d/10-no-password.conf: PasswordAuthentication no)")
    elif [[ "$kbd" != no && ( "$pam" == yes || "$pam" == unknown ) ]]; then
        REPORT_MANUAL+=("sshd: PasswordAuthentication is no, but KbdInteractiveAuthentication with UsePAM yes can still ask for passwords; once key login works, also set KbdInteractiveAuthentication no")
    fi
}

# btrfs machine with snapper but without a config for /.
check_snapper() {
    contains btrfs "${MACHINE_CLASSES[@]}" || return 0
    command -v snapper > /dev/null || return 0
    local cfg="$SNAPPER_CONFIGS_DIR/root" exists
    if [[ -x "$SNAPPER_CONFIGS_DIR" ]]; then
        [[ -e "$cfg" ]] && exists=true || exists=false
    elif [[ "$SUDO_USED" == true ]] && sudo -n true 2> /dev/null; then
        sudo -n test -e "$cfg" 2> /dev/null && exists=true || exists=false
    else
        local list
        list=$(snapper list-configs 2> /dev/null) || return 0  # unknown: no false alarm
        awk '$1 == "root"' <<< "$list" | grep -q . && exists=true || exists=false
    fi
    [[ "$exists" == false ]] &&
        REPORT_MANUAL+=("snapper has no config for /: sudo snapper -c root create-config /")
    return 0
}

# greetd listed but its config (regreet) not deployed by etcfiles in this run.
check_greetd() {
    [[ "$ETCFILES_STATUS" == declined || "$ETCFILES_STATUS" == failed ]] || return 0
    contains greetd.service "${SYSTEM_LISTED[@]}" || return 0
    REPORT_MANUAL+=("/etc files were not deployed (etcfiles $ETCFILES_STATUS): greetd will start with the package default config (not regreet) until you run etcfiles deploy")
}

step_report() {
    check_fonts
    check_not_active
    check_sshd
    check_snapper
    check_greetd
    manual_reminders
    local report
    report=$(
        echo "Things you may want to do ($(date '+%F %T'), machine: $MACHINE_NAME)"
        print_section "Missing fonts:" "${REPORT_FONTS[@]}"
        print_section "Services:" "${REPORT_SERVICES[@]}"
        print_section "Missing unit files:" "${REPORT_MISSING_UNITS[@]}"
        print_section "Failed or incomplete steps:" "${REPORT_FAILED[@]}"
        print_section "Manual steps:" "${REPORT_MANUAL[@]}"
    )
    step "10. Report"
    echo "$report"
    if [[ "$DRY_RUN" == true ]]; then
        printf '\n[dry-run] would save this report to %s\n' "$(tilde "$LOG_FILE")"
    else
        echo "$report" > "$LOG_FILE"
        printf '\nSaved to %s\n' "$(tilde "$LOG_FILE")"
    fi
    # only now: if a check above fails, the EXIT trap still writes the report (with set +e)
    REPORT_DONE=true
}

# ---------------------------------------------------------------- main

echo "Make sure this machine stays powered (plug in the AC adapter) during deployment."
[[ "$DRY_RUN" == true ]] && echo "Dry run: nothing will be changed."
REPORT_ARMED=true
step_python
step_machine
step_aur_helper
step_packages
step_wallpapers
step_colors
step_etcfiles
step_system_services
step_user_services
step_report
