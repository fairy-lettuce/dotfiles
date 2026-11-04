#!/bin/bash
# Tests for git-leakcheck. Everything runs in temp repos with a temp HOME and
# XDG_CONFIG_HOME (fictional patterns; the real leakcheck.local is never read).
#
# Usage: run-tests.sh [<test name substring>]
# shellcheck disable=SC2015  # A && ok || fail asserts
set -euo pipefail

LEAKCHECK="$HOME/.local/bin/git-leakcheck"
FILTER="${1:-}"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/leakcheck-tests.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
FAILED=()
CURRENT=""

ok()   { PASS=$((PASS + 1)); }
fail() { FAIL=$((FAIL + 1)); FAILED+=("$CURRENT: $*"); echo "    FAIL: $*"; }
assert_eq()       { [[ "$1" == "$2" ]] && ok || fail "${3:-} expected '$2', got '$1'"; }
assert_contains() { grep -qE -- "$2" "$1" && ok || fail "'$1' should match /$2/"; }
assert_not()      { grep -qE -- "$2" "$1" && fail "'$1' should not match /$2/" || ok; }

ZERO=0000000000000000000000000000000000000000

setup() {
    T=$(mktemp -d "$WORK/t.XXXXXX")
    export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config"
    export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$XDG_CONFIG_HOME/git/config"
    export GIT_AUTHOR_NAME="Pat Example" GIT_AUTHOR_EMAIL="pat@personal.example"
    export GIT_COMMITTER_NAME="Pat Example" GIT_COMMITTER_EMAIL="pat@personal.example"
    # A UTF-8 locale, as in a normal terminal (the script itself switches to C)
    unset LC_ALL LC_CTYPE
    export LANG=C.UTF-8
    mkdir -p "$XDG_CONFIG_HOME/git" "$HOME/work"
    : > "$GIT_CONFIG_GLOBAL"
    git config --global init.defaultBranch main
    cat > "$XDG_CONFIG_HOME/git/leakcheck.local" <<'EOP'
# fictional patterns
dir ~/work
email dev@acme.example
remote github.com/acme-corp/
word acme
word 株式会社アクメ
EOP
    REPO="$HOME/proj"
    git init -q "$REPO"
    git init -q --bare "$T/remote.git"
}

commit_file() {  # commit_file <path> <content (printf %b)> [message]
    mkdir -p "$(dirname "$REPO/$1")"
    printf '%b' "$2" > "$REPO/$1"
    git -C "$REPO" add -- "$1"
    git -C "$REPO" commit -q -m "${3:-add $1}"
}

push_check() {  # run the pre-push check for HEAD against the empty bare remote
    local url="${1:-$T/remote.git}"
    RC=0
    (cd "$REPO" && printf 'refs/heads/main %s refs/heads/main %s\n' "$(git rev-parse HEAD)" "$ZERO" |
        "$LEAKCHECK" pre-push origin "$url") > "$T/out" 2>&1 || RC=$?
}

# ---------------------------------------------------------------- word matching

test_whole_word_no_false_positives() {
    commit_file notes.txt 'trailing whitespace\nfailing test\nacmeinc and xacme\nacmeApi\n'
    git -C "$REPO" commit -q --allow-empty -m 'fix trailing/failing tests'
    push_check
    assert_eq "$RC" 0 "exit code"
    assert_not "$T/out" 'refusing'
}

test_whole_word_matches() {
    commit_file a.txt 'acme\nuse acme-api here\nsee (acme)\nmade by ACME\nnothing\n'
    push_check
    assert_eq "$RC" 1 "exit code"
    assert_contains "$T/out" "refusing to push to non-work remote 'origin'"
    local n
    for n in 1 2 3 4; do assert_contains "$T/out" "added line +a\.txt:$n  \[acme\]"; done
    assert_not "$T/out" 'a\.txt:5'
    assert_contains "$T/out" 'a\.txt:4  \[acme\]  "made by ACME"'
}

