"""実システム側との接点(インストール済み一覧の取得・導入)。

インストール済み(明示)の判定はシステムに直接問い合わせる(root 不要・読み取り専用):

- pacman(公式リポジトリ): ``pacman -Qqen``
- foreign(AUR 等): ``pacman -Qqem``
- flatpak: ``flatpak list --app``

依存で入ったパッケージは ``-e`` で除外される。問い合わせの **失敗** は空集合と区別して
:class:`BackendError` にする(失敗を「全部アンインストールされた」と誤認して fetch が
大量の ``skip-if`` を書かないため)。flatpak コマンド自体が無い場合だけは「flatpak の
アプリは 0 個」として空集合を返す。

常に「このシステム」の状態を表す(``--machine`` で別マシンを指定しても同じ)。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from .errors import PkgnoteError


class BackendError(PkgnoteError):
    """インストール済み一覧の問い合わせに失敗した。"""


def _query(cmd: list[str]) -> set[str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise BackendError(f"`{' '.join(cmd)}` を実行できません: {exc}") from exc
    # pacman -Q は該当 0 件のとき出力なしで exit 1 を返す(エラーではない)
    if res.returncode == 1 and not res.stdout.strip() and not res.stderr.strip():
        return set()
    if res.returncode != 0:
        detail = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else f"exit {res.returncode}"
        raise BackendError(f"`{' '.join(cmd)}` が失敗しました: {detail}")
    return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}


def installed_pacman() -> set[str]:
    names = _query(["pacman", "-Qqen"])
    if not names:
        # 公式リポジトリの明示パッケージが 0 個(base すら無い)は現実的にありえないので失敗扱い
        raise BackendError("`pacman -Qqen` の結果が空です(問い合わせ失敗とみなします)")
    return names


def installed_foreign() -> set[str]:
    return _query(["pacman", "-Qqem"])


def installed_flatpak() -> set[str]:
    if shutil.which("flatpak") is None:
        return set()
    return _query(["flatpak", "list", "--app", "--columns=application"])


# 他のパッケージが provides で満たしうる backend(flatpak には provides が無い)
PROVIDES_BACKENDS = ("pacman", "foreign")

_C_ENV = {**os.environ, "LC_ALL": "C"}


def _run_pacman(args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["pacman", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, env=_C_ENV)
    except OSError as exc:
        raise BackendError(f"`pacman {args[0]}` を実行できません: {exc}") from exc


def _fail(what: str, res) -> BackendError:
    detail = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else f"exit {res.returncode}"
    return BackendError(f"`pacman {what}` が失敗しました: {detail}")


def unsatisfied(names) -> set[str]:
    """``pacman -T``: インストール済みのどのパッケージにも満たされない名前だけを返す。

    名前そのものが(明示・依存のどちらでも)入っているか、何かが provides していれば満たされる。
    全部満たされていれば exit 0、満たされないものがあれば exit 127 でそれらを 1 行ずつ出す。
    それ以外は :class:`BackendError`。
    """
    names = sorted(set(names))
    if not names:
        return set()
    res = _run_pacman(["-T", "--", *names])
    if res.returncode == 0:
        return set()
    if res.returncode == 127:
        return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}
    raise _fail("-T", res)


def installed_any(names) -> set[str]:
    """``pacman -Qq -- <names>``: その名前のパッケージとして(理由を問わず)入っているもの。

    見つからない名前があると exit 1 で stderr に ``error: package 'x' was not found`` を出すが、
    見つかった分は stdout に出る。それ以外の失敗は :class:`BackendError`。
    pacman 7.1 は名前のパッケージが無いと provides しているものを出す(``-Qq -- sh`` → ``bash``)
    ので、問い合わせた名前そのものだけを返す。
    """
    asked = set(names)
    names = sorted(asked)
    if not names:
        return set()
    res = _run_pacman(["-Qq", "--", *names])
    found = {ln.strip() for ln in res.stdout.splitlines() if ln.strip()} & asked
    if res.returncode == 0:
        return found
    errs = [ln for ln in res.stderr.splitlines() if ln.strip()]
    if res.returncode == 1 and all("was not found" in ln for ln in errs):
        return found
    raise _fail("-Qq", res)


@dataclass(frozen=True)
class PkgInfo:
    """``pacman -Qi`` の 1 パッケージ分(provides / conflicts / replaces はバージョンを除いた名前)。"""

    name: str
    provides: frozenset[str] = frozenset()
    conflicts: frozenset[str] = frozenset()
    replaces: frozenset[str] = frozenset()


def _dep_name(item: str) -> str:
    """``dotnet-sdk=9.0`` / ``foo>=1`` / ``libx.so=1-64`` → 名前部分。"""
    return re.split(r"[<>=]", item, maxsplit=1)[0].strip()


def parse_qi(text: str) -> list[PkgInfo]:
    """``LC_ALL=C pacman -Qi`` の出力を解析する(継続行にも対応)。"""
    out: list[PkgInfo] = []
    for block in re.split(r"\n\s*\n", text):
        fields: dict[str, str] = {}
        key = None
        for line in block.splitlines():
            m = re.match(r"^(\S[^:]*?)\s*:\s?(.*)$", line)
            if m and not line[:1].isspace():
                key = m.group(1).strip()
                fields[key] = m.group(2).strip()
            elif key is not None and line.strip():
                fields[key] += "  " + line.strip()
        if "Name" not in fields:
            continue

        def names_of(field: str) -> frozenset[str]:
            v = fields.get(field, "").strip()
            if not v or v == "None":
                return frozenset()
            return frozenset(_dep_name(x) for x in v.split() if x)

        out.append(PkgInfo(
            name=fields["Name"],
            provides=names_of("Provides"),
            conflicts=names_of("Conflicts With"),
            replaces=names_of("Replaces"),
        ))
    return out


def installed_info() -> list[PkgInfo]:
    """インストール済み全パッケージの provides / conflicts / replaces(``pacman -Qi``)。"""
    res = _run_pacman(["-Qi"])
    if res.returncode != 0:
        raise _fail("-Qi", res)
    return parse_qi(res.stdout)


@dataclass
class Satisfaction:
    """入るべきなのに(明示インストールとしては)入っていない名前の分類。"""

    missing: set[str] = field(default_factory=set)          # 導入が必要
    as_dependency: set[str] = field(default_factory=set)    # その名前で依存として導入済み
    provided: dict[str, str] = field(default_factory=dict)  # 名前 → 代わりに入っているパッケージ


def classify(names, explicit: set[str]) -> Satisfaction:
    """未導入の名前を「導入が必要 / 依存として導入済み / 代替パッケージで導入済み」に分ける。

    代替パッケージとみなすのは、インストール済みのパッケージがその名前を provides し、
    かつ conflicts または replaces しているときだけ(``paru-bin`` は ``paru`` を provides +
    conflicts する)。provides だけ(``dotnet-sdk-9.0-bin`` の ``dotnet-sdk=9.0`` など)は
    共存する別物なので満たされていない扱い。``explicit`` は全 backend の明示インストール集合。
    """
    out = Satisfaction()
    cand = set(names) - explicit
    if not cand:
        return out
    unsat = unsatisfied(cand)
    out.missing |= unsat
    rest = cand - unsat
    if not rest:
        return out
    out.as_dependency = installed_any(rest) & rest
    rest -= out.as_dependency
    if not rest:
        return out
    infos = installed_info()
    for name in sorted(rest):
        provider = next(
            (i.name for i in infos
             if name in i.provides and (name in i.conflicts or name in i.replaces)),
            None,
        )
        if provider:
            out.provided[name] = provider
        else:
            out.missing.add(name)
    return out


def asexplicit_hint(names) -> str:
    return "sudo pacman -D --asexplicit -- " + " ".join(sorted(names))


def installed_by_backend() -> dict[str, set[str]]:
    """このシステムの backend 別インストール済み(明示)集合。失敗時は BackendError。"""
    return {
        "pacman": installed_pacman(),
        "foreign": installed_foreign(),
        "flatpak": installed_flatpak(),
    }


# --------------------------------------------------------------------------
# 導入操作(deploy から呼ぶ)
# --------------------------------------------------------------------------

DEFAULT_AUR_HELPER = "paru"


def install_command(
    backend: str,
    names: list[str],
    aur_helper: str = DEFAULT_AUR_HELPER,
    noconfirm: bool = False,
) -> list[str] | None:
    """backend ごとの導入コマンドを組み立てる(実行はしない)。

    既定では確認を飛ばさない(pacman/AUR ヘルパーの確認や PKGBUILD レビューをそのまま出す)。
    ``noconfirm`` のときだけ pacman/AUR ヘルパーに ``--noconfirm``、flatpak に ``-y`` を渡す。
    AUR ヘルパーは yay 互換の ``-S --needed`` を受け付けるものなら何でもよい(既定 paru)。
    """
    if not names:
        return None
    pkgs = sorted(names)
    yes = ["--noconfirm"] if noconfirm else []
    if backend == "pacman":
        return ["sudo", "pacman", "-S", "--needed", *yes, *pkgs]
    if backend == "foreign":
        return [aur_helper, "-S", "--needed", *yes, *pkgs]
    if backend == "flatpak":
        return ["flatpak", "install", *(["-y"] if noconfirm else []), *pkgs]
    return None


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(cmd: list[str]) -> int:
    return subprocess.run(cmd, check=False).returncode
