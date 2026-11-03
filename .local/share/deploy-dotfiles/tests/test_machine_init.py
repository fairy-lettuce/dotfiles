"""Tests for machine-init.py.

Run: uv run --no-project --with pytest pytest -q ~/.local/share/deploy-dotfiles/tests
Detection is replaced by fakes; no real system command is run.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tomllib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "machine-init.py"
spec = importlib.util.spec_from_file_location("machine_init", SCRIPT)
mi = importlib.util.module_from_spec(spec)
sys.modules["machine_init"] = mi
spec.loader.exec_module(mi)

HEADER = """# List of machines using this dotfiles
# values are public
"""

TOML = HEADER + """
[alpha]
form = "desktop"
cpu = "intel-cpu"
gpu = "nvidia-gpu"
bootloader = "grub"
filesystem = "ext4"
encryption = "none"
secureboot = "none"
roles = ["personal", "gaming"]

# comment before beta
[beta]
form = "laptop"
cpu = "intel-cpu"
gpu = "intel-gpu"  # inline comment
bootloader = "systemd-boot"
filesystem = "btrfs"
encryption = "luks"
secureboot = "secureboot"
roles = ["work", "touch"]
"""

DETECTED = {
    "form": "laptop",
    "cpu": "intel-cpu",
    "gpu": ["intel-gpu"],
    "bootloader": "systemd-boot",
    "filesystem": "btrfs",
    "encryption": "luks",
    "secureboot": "none",
}


@pytest.fixture(autouse=True)
def no_real_system_files(tmp_path, monkeypatch):
    """Detection must never read this machine's EFI variables, cpuinfo or /boot."""
    monkeypatch.setenv("MACHINE_INIT_EFIVARS", str(tmp_path / "no-efivars"))
    monkeypatch.setenv("MACHINE_INIT_GRUB_DIR", str(tmp_path / "no-grub"))
    monkeypatch.setenv("MACHINE_INIT_PROC_CPUINFO", str(tmp_path / "no-cpuinfo"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "machines.toml"
    path.write_text(TOML)
    monkeypatch.setenv("PKGNOTE_MACHINES_FILE", str(path))
    detected = dict(DETECTED)

    def fake_detector(key):
        return lambda: detected.get(key)

    for key in mi.DETECTORS:
        monkeypatch.setitem(mi.DETECTORS, key, fake_detector(key))
    monkeypatch.setattr(mi, "detect_hostname", lambda: "gamma")

    def no_run(cmd):
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(mi, "run", no_run)

    class Env:
        pass

    e = Env()
    e.path, e.detected = path, detected

    def call(args, stdin=""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        return mi.main(args)

    e.call = call
    return e


def read(path):
    return tomllib.loads(path.read_text())


# ---------------------------------------------------------------- new / existing


def test_new_machine_noconfirm_uses_detection(env, capsys):
    assert env.call(["--noconfirm"]) == 0
    out = capsys.readouterr()
    assert out.out == "gamma\n"
    data = read(env.path)
    assert data["gamma"] == {
        "form": "laptop", "cpu": "intel-cpu", "gpu": "intel-gpu", "bootloader": "systemd-boot",
        "filesystem": "btrfs", "encryption": "luks", "secureboot": "none", "roles": [],
    }
    assert data["alpha"]["roles"] == ["personal", "gaming"]


def test_new_machine_noconfirm_missing_detection_left_out(env, capsys):
    env.detected["cpu"] = None
    assert env.call(["--noconfirm", "--machine", "delta"]) == 0
    assert "cpu" not in read(env.path)["delta"]
    assert "not detected (left out): cpu" in capsys.readouterr().err


def test_new_machine_interactive_with_detection_and_confirmation(env, capsys):
    # hostname default (gamma) -> public warning: n -> ask again -> "delta" -> y
    stdin = "\nn\ndelta\ny\n" + "\n" * 7 + "work\nq\n"
    assert env.call([], stdin) == 0
    out = capsys.readouterr()
    assert out.out == "delta\n"
    assert "Setting classes for this machine..." in out.err
    assert "**hostname** (default: gamma): " in out.err
    assert "**cpu** (default: intel-cpu): " in out.err
    assert out.err.count("will be PUBLIC on GitHub") == 2
    data = read(env.path)
    assert "gamma" not in data
    assert data["delta"]["roles"] == ["work"]
    assert data["delta"]["form"] == "laptop"


def test_invalid_hostname_reasked(env, capsys):
    stdin = "bad name\nok-name\ny\n" + "\n" * 7 + "q\n"
    assert env.call([], stdin) == 0
    assert "Invalid name `bad name`" in capsys.readouterr().err
    assert "ok-name" in read(env.path)


def test_existing_machine_defaults_unchanged(env, capsys):
    before = env.path.read_text()
    stdin = "\n" * 8 + "\n"  # hostname + 7 keys + empty first roles line (keep)
    assert env.call(["--machine", "beta"], stdin) == 0
    out = capsys.readouterr()
    assert out.out == "beta\n"
    assert "PUBLIC" not in out.err
    assert "**form** (default: laptop): " in out.err
    assert "keeps the current roles: work, touch" in out.err
    assert "unchanged" in out.err
    assert env.path.read_text() == before


def test_existing_machine_noconfirm_unchanged(env, capsys):
    before = env.path.read_text()
    assert env.call(["--noconfirm", "--machine", "alpha"]) == 0
    assert env.path.read_text() == before


def test_existing_machine_change_value(env, capsys):
    stdin = "\n\n\nintel-gpu, nvidia-gpu\n" + "\n" * 4 + "\n"
    assert env.call(["--machine", "alpha"], stdin) == 0
    assert read(env.path)["alpha"]["gpu"] == ["intel-gpu", "nvidia-gpu"]
    # beta and its comments are untouched
    text = env.path.read_text()
    assert "# comment before beta\n[beta]" in text
    assert 'gpu = "intel-gpu"  # inline comment' in text
    assert text.startswith(HEADER)


def test_hybrid_gpu_detected_list(env, capsys):
    env.detected["gpu"] = ["intel-gpu", "nvidia-gpu"]
    stdin = "\ny\n" + "\n" * 7 + "q\n"
    assert env.call([], stdin) == 0
    err = capsys.readouterr().err
    assert "Several GPUs detected: intel-gpu, nvidia-gpu" in err
    assert "**gpu** (default: intel-gpu, nvidia-gpu): " in err
    assert read(env.path)["gamma"]["gpu"] == ["intel-gpu", "nvidia-gpu"]
    assert 'gpu = ["intel-gpu", "nvidia-gpu"]' in env.path.read_text()
    # noconfirm keeps the list too
    env.path.write_text(TOML)
    assert env.call(["--noconfirm"]) == 0
    assert read(env.path)["gamma"]["gpu"] == ["intel-gpu", "nvidia-gpu"]


def test_no_default_requires_value_and_none_allowed(env, capsys):
    env.detected["secureboot"] = None
    stdin = "\ny\n" + "\n" * 6 + "\nnone\n" + "q\n"
    assert env.call([], stdin) == 0
    assert 'Enter a value (or "none")' in capsys.readouterr().err
    assert read(env.path)["gamma"]["secureboot"] == "none"


def test_duplicate_class_reasked(env, capsys):
    # form = intel-cpu, then the cpu default (intel-cpu) collides -> must enter another
    stdin = "\ny\nintel-cpu\n\namd-cpu\n" + "\n" * 5 + "q\n"
    assert env.call([], stdin) == 0
    err = capsys.readouterr().err
    assert "`intel-cpu` is already used" in err
    assert read(env.path)["gamma"]["cpu"] == "amd-cpu"


# ---------------------------------------------------------------- roles


def test_roles_ls_q_and_duplicates(env, capsys):
    stdin = "\ny\n" + "\n" * 7 + "ls\nwork, gaming\nwork\nnone\nnewrole\nq\n"
    assert env.call([], stdin) == 0
    err = capsys.readouterr().err
    assert '**roles**: Input roles for this machine. Press "q" to end. Press "ls" to list existing roles.' in err
    assert "roles used by machines: personal, gaming, work, touch" in err
    assert "`work` skipped" in err and "`none` skipped" in err
    assert "roles: `newrole` is not used by any other machine (typo?)" in err
    assert read(env.path)["gamma"]["roles"] == ["work", "gaming", "newrole"]


def test_roles_keep_existing_vs_replace(env, capsys):
    stdin = "\n" * 8 + "personal\nq\n"
    assert env.call(["--machine", "alpha"], stdin) == 0
    assert read(env.path)["alpha"]["roles"] == ["personal"]


def test_new_machine_empty_first_roles_line_is_not_keep(env, capsys):
    stdin = "\ny\n" + "\n" * 7 + "\nq\n"
    assert env.call([], stdin) == 0
    assert "keeps the current roles" not in capsys.readouterr().err
    assert read(env.path)["gamma"]["roles"] == []


def test_typo_warning(env, capsys):
    env.detected["form"] = "lap-top"
    stdin = "\ny\n" + "\n" * 7 + "q\n"
    assert env.call([], stdin) == 0
    assert "form: `lap-top` is not used by any other machine (typo?)" in capsys.readouterr().err


# ---------------------------------------------------------------- dry-run, writer


def test_dry_run_prints_toml_and_changes_nothing(env, capsys):
    before = env.path.read_text()
    assert env.call(["--noconfirm", "--dry-run"]) == 0
    out = capsys.readouterr()
    assert out.out == "gamma\n"
    assert "[dry-run] would write" in out.err
    assert "[gamma]" in out.err and 'cpu = "intel-cpu"' in out.err
    assert env.path.read_text() == before


def test_writer_round_trip(env):
    text = env.path.read_text()
    attrs = {"form": "desktop", "gpu": ["a-gpu", "b-gpu"], "roles": []}
    new = mi.render(text, "alpha", attrs, tomllib.loads(TOML)["alpha"])
    data = tomllib.loads(new)
    assert data["alpha"] == attrs
    assert data["beta"] == tomllib.loads(TOML)["beta"]
    assert new.startswith(HEADER)
    assert "# comment before beta\n[beta]" in new
    assert 'gpu = "intel-gpu"  # inline comment' in new
    # replacing with the same values gives the same text back
    beta = tomllib.loads(TOML)["beta"]
    assert mi.render(text, "beta", beta, beta) == text
    # appending to an empty file
    assert mi.render("", "x", {"form": "laptop"}, None) == '[x]\nform = "laptop"\n'


def test_write_is_atomic_and_keeps_mode(env):
    env.path.chmod(0o640)
    assert env.call(["--noconfirm"]) == 0
    assert env.path.stat().st_mode & 0o777 == 0o640
    assert not list(env.path.parent.glob(".machines.toml.*"))


def test_missing_file_is_created(env, tmp_path):
    env.path.unlink()
    assert env.call(["--noconfirm"]) == 0
    assert list(read(env.path)) == ["gamma"]


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("bad, msg", [
    ("[a]\nencryption = true\n", r"\[a\] encryption: values must be strings"),
    ("[a]\nnum = 3\n", r"\[a\] num: values must be strings"),
    ("[a]\nsub = { x = \"y\" }\n", r"\[a\] sub: values must be strings"),
    ("[a]\nroles = [\"x\", 1]\n", r"\[a\] roles: values must be strings"),
    ("[a]\nform = \"\"\n", r"\[a\] form: values must be strings"),
    ("[a]\ncpu = \"x\"\ngpu = \"x\"\n", r"\[a\]: class `x` appears twice"),
    ("stray = \"x\"\n", r"`stray` must be a machine table"),
    ("[a\n", r"cannot parse TOML"),
])
def test_validation_errors(env, capsys, bad, msg):
    import re

    env.path.write_text(bad)
    assert env.call(["--noconfirm", "--machine", "a"]) == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert re.search(msg, out.err)


def test_invalid_name_noconfirm(env, capsys):
    assert env.call(["--noconfirm", "--machine", "bad name"]) == 1
    assert "invalid machine name" in capsys.readouterr().err


def test_stdin_closed(env, capsys):
    assert env.call([], "") == 1
    assert "stdin closed" in capsys.readouterr().err


# ---------------------------------------------------------------- detection parsing


def fake_run(table):
    def run(cmd):
        return table.get(" ".join(cmd), (127, ""))
    return run


# Real `bootctl status` output as a normal user (ESP not readable; EFI variables are)
BOOTCTL_STATUS = """systemd-boot not installed in ESP.
No default/fallback boot loader installed in ESP.
System:
      Firmware: n/a (n/a)
 Firmware Arch: x64
   Secure Boot: disabled
  TPM2 Support: yes

Current Boot Loader:
        Product: GRUB 2.14
       Features: \u2717 Boot counting
                 \u2717 Menu timeout control
"""


def test_bootloader_detection(monkeypatch, tmp_path):
    monkeypatch.setenv("MACHINE_INIT_EFIVARS", str(tmp_path / "efivars"))
    monkeypatch.setenv("MACHINE_INIT_GRUB_DIR", str(tmp_path / "grub"))
    # is-installed fails without root and must not be needed
    table = {"bootctl is-installed": (1, ""), "bootctl status": (0, BOOTCTL_STATUS)}
    monkeypatch.setattr(mi, "run", fake_run(table))
    assert mi.detect("bootloader") == "grub"
    assert mi.detect("secureboot") == "none"
    table["bootctl status"] = (0, BOOTCTL_STATUS.replace("GRUB 2.14", "systemd-boot 258.1-1-arch"))
    assert mi.detect("bootloader") == "systemd-boot"
    # bootctl missing: EFI variable LoaderInfo (4-byte attribute header + UTF-16LE)
    table.clear()
    (tmp_path / "efivars").mkdir()
    (tmp_path / "efivars" / mi.LOADER_INFO).write_bytes(b"\x06\0\0\0" + "systemd-boot 258\0".encode("utf-16-le"))
    assert mi.detect("bootloader") == "systemd-boot"
    (tmp_path / "efivars" / mi.LOADER_INFO).write_bytes(b"\x06\0\0\0" + "rEFInd 0.14".encode("utf-16-le"))
    assert mi.detect("bootloader") is None  # unknown loader: no default, no grub guess
    # no EFI information at all: /boot/grub as the last resort
    (tmp_path / "efivars" / mi.LOADER_INFO).unlink()
    assert mi.detect("bootloader") is None
    (tmp_path / "grub").mkdir()
    assert mi.detect("bootloader") == "grub"


def test_detection_parsers(monkeypatch, tmp_path):
    monkeypatch.setattr(mi, "run", fake_run({
        "hostnamectl chassis": (0, "convertible\n"),
        "lspci -nn": (0, "00:02.0 VGA compatible controller [0300]: Intel Corporation Foo [8086:a7a0] (rev 04)\n"
                         "01:00.0 3D controller [0302]: NVIDIA Corporation Bar [10de:28e0] (rev a1)\n"
                         "02:00.0 Audio device [0403]: NVIDIA Corporation Baz [10de:22be]\n"),
        "findmnt -no FSTYPE /": (0, "btrfs\n"),
        "findmnt -no SOURCE /": (0, "/dev/mapper/root[/@]\n"),
        "lsblk -no TYPE -s /dev/mapper/root": (0, "crypt\npart\ndisk\n"),
        "bootctl status": (0, BOOTCTL_STATUS.replace("disabled", "enabled (user)").replace("GRUB 2.14", "systemd-boot 258.1-1-arch")),
    }))
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text("processor\t: 0\nvendor_id\t: AuthenticAMD\n")
    monkeypatch.setenv("MACHINE_INIT_PROC_CPUINFO", str(cpuinfo))
    monkeypatch.setenv("MACHINE_INIT_GRUB_DIR", str(tmp_path / "grub"))
    assert mi.detect("form") == "laptop"
    assert mi.detect("cpu") == "amd-cpu"
    assert mi.detect("gpu") == ["intel-gpu", "nvidia-gpu"]
    assert mi.detect("bootloader") == "systemd-boot"
    assert mi.detect("filesystem") == "btrfs"
    assert mi.detect("encryption") == "luks"
    assert mi.detect("secureboot") == "secureboot"


def test_detection_failures_give_no_default(monkeypatch, tmp_path):
    monkeypatch.setattr(mi, "run", fake_run({
        "hostnamectl chassis": (0, "server\n"),
        "findmnt -no SOURCE /": (0, "/dev/nvme0n1p3\n"),
        "lsblk -no TYPE -s /dev/nvme0n1p3": (0, "part\ndisk\n"),
        "mokutil --sb-state": (0, "SecureBoot disabled\n"),
    }))
    monkeypatch.setenv("MACHINE_INIT_PROC_CPUINFO", str(tmp_path / "nope"))
    monkeypatch.setenv("MACHINE_INIT_GRUB_DIR", str(tmp_path / "nope"))
    assert mi.detect("form") is None
    assert mi.detect("cpu") is None
    assert mi.detect("gpu") is None
    assert mi.detect("bootloader") is None
    assert mi.detect("filesystem") is None
    assert mi.detect("encryption") == "none"
    assert mi.detect("secureboot") == "none"
    assert mi.detect("unknown-key") is None

    def boom():
        raise RuntimeError("x")

    monkeypatch.setitem(mi.DETECTORS, "form", boom)
    assert mi.detect("form") is None


# ---------------------------------------------------------------- minimal editing

EDIT_TOML = """# header
[alpha] # header comment
# leading comment inside alpha
form = "desktop"   # form comment
cpu = "intel-cpu"
gpu = [
    "intel-gpu",  # first
    "nvidia-gpu",
]
old-key = "x"  # to be removed
roles = ["personal"] # roles comment

# trailing comment of alpha

[beta]
form = "laptop"
"""


def test_minimal_edit_keeps_comments(tmp_path):
    old = tomllib.loads(EDIT_TOML)["alpha"]
    new = {"form": "laptop", "cpu": "intel-cpu", "gpu": "nvidia-gpu", "roles": ["personal"], "extra": "foo"}
    out = mi.render(EDIT_TOML, "alpha", new, old)
    assert tomllib.loads(out)["alpha"] == new
    assert out == """# header
[alpha] # header comment
# leading comment inside alpha
form = "laptop"  # form comment
cpu = "intel-cpu"
gpu = "nvidia-gpu"  # first
roles = ["personal"] # roles comment
extra = "foo"

# trailing comment of alpha

[beta]
form = "laptop"
"""


def test_minimal_edit_only_changed_line(env):
    before = env.path.read_text()
    stdin = "\n\n\nintel-gpu, nvidia-gpu\n" + "\n" * 4 + "\n"
    assert env.call(["--machine", "alpha"], stdin) == 0
    after = env.path.read_text()
    diff = [(a, b) for a, b in zip(before.split("\n"), after.split("\n")) if a != b]
    assert diff == [('gpu = "nvidia-gpu"', 'gpu = ["intel-gpu", "nvidia-gpu"]')]


def test_quoted_keys_and_del_escape():
    out = mi.render("", "x", {"odd key": "a\x7fb", "k": ["c"]}, None)
    assert '"odd key" = "a\\u007fb"' in out
    assert "\x7f" not in out
    assert tomllib.loads(out)["x"] == {"odd key": "a\x7fb", "k": ["c"]}
    # quoted keys are found again when editing
    out2 = mi.render(out, "x", {"odd key": "z", "k": ["c"]}, tomllib.loads(out)["x"])
    assert tomllib.loads(out2)["x"] == {"odd key": "z", "k": ["c"]}


def test_crlf_is_read(tmp_path):
    text = '[a]\r\nform = "laptop"\r\n'
    out = mi.render(text, "a", {"form": "desktop"}, {"form": "laptop"})
    assert tomllib.loads(out)["a"] == {"form": "desktop"}


def test_reparse_failure_is_init_error(env, capsys, monkeypatch):
    monkeypatch.setattr(mi, "render", lambda *a: "[broken\n")
    assert env.call(["--noconfirm"]) == 1
    err = capsys.readouterr().err
    assert "would not parse" in err and "Traceback" not in err


# ---------------------------------------------------------------- names, stdin, Ctrl-C


@pytest.mark.parametrize("bad, msg", [
    ("[a_b]\nform = \"x\"\n", r"invalid machine name `a_b`"),
    ("[a]\ncpu = \"intel_cpu\"\n", r"invalid class name `intel_cpu`"),
    ("[a]\ncpu = \"-x\"\n", r"invalid class name `-x`"),
    ("[a]\nroles = [\"" + "y" * 64 + "\"]\n", r"invalid class name"),
])
def test_name_rule_in_file(env, capsys, bad, msg):
    import re

    env.path.write_text(bad)
    assert env.call(["--noconfirm", "--machine", "a"]) == 1
    assert re.search(msg, capsys.readouterr().err)


def test_name_rule_in_prompts(env, capsys):
    # hostname with "_" and trailing "-" re-asked; class with "_" re-asked; role skipped
    stdin = "a_b\nab-\nab\ny\nlap_top\nlaptop\n" + "\n" * 6 + "bad_role good\nq\n"
    assert env.call([], stdin) == 0
    err = capsys.readouterr().err
    assert "Invalid name `a_b`" in err and "Invalid name `ab-`" in err
    assert "Invalid class name `lap_top`" in err
    assert "`bad_role` skipped (invalid" in err
    data = read(env.path)["ab"]
    assert data["form"] == "laptop" and data["roles"] == ["good"]


def test_class_equal_to_machine_name_allowed(env, capsys):
    stdin = "\ny\nbeta\n" + "\n" * 6 + "q\n"
    assert env.call([], stdin) == 0
    err = capsys.readouterr().err
    assert read(env.path)["gamma"]["form"] == "beta"
    assert "Invalid" not in err


def test_closed_stdin(env, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert mi.main([]) == 1
    err = capsys.readouterr().err
    assert "no input" in err and "Traceback" not in err


def test_keyboard_interrupt(env, capsys, monkeypatch):
    before = env.path.read_text()

    def interrupt(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(mi, "read_line", interrupt)
    assert mi.main([]) == 130
    out = capsys.readouterr()
    assert out.out == ""
    assert "interrupted; nothing was written" in out.err
    assert env.path.read_text() == before


def test_closed_stdin_subprocess(tmp_path):
    import subprocess

    (tmp_path / "m.toml").write_text('[a]\nform = "x"\n')
    res = subprocess.run(
        ["bash", "-c", f'exec python3 "{SCRIPT}" --file "{tmp_path}/m.toml" --machine a <&-'],
        capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert res.returncode == 1
    assert "no input" in res.stderr and "Traceback" not in res.stderr