patterns() {  # replace the pattern file with the given lines
    printf '%s\n' "$@" > "$XDG_CONFIG_HOME/git/leakcheck.local"
}

test_boundary_only_at_word_edges() {
    patterns 'word github.com/acme-inc/' 'word @acme.example' 'word アクメ'
    commit_file e.txt 'see https://github.com/acme-inc/tools\nmail someone@acme.example\nアクメ2024年\n第3アクメ\nplain\n'
    push_check
    assert_eq "$RC" 1
    assert_contains "$T/out" 'e\.txt:1  \[github\.com/acme-inc/\]'
    assert_contains "$T/out" 'e\.txt:2  \[@acme\.example\]'
    assert_contains "$T/out" 'e\.txt:3  \[アクメ\]'
    assert_contains "$T/out" 'e\.txt:4  \[アクメ\]'
    assert_not "$T/out" 'e\.txt:5'
}

test_underscore_and_digit_are_boundaries() {
    commit_file u.txt 'acme_prod\nACME_TOKEN=1\nmy_acme\nacme2024\n2024acme\nacmeApi\n'
    push_check
    assert_eq "$RC" 1
    local n
    for n in 1 2 3 4 5; do assert_contains "$T/out" "u\.txt:$n  \[acme\]"; done
    assert_not "$T/out" 'u\.txt:6'
}

test_short_word_not_in_longer_word() {
    patterns 'word ail'
    commit_file r.txt 'trailing whitespace\nfailing\n'
    push_check
    assert_eq "$RC" 0 "no match inside words"
    commit_file r.txt 'trailing\nmail ail here\n'
    push_check
    assert_eq "$RC" 1 "whole word"
    assert_contains "$T/out" 'r\.txt:2  \[ail\]'
}

test_path_with_space() {
    commit_file 'my dir/my file.txt' 'ok\nacme here\n'
    push_check
    assert_eq "$RC" 1
    assert_contains "$T/out" 'added line +my dir/my file\.txt:2  \[acme\]  "acme here"$'
    assert_not "$T/out" $'\t'
}

test_japanese_pattern() {
    commit_file ja.md '# 資料\nこれは株式会社アクメの資料です\n'
    push_check
    assert_eq "$RC" 1
    assert_contains "$T/out" 'ja\.md:2  \[株式会社アクメ\]  "これは株式会社アクメの資料です"'
}

test_invalid_utf8_no_warning() {
    commit_file bin.txt 'bad \xff\xfe bytes then acme\n\xc3\x28 end\n'
    push_check
    assert_eq "$RC" 1
    assert_not "$T/out" 'warning|Invalid multibyte'
    assert_contains "$T/out" 'bin\.txt:1  \[acme\]'
}

test_location_line_numbers_and_modified_file() {
    commit_file src/b.txt 'one\ntwo\nthree\nfour\n'
    git -C "$REPO" push -q "$T/remote.git" main
    commit_file src/b.txt 'one\ntwo\nacme here\nthree\nfour\n' 'edit b'
    push_check
    assert_eq "$RC" 1
    assert_contains "$T/out" 'added line +src/b\.txt:3  \[acme\]  "acme here"'
    # the already-pushed commit is not reported again
    assert_eq "$(grep -c 'added line' "$T/out")" 1 "one finding"
}

test_message_filename_ident_and_tag() {
    commit_file docs/acme.md 'hello\n' 'Add notes for Acme'
    git -C "$REPO" tag -a v1 -m 'release for acme'
    RC=0
    (cd "$REPO" && printf 'refs/tags/v1 %s refs/tags/v1 %s\n' "$(git rev-parse v1)" "$ZERO" |
        "$LEAKCHECK" pre-push origin "$T/remote.git") > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 1
    assert_contains "$T/out" 'file name +docs/acme\.md  \[acme\]'
    assert_contains "$T/out" 'message +line 1  \[acme\]  "Add notes for Acme"'
    assert_contains "$T/out" 'tag v1 +message +line 1  \[acme\]  "release for acme"'
    # ident with a work email
    GIT_AUTHOR_EMAIL=dev@acme.example git -C "$REPO" commit -q --allow-empty --no-verify -m x
    push_check
    assert_contains "$T/out" 'author email +-  \[dev@acme\.example\]'
}

