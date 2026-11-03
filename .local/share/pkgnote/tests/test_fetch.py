"""fetch の状態遷移(一時ディレクトリ上のコピーで実行)。"""

import pytest

from pkgnote.cli import main
from pkgnote.model import PackagesDoc

BASE = """
tool {
    package "vim"
    package "steam" install-if="tribios"
    package "obs" skip-if="ruan"
}
blocked install-if="laptop" {
    package "touchegg"
}
"""


def props(name):
    return dict(PackagesDoc.load().find_package(name).node.props)


def fetch(*extra):
    return main(["fetch", *extra])


@pytest.fixture
def seeded(env):
    """初回 fetch 済み(観測集合が記録された)状態。"""
    env.write_kdl(BASE)
    env.set_installed(pacman=["vim"])
    assert fetch() == 0
    return env


def test_first_run_only_adds_unknown_and_seeds_state(env):
    env.write_kdl(BASE)
    # obs は条件上入らないが入っている。初回は「新たに入れた」か分からないので書かない。
    env.set_installed(pacman=["vim", "obs", "newpkg"], flatpak=["org.example.App"])
    assert fetch() == 0
    assert props("newpkg") == {
        "from": "pacman", "install-if": "ruan", "first-installed-on": "ruan",
    }
    assert props("org.example.App")["from"] == "flatpak"
    assert props("obs") == {"skip-if": "ruan"}
    assert (env.state / "installed_ruan.txt").read_text().split() == sorted(
        ["vim", "obs", "newpkg", "org.example.App"]
    )


def test_uninstall_appends_skip_if(seeded):
    seeded.set_installed(pacman=[])
    assert fetch() == 0
    assert props("vim") == {"skip-if": "ruan"}


def test_uninstall_appends_to_existing_skip_if(seeded):
    seeded.write_kdl(BASE.replace('package "vim"', 'package "vim" skip-if="work"'))
    seeded.set_installed(pacman=[])
    assert fetch() == 0
    assert props("vim")["skip-if"] == "work | ruan"


def test_reinstall_removes_machine_term_from_own_skip_if(seeded):
    seeded.set_installed(pacman=["vim", "obs"])
    assert fetch() == 0
    assert "skip-if" not in props("obs")


def test_reinstall_with_compound_skip_if(seeded):
    seeded.write_kdl(BASE.replace('skip-if="ruan"', 'skip-if="work | ruan"'))
    seeded.set_installed(pacman=["vim", "obs"])
    assert fetch() == 0
    assert props("obs")["skip-if"] == "work"


def test_reinstall_when_skip_matches_via_class(seeded):
    seeded.write_kdl(BASE.replace('skip-if="ruan"', 'skip-if="desktop"'))
    seeded.set_installed(pacman=["vim", "obs"])
    assert fetch() == 0
    assert props("obs")["skip-if"] == "desktop & !ruan"
    # 結果としてこのマシンでは条件が真になる
    from pkgnote import machines
    from pkgnote.resolve import decide

    names = machines.names_for("ruan", machines.load())
    assert decide(PackagesDoc.load().find_package("obs"), names).install


def test_install_appends_to_own_install_if(seeded):
    seeded.set_installed(pacman=["vim", "steam"])
    assert fetch() == 0
    assert props("steam")["install-if"] == "tribios | ruan"


def test_category_blocked_is_warned_not_written(seeded, capsys):
    before = seeded.read_kdl()
    seeded.set_installed(pacman=["vim", "touchegg"])
    assert fetch() == 0
    assert seeded.read_kdl() == before
    err = capsys.readouterr().err
    assert "カテゴリ側の条件" in err and "blocked" in err
    # status でも理由付きの EXTRA として出続ける
    assert main(["status"]) == 0
    assert "カテゴリ側の条件で除外" in capsys.readouterr().out


def test_never_installed_package_is_not_skipped(seeded):
    """手で追記しただけ(このマシンで一度も観測していない)なら skip-if を付けない。"""
    seeded.write_kdl(BASE + 'extra {\n    package "newly-labelled"\n}\n')
    assert fetch() == 0
    assert props("newly-labelled") == {}


