"""``pkgnote fetch`` — 実システムの状態を packages.kdl に取り込む。

pacman hook(``/etc/pacman.d/hooks/pkgnote-fetch.hook``。SPEC「hook」参照)/ flatpak ラッパーから自動呼び出しされる
想定(手動実行も可)。対象は常に現在のマシン(``--machine`` は現在のマシン名と一致する場合のみ可)。
入力は「``pacman -Qqen`` / ``-Qqem`` / ``flatpak list --app`` の明示インストール集合」と、前回 fetch 時に観測した
集合(``~/.local/state/pkgnote/installed_<machine>.txt``、マシンローカル)。前回との差分で
「このマシンで今インストールした / アンインストールした」を判定する。差分を取るのは、
手で条件を書き換えた直後(まだ deploy・削除していない)のパッケージを、fetch が勝手に
「実機に合わせて」書き戻さないため。

反映ルール(ノードは決して削除しない):

- packages.kdl に未登録のパッケージが入っている
  → ``uncategorized`` に ``install-if="<machine>"`` + ``first-installed-on="<machine>"`` で追加。
- 新たにインストールされたが、条件上はこのマシンに入らない
  - package 自身の ``skip-if`` が真 → その OR 項からマシン名を取り除く(それでも真なら
    ``(<元の式>) & !<machine>`` に書き換える)。空になれば ``skip-if`` ごと消す。
  - package 自身の ``install-if`` が偽 → `` | <machine>`` を追記。
  - **カテゴリ側の条件**(祖先の ``install-if`` が偽、または ``skip-if`` が真)で除外されている
    → package 側の条件ではこれを覆せない(install は AND、skip は OR で合成されるため)。
    何も書かずに警告だけ出す。``pkgnote status`` でも EXTRA として理由付きで出続ける。
- アンインストールされたが、条件上はこのマシンに入る
  → package 自身の ``skip-if`` に `` | <machine>`` を追記(無ければ作る)。
- 記録と違う backend で入っている(AUR → 公式リポジトリへの移動など)→ ``from`` を実際の値に直す。

前回の観測集合が無い(または空の)初回は、未登録パッケージの追加だけを行い、観測集合を記録する。
空の観測集合は保存しない(空ファイルで初回保護が外れないように)。

安全策:
- データ(packages.kdl / machines.toml)が不整合なら何も書かずに失敗する。
- インストール済み一覧の問い合わせが 1 つでも失敗したら、何も書かずに(観測集合も更新せずに)失敗する。
- アンインストール記録が一度に ``MASS_REMOVAL_LIMIT`` 件を超えるなら、問い合わせ異常の疑いが
  あるので書かずに止める(``--allow-mass-removal`` で続行)。
- 書き込みは原子的置換で、読み込み後にファイルが変わっていたら上書きしない。
"""

from __future__ import annotations

import sys

from .. import backends, paths, term
from ..expr import And, Name, Not, Or, or_terms, to_str
from ..kdl import KNode, write_text_atomic
from ..model import FIRST_INSTALLED_ON, INSTALL_IF, SKIP_IF, UNCATEGORIZED, Package
from ..resolve import decide
from . import Context

# 一度にアンインストールとして記録してよい件数の上限(これを超えたら問い合わせ異常を疑う)。
MASS_REMOVAL_LIMIT = 5


def load_seen(machine: str) -> set[str] | None:
    """前回の観測集合。ファイルが無い・空なら None(= 初回扱い)。"""
    p = paths.seen_file(machine)
    if not p.exists():
        return None
    names = {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}
    return names or None


def save_seen(machine: str, names: set[str]) -> None:
    if not names:
        return  # 空集合は保存しない(次回の初回保護を外さないため)
    p = paths.seen_file(machine)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(p, "".join(f"{n}\n" for n in sorted(names)))