test_merge_resolution_line() {
    commit_file m.txt 'a\nb\nc\n'
    git -C "$REPO" push -q "$T/remote.git" main
    git -C "$REPO" checkout -q -b side
    commit_file m.txt 'a\nside\nc\n' side
    git -C "$REPO" checkout -q main
    commit_file m.txt 'a\nmain\nc\n' main
    git -C "$REPO" merge -q side > /dev/null 2>&1 || true
    printf 'a\nmerged by acme\nc\n' > "$REPO/m.txt"   # evil merge: new line only in the merge
    git -C "$REPO" add m.txt
    git -C "$REPO" commit -q --no-edit
    push_check
    assert_eq "$RC" 1
    assert_contains "$T/out" 'added line +m\.txt:2  \[acme\]  "merged by acme"'
}

test_binary_file_reported_with_path() {
    commit_file data/blob.bin 'abc\0def\0\n'
    commit_file img/pic.png 'PNG\0\0\n'
    push_check
    assert_eq "$RC" 1
    assert_contains "$T/out" 'binary file +data/blob\.bin$'
    assert_not "$T/out" 'pic\.png'
}

test_report_cap() {
    local body="" i
    for ((i = 1; i <= 60; i++)); do body+="acme $i\n"; done
    commit_file many.txt "$body"
    push_check
    assert_eq "$RC" 1
    assert_contains "$T/out" '^  \.\.\. 20 more$'
    assert_eq "$(grep -c 'added line' "$T/out")" 40 "capped lines"
}

test_report_cap_keeps_binary() {
    local body="" i
    for ((i = 1; i <= 60; i++)); do body+="acme $i\n"; done
    commit_file many.txt "$body"
    commit_file data/blob.bin 'abc\0def\0\n'
    push_check
    assert_eq "$RC" 1
    assert_contains "$T/out" 'binary file +data/blob\.bin$'
    assert_contains "$T/out" '^  \.\.\. 21 more$'
}

# fail_cmd <command> <arg substring>: shim <command> in PATH so that it fails
# when one of its arguments contains the substring.
fail_cmd() {
    local real
    real="$(command -v "$1")"
    mkdir -p "$T/shim"
    cat > "$T/shim/$1" <<EOS
#!/bin/bash
for a in "\$@"; do [[ "\$a" == *'$2'* ]] && { echo "shim: $1 failed" >&2; exit 1; }; done
exec '$real' "\$@"
EOS
    chmod +x "$T/shim/$1"
}

test_fail_closed() {
    commit_file clean.txt 'nothing here\n'
    local spec
    for spec in 'git --cc' 'git --numstat' 'git rev-list' 'awk isword'; do
        rm -rf "$T/shim"
        fail_cmd ${spec}
        PATH="$T/shim:$PATH" push_check
        assert_eq "$RC" 1 "$spec"
        assert_contains "$T/out" 'refusing to push'
    done
    rm -rf "$T/shim"
    push_check
    assert_eq "$RC" 0 "no shim"
}

test_blob_fail_closed() {
    local blob
    blob="$(printf 'nothing here\n' | git -C "$REPO" hash-object -w --stdin)"
    fail_cmd git blob   # git cat-file blob <oid> while dumping it
    RC=0
    (cd "$REPO" && printf 'refs/tags/b %s refs/tags/b %s\n' "$blob" "$ZERO" |
        PATH="$T/shim:$PATH" "$LEAKCHECK" pre-push origin "$T/remote.git") > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 1
    assert_contains "$T/out" 'refusing to push'
}