def test_dry_run_writes_nothing(seeded):
    before = seeded.read_kdl()
    state = (seeded.state / "installed_ruan.txt").read_text()
    seeded.set_installed(pacman=["brand-new"])
    assert fetch("--dry-run") == 0
    assert seeded.read_kdl() == before
    assert (seeded.state / "installed_ruan.txt").read_text() == state


def test_legacy_schema_refused_without_writing(env, capsys):
    legacy = 'uncategorized {\n    package "x" first_installed_on="ruan" {\n        installed_on "ruan"\n    }\n}\n'
    env.write_kdl(legacy)
    env.set_installed(pacman=["x", "y"])
    assert fetch() == 1
    assert env.read_kdl() == legacy
    assert "旧形式" in capsys.readouterr().err
    assert not (env.state / "installed_ruan.txt").exists()


def test_bad_expression_refused_without_writing(env):
    bad = 'a {\n    package "x" install-if="ruan &"\n}\n'
    env.write_kdl(bad)
    env.set_installed(pacman=["y"])
    assert fetch() == 1
    assert env.read_kdl() == bad


def test_unknown_machine_refused(env, capsys):
    env.write_kdl(BASE)
    env.set_installed(pacman=["y"])
    (env.root / "yadmcfg").write_text("[local]\n\thostname = nosuch\n")
    assert fetch() == 1
    assert "machines.toml" in capsys.readouterr().err
    assert "package \"y\"" not in env.read_kdl()


def test_fetch_for_other_machine_refused(env, capsys):
    env.write_kdl(BASE)
    env.set_installed(pacman=["y"])
    assert fetch("--machine", "tribios") == 1
    assert "現在のマシン(ruan)ではありません" in capsys.readouterr().err
    assert "package \"y\"" not in env.read_kdl()
    assert not (env.state / "installed_tribios.txt").exists()
    # 現在のマシン名と同じなら可
    assert fetch("--machine", "ruan") == 0


def test_backend_query_failure_aborts_without_writing(seeded, monkeypatch, capsys):
    from pkgnote import backends

    before = seeded.read_kdl()
    state = (seeded.state / "installed_ruan.txt").read_text()

    def boom():
        raise backends.BackendError("`pacman -Qqem` が失敗しました: test")

    monkeypatch.setattr(backends, "installed_foreign", boom)
    seeded.set_installed(pacman=[])  # 仮に他が空でも、失敗があれば何もしない
    assert fetch() == 1
    assert "pacman -Qqem" in capsys.readouterr().err
    assert seeded.read_kdl() == before
    assert (seeded.state / "installed_ruan.txt").read_text() == state


MANY = "many {\n" + "".join(f'    package "p{i}"\n' for i in range(8)) + "}\n"


def test_mass_removal_is_refused_unless_allowed(env, capsys):
    env.write_kdl(MANY)
    env.set_installed(pacman=[f"p{i}" for i in range(8)])
    assert fetch() == 0
    seen = (env.state / "installed_ruan.txt").read_text()
    before = env.read_kdl()
    env.set_installed(pacman=["p0", "unrelated-new"])  # 7 件が消えたように見える
    assert fetch() == 1
    assert "--allow-mass-removal" in capsys.readouterr().err
    assert env.read_kdl() == before
    assert (env.state / "installed_ruan.txt").read_text() == seen
    assert fetch("--allow-mass-removal") == 0
    assert props("p7") == {"skip-if": "ruan"}
    assert props("unrelated-new")["install-if"] == "ruan"


def test_few_removals_are_fine(env):
    env.write_kdl(MANY)
    env.set_installed(pacman=[f"p{i}" for i in range(8)])
    assert fetch() == 0
    env.set_installed(pacman=[f"p{i}" for i in range(3, 8)])
    assert fetch() == 0
    assert [props(f"p{i}").get("skip-if") for i in range(4)] == ["ruan", "ruan", "ruan", None]


