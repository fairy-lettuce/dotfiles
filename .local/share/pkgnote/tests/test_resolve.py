from pkgnote import machines
from pkgnote.model import PackagesDoc
from pkgnote.resolve import decide, desired_set, unknown_names

DOC = """
tool install-if="desktop | laptop" {
    gui skip-if="work" {
        package "steam" install-if="gaming"
        package "vlc"
        package "obs" skip-if="ruan"
    }
    package "htop"
}
plain {
    package "git"
}
uncategorized {
    package "newtool" install-if="ruan"
}
"""


def names(m):
    return machines.names_for(m, machines.load())


def load(env, text=DOC):
    env.write_kdl(text)
    return PackagesDoc.load()


def test_inheritance(env):
    doc = load(env)
    r = desired_set(doc, names("ruan"))
    t = desired_set(doc, names("tribios"))
    assert r["pacman"] == {"steam", "vlc", "htop", "git", "newtool"}
    # tribios: laptop なので tool は真、だが gui の skip-if=work が真 → gui 配下は全部外れる
    assert t["pacman"] == {"htop", "git"}


def test_no_condition_means_all_machines(env):
    doc = load(env)
    for m in ("ruan", "tribios"):
        assert "git" in desired_set(doc, names(m))["pacman"]


def test_skip_wins_over_install(env):
    doc = load(env, 'a { package "x" install-if="ruan" skip-if="desktop" }\n')
    assert not decide(doc.packages()[0], names("ruan")).install


def test_category_install_is_anded(env):
    doc = load(env, 'a install-if="tribios" { package "x" install-if="ruan" }\n')
    d = decide(doc.packages()[0], names("ruan"))
    assert not d.install and not d.category_install and d.own_install


def test_uncategorized_has_no_special_meaning(env):
    doc = load(env, 'uncategorized { package "x" }\n')
    assert desired_set(doc, names("tribios"))["pacman"] == {"x"}


def test_unknown_names_warn_not_error(env, capsys):
    doc = load(env, 'a install-if="hidpi | ruan" { package "x" skip-if="amd-gpu" }\n')
    found = unknown_names(doc, machines.known_names(machines.load()))
    assert [n for _, n in found] == ["hidpi", "amd-gpu"]
    assert "packages.kdl: a" in found[0][0]
    # CLI でも警告(stderr)を出しつつ正常終了する
    from pkgnote.cli import main

    env.set_installed()
    assert main(["status"]) == 0
    err = capsys.readouterr().err
    assert "未知の名前 `hidpi`" in err and "未知の名前 `amd-gpu`" in err


def test_expression_error_has_file_and_node_path(env, capsys):
    env.write_kdl('tool { gui { package "x" install-if="ruan tribios" } }\n')
    from pkgnote.cli import main

    env.set_installed()
    assert main(["status"]) == 1
    err = capsys.readouterr().err
    assert 'packages.kdl: tool/gui/package "x" の install-if' in err
    assert "並置" in err
