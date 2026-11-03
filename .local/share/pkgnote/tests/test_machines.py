import pytest

from pkgnote import machines


def test_derive_classes_ruan_and_tribios(env):
    table = machines.load()
    assert machines.derive_classes(table["ruan"]) == [
        "desktop", "intel-cpu", "nvidia-gpu", "grub", "ext4", "personal", "gaming", "dualboot",
    ]
    assert machines.derive_classes(table["tribios"]) == [
        "laptop", "intel-cpu", "intel-gpu", "systemd-boot", "btrfs",
        "luks", "secureboot", "work", "touch",
    ]


def test_derive_classes_verbatim_lists_and_none():
    attrs = {"cpu": "amd-cpu", "gpu": ["intel-gpu", "nvidia-gpu"], "display": "hidpi",
             "tpm": "none", "tags": ["a", "none", "b"], "empty": []}
    # 値はそのままクラス名(接尾辞は付けない)。"none" は何も出さない。許可リストは持たない。
    assert machines.derive_classes(attrs) == ["amd-cpu", "intel-gpu", "nvidia-gpu", "hidpi", "a", "b"]


@pytest.mark.parametrize("value", [True, False, 1, 2.5, {"x": "y"}, ["a", 1], ["a", True], "", [""]])
def test_derive_classes_rejects_non_strings(value):
    with pytest.raises(machines.MachineError, match=r"\[box\] key: 値は文字列か文字列の配列"):
        machines.derive_classes({"key": value}, "box")


def test_derive_classes_rejects_duplicates():
    with pytest.raises(machines.MachineError, match=r"\[box\]: クラス `intel-gpu` が重複"):
        machines.derive_classes({"cpu": "intel-gpu", "gpu": "intel-gpu"}, "box")
    with pytest.raises(machines.MachineError, match="重複"):
        machines.derive_classes({"roles": ["work", "work"]}, "box")


def test_load_validates_every_machine(env):
    (env.root / "machines.toml").write_text('[a]\nform = "laptop"\n[b]\nencryption = true\n')
    with pytest.raises(machines.MachineError, match=r"\[b\] encryption"):
        machines.load()
    (env.root / "machines.toml").write_text('stray = "x"\n[a]\nform = "laptop"\n')
    with pytest.raises(machines.MachineError, match="stray"):
        machines.load()


def test_names_for_and_known(env):
    table = machines.load()
    assert machines.names_for("ruan", table) >= {"ruan", "desktop", "nvidia-gpu"}
    assert "none" not in machines.names_for("ruan", table)
    assert "luks" not in machines.names_for("ruan", table)
    known = machines.known_names(table)
    assert {"ruan", "tribios", "laptop", "luks", "secureboot", "intel-gpu"} <= known
    assert "none" not in known and "encryption" not in known
    with pytest.raises(machines.MachineError, match=r"\[nosuch\]"):
        machines.names_for("nosuch", table)


def test_current_machine_from_yadm_config(env):
    assert machines.current_machine() == "ruan"


def test_current_machine_unset_is_clear_error(env):
    (env.root / "yadmcfg").write_text("[core]\n")
    with pytest.raises(machines.MachineError) as ei:
        machines.current_machine()
    assert "local.hostname" in str(ei.value)
    assert "--machine" in str(ei.value)


def test_cli_machine_classes(env, capsys):
    from pkgnote.cli import main

    assert main(["machine", "classes", "--machine", "tribios"]) == 0
    out = capsys.readouterr().out.split()
    assert out[:2] == ["laptop", "intel-cpu"]
    assert main(["machine", "name"]) == 0
    assert capsys.readouterr().out.strip() == "ruan"


def test_cli_unset_machine_reports_error(env, capsys):
    from pkgnote.cli import main

    (env.root / "yadmcfg").write_text("")
    assert main(["status"]) == 1
    assert "local.hostname" in capsys.readouterr().err


@pytest.mark.parametrize("toml, msg", [
    ('[a_b]\nform = "laptop"\n', r"論理名 `a_b` が不正"),
    ('[-a]\nform = "laptop"\n', r"論理名 `-a` が不正"),
    ('[a]\ncpu = "intel_cpu"\n', r"クラス名 `intel_cpu` が不正"),
    ('[a]\ncpu = "intel-"\n', r"クラス名 `intel-` が不正"),
    ('[a]\nroles = ["' + "x" * 64 + '"]\n', r"クラス名 `x+` が不正"),
])
def test_load_rejects_bad_names(env, toml, msg):
    (env.root / "machines.toml").write_text(toml)
    with pytest.raises(machines.MachineError, match=msg):
        machines.load()


def test_class_may_equal_machine_name(env):
    (env.root / "machines.toml").write_text('[a]\nform = "b"\n[b]\nform = "a"\n')
    assert machines.derive_classes(machines.load()["a"]) == ["b"]
    assert "x" * 63 in machines.derive_classes({"r": ["x" * 63]})


def test_cli_parse_error_is_clear(env, capsys):
    from pkgnote.cli import main

    (env.root / "machines.toml").write_text("[ruan\n")
    assert main(["machine", "classes"]) == 1
    err = capsys.readouterr().err
    assert "TOML の解析に失敗しました" in err
    assert "Traceback" not in err
