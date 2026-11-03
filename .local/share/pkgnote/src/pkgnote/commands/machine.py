"""``pkgnote machine name|classes`` — マシンの論理名・クラスを表示する。

``classes`` は 1 行 1 名。セットアップスクリプトから yadm の ``local.class`` に
流し込む用途を想定している(規則は :mod:`pkgnote.machines` にだけある)。
"""

from __future__ import annotations

from .. import machines


def run(what: str, machine: str | None = None) -> int:
    name = machine or machines.current_machine()
    if what == "name":
        print(name)
        return 0
    table = machines.load()
    machines.names_for(name, table)  # 未定義ならここでエラー
    for cls in machines.derive_classes(table[name], name):
        print(cls)
    return 0
