"""マシン属性(``~/.config/machines.toml``)と、そこから得る「クラス名」。

条件式(``install-if`` / ``skip-if``)で使える名前は、

- マシンの論理名(machines.toml のテーブルキー。例 ``ruan``)
- 各マシンの属性の値(下記 :func:`derive_classes`)

の 2 種類。規則はここにしか書かない。``pkgnote machine classes`` で一覧を出せるので、
セットアップスクリプトはそれを yadm の ``local.class`` に流し込めばよい。

現在のマシンの論理名は yadm の ``local.hostname``
(``git config -f ~/.dotfiles/config local.hostname``)から取る。``--machine`` で上書き可。
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

from . import paths
from .errors import PkgnoteError

# この値はクラスを出さない(``encryption = "none"`` など、「その属性がない」ことを書くため)。
NONE_VALUE = "none"

# マシンの論理名とクラス名の規則(ホスト名のラベル、RFC 1123): 英数字と '-'、先頭・末尾は '-' 不可、
# 1〜63 文字。条件式の名前(expr.py の NAME)はこれより広い集合なので、そのまま書ける。
NAME_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
NAME_RULE = "英数字と '-'(先頭・末尾は '-' 不可)、1〜63 文字"


class MachineError(PkgnoteError):
    """マシン名・machines.toml まわりの設定不備。"""


def derive_classes(attrs: dict, machine: str = "?") -> list[str]:
    """1 マシンの属性テーブルからクラス名の列を得る(出現順)。

    キーはラベルにすぎず、文字列の値と、文字列の配列の各要素が、そのままクラス名になる
    (``cpu = "intel-cpu"`` → ``intel-cpu``、``gpu = ["intel-gpu", "nvidia-gpu"]`` → 両方)。
    例外は ``"none"`` で、何も出さない。真偽値・数値・テーブル・空文字列はエラー。
    1 マシンの中で同じクラスが 2 回出てきてもエラー。許可値の検査はしない。
    """
    out: list[str] = []
    for key, value in attrs.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            if not isinstance(v, str) or not v.strip():
                raise MachineError(
                    f"machines.toml の [{machine}] {key}: 値は文字列か文字列の配列にしてください"
                    f"(得られた値: {v!r})。属性がないことは \"{NONE_VALUE}\" で書きます"
                )
            if v == NONE_VALUE:
                continue
            if not NAME_RE.match(v):
                raise MachineError(f"machines.toml の [{machine}] {key}: クラス名 `{v}` が不正です({NAME_RULE})")
            if v in out:
                raise MachineError(f"machines.toml の [{machine}]: クラス `{v}` が重複しています({key})")
            out.append(v)
    return out


def load(path: Path | None = None) -> dict[str, dict]:
    """machines.toml を ``{論理名: 属性テーブル}`` として読む。"""
    p = path or paths.machines_file()
    if not p.exists():
        raise MachineError(f"{p} がありません(マシン属性の定義ファイル)")
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise MachineError(f"{p}: TOML の解析に失敗しました: {exc}") from exc
    out: dict[str, dict] = {}
    for name, attrs in data.items():
        if not isinstance(attrs, dict):
            raise MachineError(f"{p}: `{name}` はマシンのテーブル(`[{name}]`)にしてください")
        if not NAME_RE.match(name):
            raise MachineError(f"{p}: マシンの論理名 `{name}` が不正です({NAME_RULE})")
        derive_classes(attrs, name)  # 形式の検査(不正ならここでエラー)
        out[name] = attrs
    return out


def names_for(machine: str, machines: dict[str, dict]) -> set[str]:
    """条件式の評価に使う名前集合(論理名 + クラス)。"""
    if machine not in machines:
        raise MachineError(
            f"マシン `{machine}` が {paths.machines_file()} に定義されていません。"
            f"`[{machine}]` テーブルを追加してください"
        )
    return {machine, *derive_classes(machines[machine], machine)}


def known_names(machines: dict[str, dict]) -> set[str]:
    """条件式で「既知」とみなす全名前(全マシンの論理名 + 全マシンのクラス)。"""
    out: set[str] = set(machines)
    for name, attrs in machines.items():
        out.update(derive_classes(attrs, name))
    return out


def current_machine() -> str:
    """yadm の ``local.hostname`` から現在のマシンの論理名を得る。"""
    cfg = paths.yadm_config_file()
    try:
        res = subprocess.run(
            ["git", "config", "-f", str(cfg), "local.hostname"],
            capture_output=True,
            text=True,
            check=False,
        )
        name = res.stdout.strip() if res.returncode == 0 else ""
    except OSError:
        name = ""
    if not name:
        raise MachineError(
            "現在のマシンの論理名が分かりません(yadm の local.hostname が未設定)。\n"
            "  `yadm --yadm-repo ~/.dotfiles config local.hostname <name>` で設定するか、"
            "`--machine <name>` を指定してください"
        )
    return name