push_ref() {  # push_ref <remote ref> <local oid> [<remote oid>]: one pre-push line
    RC=0
    (cd "$REPO" && printf 'x %s %s %s\n' "$2" "$1" "${3:-$ZERO}" |
        "$LEAKCHECK" pre-push origin "$T/remote.git") > "$T/out" 2>&1 || RC=$?
}

test_legitimate_pushes_pass() {
    commit_file clean.txt 'nothing here\n'
    local head tree gtree
    head="$(git -C "$REPO" rev-parse HEAD)"
    tree="$(git -C "$REPO" rev-parse 'HEAD^{tree}')"
    git -C "$REPO" push -q "$T/remote.git" main
    push_ref refs/heads/acme/old "$ZERO" "$head"
    assert_eq "$RC" 0 "branch deletion"
    push_ref refs/heads/feature "$head"
    assert_eq "$RC" 0 "new branch at an existing commit"
    git -C "$REPO" tag v1
    push_ref refs/tags/v1 "$head"
    assert_eq "$RC" 0 "lightweight tag"
    git -C "$REPO" tag -a v2 -m 'release 2'
    push_ref refs/tags/v2 "$(git -C "$REPO" rev-parse v2)"
    assert_eq "$RC" 0 "annotated tag"
    push_ref refs/tags/t "$tree"
    assert_eq "$RC" 0 "tag at a tree"
    gtree="$(printf '160000 commit %s\tsub\n100644 blob %s\tclean.txt\n' \
        1111111111111111111111111111111111111111 "$(git -C "$REPO" rev-parse HEAD:clean.txt)" |
        git -C "$REPO" mktree)"
    push_ref refs/tags/g "$gtree"
    assert_eq "$RC" 0 "tag at a tree with a gitlink"
    git -C "$REPO" tag -a g2 -m 'tree with submodule' "$gtree"
    push_ref refs/tags/g2 "$(git -C "$REPO" rev-parse g2)"
    assert_eq "$RC" 0 "annotated tag at a tree with a gitlink"
}

test_ref_names() {
    commit_file clean.txt 'nothing here\n'
    local head
    head="$(git -C "$REPO" rev-parse HEAD)"
    push_ref refs/heads/acme/feature "$head"
    assert_eq "$RC" 1 "branch name"
    assert_contains "$T/out" 'ref name +ref refs/heads/acme/feature  \[acme\]$'
    git -C "$REPO" tag acme-v1
    push_ref refs/tags/acme-v1 "$head"
    assert_eq "$RC" 1 "lightweight tag name"
    assert_contains "$T/out" 'ref refs/tags/acme-v1  \[acme\]'
    git -C "$REPO" tag -a acme-v2 -m 'release 2'
    push_ref refs/tags/acme-v2 "$(git -C "$REPO" rev-parse acme-v2)"
    assert_eq "$RC" 1 "annotated tag name"
    assert_contains "$T/out" 'ref refs/tags/acme-v2  \[acme\]'
    push_ref refs/heads/acmeinc-feature "$head"
    assert_eq "$RC" 0 "non-matching branch name"
    git -C "$REPO" tag -a v3 -m 'release 3'
    push_ref refs/tags/v3 "$(git -C "$REPO" rev-parse v3)"
    assert_eq "$RC" 0 "non-matching tag name"
}

test_work_remote_is_skipped() {
    commit_file a.txt 'acme\n'
    push_check "git@github.com:acme-corp/tools.git"
    assert_eq "$RC" 0
}

# ---------------------------------------------------------------- pre-commit

precommit() {  # precommit <repo>
    RC=0
    (cd "$1" && "$LEAKCHECK" pre-commit) > "$T/out" 2>&1 || RC=$?
}