def test_empty_observation_file_counts_as_first_run(env):
    env.write_kdl(BASE)
    env.state.mkdir()
    (env.state / "installed_ruan.txt").write_text("")
    env.set_installed(pacman=[])  # vim が「消えた」ように見えても初回扱いで何も書かない
    before = env.read_kdl()
    assert fetch() == 0
    assert env.read_kdl() == before
    # 空集合は保存しない
    assert (env.state / "installed_ruan.txt").read_text() == ""
    env.set_installed(pacman=["vim"])
    assert fetch() == 0
    assert (env.state / "installed_ruan.txt").read_text() == "vim\n"


def test_backend_change_updates_from(seeded, capsys):
    seeded.write_kdl(BASE.replace('package "vim"', 'package "vim" from="foreign"'))
    seeded.set_installed(pacman=["vim"])
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "MISSING" not in out.split("summary")[0].replace("MISSING=", "")
    assert 'tool/vim: KDL from="foreign" / 実機 pacman' in out
    assert "FROM-MISMATCH=1" in out
    assert fetch() == 0
    assert props("vim") == {"from": "pacman"}
    assert "skip-if" not in props("vim")


def test_concurrent_modification_is_not_clobbered(env, monkeypatch):
    env.write_kdl(BASE)
    env.set_installed(pacman=["y"])
    orig = PackagesDoc.save

    def racing_save(self, path=None):
        env.kdl_path.write_text(env.read_kdl() + "\nother {\n    package \"z\"\n}\n")
        return orig(self, path)

    monkeypatch.setattr(PackagesDoc, "save", racing_save)
    assert fetch() == 1
    assert 'package "y"' not in env.read_kdl()
    assert 'package "z"' in env.read_kdl()


def test_header_kept_and_output_stable(seeded):
    seeded.set_installed(pacman=["vim", "brand-new"])
    assert fetch() == 0
    text = seeded.read_kdl()
    assert text.startswith("// pkgnote packages.kdl")
    # もう一度 fetch しても何も変わらない(冪等)
    assert fetch() == 0
    assert seeded.read_kdl() == text


def test_missing_notes_use_provides_and_dependency(seeded, capsys):
    """fetch の「未導入」の表示は status / deploy と同じ分類。書き込みは変えない。"""
    from pkgnote import backends

    seeded.write_kdl(BASE + 'extra {\n    package "paru" from="foreign"\n    package "libfoo"\n'
                     '    package "dotnet-sdk"\n}\n')
    seeded.set_installed(pacman=["vim", "dotnet-sdk-9.0-bin"], foreign=["paru-bin"])
    seeded.infos = [
        backends.PkgInfo("paru-bin", frozenset({"paru"}), frozenset({"paru"})),
        backends.PkgInfo("dotnet-sdk-9.0-bin", frozenset({"dotnet-sdk"})),
    ]
    seeded.deps = {"libfoo"}
    capsys.readouterr()
    assert fetch() == 0
    out = capsys.readouterr().out
    assert "paru: paru-bin で導入済み" in out
    assert "libfoo: 依存として導入済み" in out and "--asexplicit -- libfoo" in out
    assert "dotnet-sdk: 条件上は入るが未導入(MISSING)" in out
    # write path unchanged: no skip-if for these never-seen names
    for name in ("paru", "libfoo", "dotnet-sdk"):
        assert "skip-if" not in props(name)


def test_missing_notes_survive_classify_failure(seeded, monkeypatch, capsys):
    from pkgnote import backends

    def boom(*a):
        raise backends.BackendError("pacman -T broke")

    monkeypatch.setattr(backends, "classify", boom)
    seeded.write_kdl(BASE + 'extra {\n    package "libfoo"\n}\n')
    capsys.readouterr()
    assert fetch() == 0
    captured = capsys.readouterr()
    assert "libfoo: 条件上は入るが未導入(MISSING)" in captured.out
    assert "pacman -T broke" in captured.err
