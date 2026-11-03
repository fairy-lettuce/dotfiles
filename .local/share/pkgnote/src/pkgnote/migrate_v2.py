"""一回限りの移行: machine_*.kdl + installed_on 形式 → install-if / skip-if 形式。

使い方::

    uv run --project ~/.local/share/pkgnote python -m pkgnote.migrate_v2 [--dry-run] [packages.kdl]

やること:

1. プロパティ名を kebab-case に(``first_installed_on`` → ``first-installed-on``)。
2. ``uncategorized`` 配下の package は ``installed_on "<m>"`` 子ノードを
   ``install-if="<m1> | <m2> …"`` に変換する。``installed_on`` が 1 つも無い(どこにも
   入っていない)ものは ``install-if="<first-installed-on>"`` にする(4. で ``skip-if`` も付き、
   どのマシンにも入らない)。旧モデルでは uncategorized は ``installed_on`` だけで決まり、
   machine ファイルの無いマシンにも入らなかったので、その意味を保つ。
3. それ以外の ``installed_on`` ノードは削除する(正式カテゴリでは元々判定に使われない
   inert な情報だった)。
4. 同じディレクトリの旧 ``machine_<m>.kdl`` ごとに旧モデルでの導入対象を計算し、新モデルの
   結果と食い違うパッケージだけ package 自身の条件で補正する(旧モデルで入らないのに
   新モデルで入る → ``skip-if`` に ``<m>`` を追記)。正式カテゴリのパッケージに機械的に
   ``install-if`` を付けることはしない(どのマシンに入れるかは手でラベル付けする)。
5. 新モデルで読み直し、全マシンで旧モデルと結果が一致することを確認してから書き込む。

machine_*.kdl 自体は読むだけで、削除も変更もしない。移行が済めばこのモジュールは不要。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import kdl
from . import machines as machines_mod
from .kdl import KNode
from .model import (
    FIRST_INSTALLED_ON,
    HEADER,
    INSTALL_IF,
    SKIP_IF,
    UNCATEGORIZED,
    PackagesDoc,
)
from .resolve import decide

_RENAMES = {"first_installed_on": FIRST_INSTALLED_ON, "install_if": INSTALL_IF, "skip_if": SKIP_IF}
_OLD_NODES = ("installed_on", "installed-on")


# --- 旧モデルの解決(machine 木の最深 include + uncategorized の installed_on) ------------


def _old_desired(roots: list[KNode], machine_root: KNode, machine: str) -> set[str]:
    out: set[str] = set()

    def walk(node: KNode, path: tuple[str, ...]) -> None:
        for c in node.children:
            if c.name == "package":
                if path and path[0] == UNCATEGORIZED:
                    io = {str(x.args[0]) for x in c.children if x.name in _OLD_NODES and x.args}
                    if machine in io:
                        out.add(str(c.args[0]))
                    continue
                explicit = machine_root.props.get("include")
                mnode = machine_root
                reached = True
                for name in path:
                    mnode = mnode.find_category(name)
                    if mnode is None:
                        reached = False
                        break
                    if isinstance(mnode.props.get("include"), bool):
                        explicit = mnode.props["include"]
                if reached:
                    pnode = mnode.find_package(str(c.args[0]))
                    if pnode is not None and isinstance(pnode.props.get("include"), bool):
                        explicit = pnode.props["include"]
                if explicit is True:  # 旧 deploy は未指定(None)も導入しなかった
                    out.add(str(c.args[0]))
            elif c.name not in _OLD_NODES:
                walk(c, path + (c.name,))

    for r in roots:
        walk(r, (r.name,))
    return out


def _old_machines(directory: Path) -> dict[str, KNode]:
    result: dict[str, KNode] = {}
    for f in sorted(directory.glob("machine_*.kdl")):
        for n in kdl.load_file(f):
            if n.name == "machine" and n.args:
                result[str(n.args[0])] = n
    return result


# --- 変換 -----------------------------------------------------------------------------


def migrate(
    roots: list[KNode], old_machines: dict[str, KNode], machines: dict[str, dict]
) -> tuple[PackagesDoc, list[str]]:
    """roots を(破壊的に)移行し、(新ドキュメント, 補正ログ) を返す。"""
    old = {m: _old_desired(roots, mr, m) for m, mr in old_machines.items()}
    # machine ファイルの無いマシン(machines.toml にだけある)でも、旧モデルでの
    # uncategorized の結果(installed_on に名前があるものだけ)は保つ。
    old_unc: dict[str, set[str]] = {}
    for m in machines:
        old_unc[m] = {
            str(c.args[0])
            for r in roots if r.name == UNCATEGORIZED
            for c in r.children
            if c.name == "package"
            and any(x.name in _OLD_NODES and x.args and str(x.args[0]) == m for x in c.children)
        }

    def walk(node: KNode, path: tuple[str, ...]) -> None:
        for old_key, new_key in _RENAMES.items():
            if old_key in node.props:
                node.props[new_key] = node.props.pop(old_key)
        if node.name == "package":
            if path and path[0] == UNCATEGORIZED:
                ms: list[str] = []
                for c in node.children:
                    if c.name in _OLD_NODES and c.args and str(c.args[0]) not in ms:
                        ms.append(str(c.args[0]))
                if not ms and FIRST_INSTALLED_ON in node.props:
                    # どこにも入っていない(入れた後に消した)もの。install-if を空にすると
                    # 「全マシン」になってしまうので、最初のマシンに限定しておき、そのマシンでの
                    # 削除は下の補正で skip-if として記録する(= fetch が付ける履歴と同じ形)。
                    ms = [str(node.props[FIRST_INSTALLED_ON])]
                if ms and INSTALL_IF not in node.props:
                    node.props[INSTALL_IF] = " | ".join(ms)
            node.children = [c for c in node.children if c.name not in _OLD_NODES]
            return
        node.children = [c for c in node.children if c.name not in _OLD_NODES]
        for c in node.children:
            walk(c, path + (c.name,))

    for r in roots:
        walk(r, (r.name,))

    doc = PackagesDoc(roots=roots)
    log: list[str] = []

    def names(m: str) -> set[str]:
        return {m, *machines_mod.derive_classes(machines.get(m, {}), m)}

    for m in sorted(old):
        for pkg in doc.packages():
            d = decide(pkg, names(m))
            was = pkg.name in old[m]
            if was and not d.install:
                if not (d.category_install and not d.category_skip and not d.own_skip):
                    raise RuntimeError(f"{pkg.label}: {m} で導入対象のはずが新モデルで外れる")
                cur = pkg.node.props.get(INSTALL_IF)
                pkg.node.props[INSTALL_IF] = f"{cur} | {m}" if cur else m
                log.append(f"{pkg.label}: install-if に {m} を追加(旧: {m} で導入対象)")
            elif not was and d.install:
                cur = pkg.node.props.get(SKIP_IF)
                pkg.node.props[SKIP_IF] = f"{cur} | {m}" if cur else m
                log.append(f"{pkg.label}: skip-if に {m} を追加(旧: {m} では導入対象外)")

    for m in sorted(old):
        new = {p.name for p in doc.packages() if decide(p, names(m)).install}
        if new != old[m]:
            raise RuntimeError(f"{m}: 移行後の導入対象が一致しません: {sorted(new ^ old[m])}")
    for m in sorted(old_unc):
        new = {
            p.name for p in doc.packages()
            if p.is_uncategorized and decide(p, names(m)).install
        }
        if new != old_unc[m]:
            raise RuntimeError(
                f"{m}: 移行後の uncategorized の導入対象が一致しません: {sorted(new ^ old_unc[m])}"
            )
    doc.validate()
    return doc, log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pkgnote.migrate_v2")
    ap.add_argument("file", nargs="?", type=Path, help="packages.kdl(既定 ~/.pacman/packages.kdl)")
    ap.add_argument("--dry-run", action="store_true", help="書き込まず結果を標準出力へ")
    args = ap.parse_args(argv)

    from . import paths

    path: Path = args.file or paths.packages_file()
    text = path.read_text(encoding="utf-8")
    roots = kdl.loads(text, source=str(path))
    try:
        machines = machines_mod.load()
    except machines_mod.MachineError:
        machines = {}
    old_machines = _old_machines(path.parent)
    doc, log = migrate(roots, old_machines, machines)

    out = kdl.dumps(doc.roots, header=HEADER)
    print(f"旧 machine ファイル: {', '.join(sorted(old_machines)) or 'なし'}", file=sys.stderr)
    for line in log:
        print(f"  補正: {line}", file=sys.stderr)
    if args.dry_run:
        sys.stdout.write(out)
        return 0
    if path.read_text(encoding="utf-8") != text:
        print("読み込み後にファイルが変更されたため中止しました", file=sys.stderr)
        return 1
    kdl.write_text_atomic(path, out)
    print(f"{path} を移行しました", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