test_pre_commit() {
    precommit "$REPO"
    assert_eq "$RC" 0 "personal ident outside work dir"
    GIT_AUTHOR_EMAIL=dev@acme.example precommit "$REPO"
    assert_eq "$RC" 1 "work email outside work dir"
    assert_contains "$T/out" 'author email <dev@acme\.example> is a work email'
    GIT_AUTHOR_NAME="Acme Bot" precommit "$REPO"
    assert_eq "$RC" 1 "word in name"
    assert_contains "$T/out" "contains 'acme'"
    GIT_AUTHOR_NAME="Trailing Failure" precommit "$REPO"
    assert_eq "$RC" 0 "no substring false positive"
    GIT_AUTHOR_NAME="山田 株式会社アクメ" precommit "$REPO"
    assert_eq "$RC" 1 "Japanese word in name"
    local n
    for n in ACME_TOKEN my_acme "Bot acme_prod" acme2024 2024acme; do
        GIT_AUTHOR_NAME="$n" precommit "$REPO"
        assert_eq "$RC" 1 "underscore/digit boundary: $n"
    done
    for n in acmeApi xacme; do
        GIT_AUTHOR_NAME="$n" precommit "$REPO"
        assert_eq "$RC" 0 "letter: $n"
    done
    git init -q "$HOME/work/job"
    precommit "$HOME/work/job"
    assert_eq "$RC" 1 "personal email inside work dir"
    assert_contains "$T/out" 'is not a work email'
}

test_pre_commit_word_edges() {
    patterns 'word github.com/acme-inc/' 'word @acme.example' 'word アクメ' 'word ail'
    local n
    for n in "Bot https://github.com/acme-inc/tools" "第3アクメ" "アクメ2024年"; do
        GIT_AUTHOR_NAME="$n" precommit "$REPO"
        assert_eq "$RC" 1 "edge: $n"
    done
    GIT_AUTHOR_EMAIL=someone@acme.example precommit "$REPO"
    assert_eq "$RC" 1 "email domain"
    assert_contains "$T/out" "contains '@acme\.example'"
    GIT_AUTHOR_NAME="Trailing Failure" precommit "$REPO"
    assert_eq "$RC" 0 "ail in trailing"
    GIT_AUTHOR_NAME="Ail Example" precommit "$REPO"
    assert_eq "$RC" 1 "ail whole word"
}

# ---------------------------------------------------------------- through git's hook config

test_real_git_hooks() {
    git config --global hook.leakcheck-commit.command "$LEAKCHECK pre-commit"
    git config --global hook.leakcheck-commit.event pre-commit
    git config --global hook.leakcheck-push.command "$LEAKCHECK pre-push"
    git config --global hook.leakcheck-push.event pre-push
    git -C "$REPO" remote add origin "$T/remote.git"
    printf 'failing test\n' > "$REPO/ok.txt"
    git -C "$REPO" add ok.txt
    RC=0
    git -C "$REPO" commit -q -m 'trailing fix' > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 0 "commit allowed"
    git -C "$REPO" push -q origin main > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 0 "push allowed"
    printf 'acme\n' > "$REPO/bad.txt"
    git -C "$REPO" add bad.txt
    git -C "$REPO" commit -q -m bad
    RC=0
    git -C "$REPO" push -q origin main > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 1 "push blocked"
    assert_contains "$T/out" 'added line +bad\.txt:1  \[acme\]'
    RC=0
    GIT_AUTHOR_EMAIL=dev@acme.example git -C "$REPO" commit -q --allow-empty -m x > "$T/out" 2>&1 || RC=$?
    assert_eq "$RC" 1 "commit blocked"
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
        echo "    --- output ---"; sed 's/^/    | /' "$T/out" 2> /dev/null | tail -30
    fi
done

echo
echo "$PASS passed, $FAIL failed"
for f in "${FAILED[@]}"; do echo "  $f"; done
[[ $FAIL -eq 0 ]]