def run(
    machine: str | None = None, dry_run: bool = False, allow_mass_removal: bool = False
) -> int:
    ctx = Context.load(machine, require_current=True)
    m = ctx.machine
    # 問い合わせ失敗は BackendError で即中止(ここまでに何も書いていない)
    installed_by = backends.installed_by_backend()
    installed: set[str] = set().union(*installed_by.values())
    seen = load_seen(m)
    known = {p.name: p for p in ctx.packages.packages()}

    changes: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    # --- 未登録パッケージの追加 ------------------------------------------------
    for backend, names in installed_by.items():
        for name in sorted(names):
            if name in known:
                continue
            _add_uncategorized(ctx, name, backend)
            changes.append(f"{UNCATEGORIZED}/{term.cyan(name)} を追加 "
                           f"({term.dim('from=')}{backend} {term.dim('install-if=')}{m})")

    # --- backend の付け替え(AUR → 公式 など)---------------------------------
    for pkg in known.values():
        if pkg.name in installed_by.get(pkg.source, set()):
            continue
        actual = [b for b, names in installed_by.items() if pkg.name in names]
        if len(actual) == 1:
            pkg.node.props["from"] = actual[0]
            changes.append(f"{term.cyan(pkg.label)}: {term.dim('from')}: "
                           f"\"{pkg.source}\" → \"{actual[0]}\"(実際の導入元に合わせた)")

    # --- 既知パッケージの条件更新 ----------------------------------------------
    removals = 0
    not_installed: list = []
    for pkg in known.values():
        d = decide(pkg, ctx.names)
        is_inst = pkg.name in installed
        if is_inst and not d.install:
            if seen is not None and pkg.name not in seen:
                msg = _record_installed(pkg, d, m, ctx.names)
                (changes if msg[0] else warnings).append(msg[1])
            else:
                notes.append(f"{pkg.label}: 条件上は入らないが導入されている(EXTRA)")
        elif not is_inst and d.install:
            if seen is not None and pkg.name in seen:
                changes.append(_record_removed(pkg, m))
                removals += 1
            else:
                not_installed.append(pkg)

    # 記録しない「未導入」のずれは status / deploy と同じ分類で知らせる(書き込みには使わない)
    by_backend: dict[str, list] = {}
    for pkg in not_installed:
        by_backend.setdefault(pkg.source, []).append(pkg)
    for backend, pkgs in by_backend.items():
        sat = None
        if backend in backends.PROVIDES_BACKENDS:
            try:
                sat = backends.classify({p.name for p in pkgs}, installed)
            except backends.BackendError as exc:  # 表示のための分類なので fetch は止めない
                warnings.append(f"provides / 依存の判定に失敗しました: {exc}")
        for pkg in pkgs:
            if sat is not None and pkg.name in sat.provided:
                notes.append(f"{pkg.label}: {sat.provided[pkg.name]} で導入済み(provides + conflicts/replaces)")
            elif sat is not None and pkg.name in sat.as_dependency:
                notes.append(f"{pkg.label}: 依存として導入済み"
                             f"(明示にするなら `{backends.asexplicit_hint([pkg.name])}`)")
            else:
                notes.append(f"{pkg.label}: 条件上は入るが未導入(MISSING)")

    _report(changes, warnings, notes, dry_run)
    if removals > MASS_REMOVAL_LIMIT and not allow_mass_removal:
        print(
            term.red("error") + f": アンインストールの記録が {removals} 件あります"
            f"(上限 {MASS_REMOVAL_LIMIT} 件)。インストール済み一覧の取得異常の可能性があるため、"
            "packages.kdl にも観測集合にも何も書かずに中止しました。\n"
            "  本当に一度に削除したのなら `pkgnote fetch --allow-mass-removal` で取り込んでください。",
            file=sys.stderr,
        )
        return 1
    if dry_run:
        return 0
    if changes:
        ctx.packages.save()
    save_seen(m, installed)
    return 0


def _add_uncategorized(ctx: Context, name: str, backend: str) -> None:
    parent = ctx.packages.find_category((UNCATEGORIZED,), create=True)
    parent.children.append(
        KNode(
            name="package",
            args=[name],
            props={"from": backend, INSTALL_IF: ctx.machine, FIRST_INSTALLED_ON: ctx.machine},
        )
    )


def _record_installed(pkg: Package, d, machine: str, names: set[str]) -> tuple[bool, str]:
    """導入されたが条件が偽 → package 自身の条件を直す。(成功?, メッセージ)"""
    label = term.cyan(pkg.label)
    if d.category_skip or not d.category_install:
        blockers = [
            c.where for c in pkg.category_conds
            if (c.skip is not None and c.skip.eval(names))
            or (c.install is not None and not c.install.eval(names))
        ]
        return False, (
            f"{label}: {machine} に導入されたが、カテゴリ側の条件で除外されているため"
            "自動では記録できません。package を別カテゴリへ移すか、カテゴリの条件を"
            f"見直してください(関係するカテゴリ: {', '.join(_short(w) for w in blockers) or '-'})"
        )
    props = pkg.node.props
    parts: list[str] = []
    if d.own_skip:
        old = str(props[SKIP_IF])
        rest = [t for t in or_terms(pkg.own.skip) if t != Name(machine)]
        if not rest:
            del props[SKIP_IF]
            parts.append(f"{term.dim('skip-if')} から {machine} を除去(空になったので削除)")
        else:
            rest_e = rest[0] if len(rest) == 1 else Or(tuple(rest))
            if rest_e.eval(names):
                new = to_str(And((rest_e, Not(Name(machine)))))
            else:
                new = to_str(rest_e)
            props[SKIP_IF] = new
            parts.append(f"{term.dim('skip-if')}: \"{old}\" → \"{new}\"")
    if not d.own_install:
        old = str(props[INSTALL_IF])
        props[INSTALL_IF] = f"{old} | {machine}"
        parts.append(f"{term.dim('install-if')}: \"{old}\" → \"{props[INSTALL_IF]}\"")
    return True, f"{label}: " + "、".join(parts)


def _record_removed(pkg: Package, machine: str) -> str:
    props = pkg.node.props
    old = props.get(SKIP_IF)
    props[SKIP_IF] = f"{old} | {machine}" if old else machine
    shown = f"\"{old}\" → \"{props[SKIP_IF]}\"" if old else f"\"{props[SKIP_IF]}\" を追加"
    return f"{term.cyan(pkg.label)}: アンインストールを記録 {term.dim('skip-if')}: {shown}"


def _short(where: str) -> str:
    return where.split(": ", 1)[-1]


def _report(changes, warnings, notes, dry_run) -> None:
    tag = "[dry-run] " if dry_run else ""
    if changes:
        print(f"{tag}packages.kdl の更新 {len(changes)} 件:")
        for c in changes:
            print("  " + term.green("+") + f" {c}")
    for w in warnings:
        print(term.yellow("[warn]") + f" {w}", file=sys.stderr)
    if notes:
        print(f"未記録のずれ {len(notes)} 件(`pkgnote status` で確認、deploy か条件の見直しを):")
        for n in notes[:10]:
            print("  " + term.yellow("!") + f" {n}")
        if len(notes) > 10:
            print(f"  … ほか {len(notes) - 10} 件")
    if not (changes or warnings or notes):
        print("変更なし。packages.kdl と実機は同期しています。")
