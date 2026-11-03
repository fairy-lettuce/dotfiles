import pytest

from pkgnote import backends
from pkgnote.backends import install_command
from pkgnote.cli import main


def test_default_has_no_noconfirm_and_uses_paru():
    assert install_command("pacman", ["b", "a"]) == ["sudo", "pacman", "-S", "--needed", "a", "b"]
    assert install_command("foreign", ["x"]) == ["paru", "-S", "--needed", "x"]
    assert install_command("flatpak", ["org.A"]) == ["flatpak", "install", "org.A"]


def test_noconfirm_and_aur_helper():
    assert install_command("pacman", ["a"], noconfirm=True) == [
        "sudo", "pacman", "-S", "--needed", "--noconfirm", "a",
    ]
    assert install_command("foreign", ["x"], aur_helper="yay", noconfirm=True) == [
        "yay", "-S", "--needed", "--noconfirm", "x",
    ]
    assert install_command("flatpak", ["org.A"], noconfirm=True) == ["flatpak", "install", "-y", "org.A"]
    assert install_command("pacman", []) is None


KDL = """
base {
    package "vim"
    package "brave-bin" from="foreign"
    package "org.A" from="flatpak"
}
laptop install-if="laptop" {
    package "tlp"
}
"""


def test_cli_dry_run_prints_commands(env, capsys):
    env.write_kdl(KDL)
    env.set_installed()
    assert main(["deploy", "--dry-run", "--aur-helper", "yay"]) == 0
    out = capsys.readouterr().out
    assert "$ sudo pacman -S --needed vim" in out
    assert "$ yay -S --needed brave-bin" in out
    assert "$ flatpak install org.A" in out
    assert "tlp" not in out
    (env.root / "yadmcfg").write_text("[local]\n\thostname = tribios\n")
    assert main(["deploy", "--dry-run", "--noconfirm"]) == 0
    out = capsys.readouterr().out
    assert "$ sudo pacman -S --needed --noconfirm tlp vim" in out
    assert "$ paru -S --needed --noconfirm brave-bin" in out
    assert "$ flatpak install -y org.A" in out


def test_cli_runs_mocked_backend(env, monkeypatch, capsys):
    env.write_kdl(KDL)
    env.set_installed(pacman=["vim"], flatpak=["org.A"])
    ran = []
    monkeypatch.setattr(backends, "run_command", lambda cmd: ran.append(cmd) or 0)
    assert main(["deploy", "--backend", "foreign"]) == 0
    assert ran == [["paru", "-S", "--needed", "brave-bin"]]


def test_cli_missing_aur_helper_skips_foreign(env, monkeypatch, capsys):
    env.write_kdl(KDL)
    env.set_installed(flatpak=["org.A"])
    ran = []
    monkeypatch.setattr(backends, "run_command", lambda cmd: ran.append(cmd) or 0)
    monkeypatch.setattr(backends, "command_available", lambda name: name != "paru")
    assert main(["deploy"]) == 1
    assert ran == [["sudo", "pacman", "-S", "--needed", "vim"]]
    assert "AUR ヘルパー `paru` が見つかりません" in capsys.readouterr().out
    # dry-run でも知らせる(終了コードは 0 のまま)
    assert main(["deploy", "--dry-run"]) == 0
    assert "`paru` が見つかりません" in capsys.readouterr().out


def test_cli_nothing_to_do(env, capsys):
    env.write_kdl(KDL)
    env.set_installed(pacman=["vim"], foreign=["brave-bin"], flatpak=["org.A"])
    assert main(["deploy"]) == 0
    assert "導入対象なし" in capsys.readouterr().out


@pytest.mark.parametrize("cmd", [["compress"], ["status", "--host", "ruan"]])
def test_removed_options(env, cmd):
    with pytest.raises(SystemExit):
        main(cmd)


def test_deploy_for_other_machine_refused(env, capsys):
    env.write_kdl(KDL)
    env.set_installed()
    assert main(["deploy", "--dry-run", "--machine", "tribios"]) == 1
    assert "現在のマシン(ruan)ではありません" in capsys.readouterr().err
    # status は他マシンも可
    assert main(["status", "--machine", "tribios"]) == 0


class _Res:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_query_distinguishes_failure_from_empty(monkeypatch):
    from pkgnote.backends import BackendError

    def fake(rc, out="", err=""):
        monkeypatch.setattr(backends.subprocess, "run", lambda *a, **k: _Res(rc, out, err))

    fake(0, "a\nb\n")
    assert backends.installed_foreign() == {"a", "b"}
    fake(1)  # pacman -Qqm で該当 0 件
    assert backends.installed_foreign() == set()
    fake(1, err="error: could not open database")
    with pytest.raises(BackendError, match="could not open database"):
        backends.installed_foreign()
    fake(0, "")
    with pytest.raises(BackendError, match="空"):
        backends.installed_pacman()

    def oserror(*a, **k):
        raise OSError("no pacman")

    monkeypatch.setattr(backends.subprocess, "run", oserror)
    with pytest.raises(BackendError):
        backends.installed_foreign()


def test_flatpak_missing_is_empty_but_failure_is_error(monkeypatch):
    from pkgnote.backends import BackendError

    monkeypatch.setattr(backends.shutil, "which", lambda _: None)
    assert backends.installed_flatpak() == set()
    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/flatpak")
    monkeypatch.setattr(backends.subprocess, "run", lambda *a, **k: _Res(2, err="boom"))
    with pytest.raises(BackendError):
        backends.installed_flatpak()


# ---------------------------------------------------------------- provides / dependency

PROVIDES_KDL = """
base {
    package "vim"
    package "paru" from="foreign"
    package "dotnet-sdk"
    package "libfoo"
    package "org.A" from="flatpak"
}
"""

# real `LC_ALL=C pacman -Qi` format (abridged), incl. versioned provides/conflicts
QI = """Name            : paru-bin
Version         : 2.1.0-1
Description     : Feature packed AUR helper
Architecture    : x86_64
URL             : https://github.com/morganamilo/paru
Licenses        : GPL-3.0-or-later
Groups          : None
Provides        : paru=2.1.0
Depends On      : git  pacman
Optional Deps   : bat: colored pkgbuild printing
                  devtools: build in chroot and downloading pkgbuilds
Required By     : None
Optional For    : None
Conflicts With  : paru
Replaces        : None
Installed Size  : 9.06 MiB
Install Reason  : Explicitly installed

Name            : dotnet-sdk-9.0-bin
Version         : 9.0.300-1
Description     : The .NET Core SDK version 9.0
Architecture    : x86_64
Provides        : dotnet-sdk=9.0  dotnet-sdk-9.0
Depends On      : dotnet-runtime-9.0-bin
Conflicts With  : dotnet-sdk-9.0
Replaces        : None
Install Reason  : Explicitly installed

Name            : neovim-git
Version         : 0.12-1
Provides        : neovim=0.12  vim-plugin-runtime
Conflicts With  : neovim>=0.10
Replaces        : vim<9
Install Reason  : Explicitly installed

Name            : pacman
Version         : 7.1.0-3
Provides        : libalpm.so=16-64
Conflicts With  : None
Replaces        : None
"""


def test_parse_qi_real_format():
    infos = {i.name: i for i in backends.parse_qi(QI)}
    assert infos["paru-bin"].provides == {"paru"} and infos["paru-bin"].conflicts == {"paru"}
    assert infos["dotnet-sdk-9.0-bin"].provides == {"dotnet-sdk", "dotnet-sdk-9.0"}
    assert infos["dotnet-sdk-9.0-bin"].conflicts == {"dotnet-sdk-9.0"}
    assert infos["neovim-git"].conflicts == {"neovim"} and infos["neovim-git"].replaces == {"vim"}
    assert infos["pacman"].conflicts == frozenset() and infos["pacman"].provides == {"libalpm.so"}


def test_classify_requires_provides_and_conflicts(env):
    env.infos = backends.parse_qi(QI)
    env.deps = {"libfoo"}
    sat = backends.classify({"paru", "dotnet-sdk", "libfoo", "vim", "neovim"}, explicit={"paru-bin"})
    assert sat.provided == {"paru": "paru-bin", "neovim": "neovim-git"}
    assert sat.as_dependency == {"libfoo"}
    assert sat.missing == {"dotnet-sdk", "vim"}  # provides only (no conflict) -> still needed


def test_classify_replaces_counts(env):
    env.infos = backends.parse_qi(QI)
    # neovim-git provides vim-plugin-runtime but neither conflicts nor replaces it
    sat = backends.classify({"vim-plugin-runtime"}, explicit=set())
    assert sat.missing == {"vim-plugin-runtime"}


def test_deploy_skips_provided_and_dependency(env, capsys):
    env.write_kdl(PROVIDES_KDL)
    env.set_installed(foreign=["paru-bin"], pacman=["dotnet-sdk-9.0-bin"])
    env.infos = backends.parse_qi(QI)
    env.deps = {"libfoo"}
    assert main(["deploy", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "$ sudo pacman -S --needed dotnet-sdk vim" in out
    assert "paru -S" not in out
    assert "paru: paru-bin で導入済み" in out
    assert "依存として導入済み(導入はしない): libfoo" in out
    assert "sudo pacman -D --asexplicit -- libfoo" in out
    assert "$ flatpak install org.A" in out


def test_deploy_nothing_when_all_satisfied(env, capsys):
    env.write_kdl(PROVIDES_KDL)
    env.set_installed(pacman=["vim", "dotnet-sdk"], foreign=["paru-bin"], flatpak=["org.A"])
    env.infos = backends.parse_qi(QI)
    env.deps = {"libfoo"}
    assert main(["deploy"]) == 0
    out = capsys.readouterr().out
    assert "導入対象なし" in out and "--asexplicit -- libfoo" in out


def test_status_provided_and_dependency(env, capsys):
    env.write_kdl(PROVIDES_KDL)
    env.set_installed(pacman=["vim"], foreign=["paru-bin"], flatpak=["org.A"])
    env.infos = backends.parse_qi(QI)
    env.deps = {"libfoo"}
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "PROVIDED" in out and "paru-bin が provides" in out
    assert "DEPENDENCY" in out and "sudo pacman -D --asexplicit -- libfoo" in out
    assert "MISSING=1" in out  # dotnet-sdk: provides only, no conflict
    assert "dotnet-sdk" in out.split("MISSING")[1]


def test_unsatisfied_and_installed_any_parse_pacman(monkeypatch):
    from pkgnote.backends import BackendError

    calls = []

    def fake(rc, out="", err=""):
        def run(cmd, **k):
            calls.append(cmd)
            assert k["env"]["LC_ALL"] == "C"
            return _Res(rc, out, err)
        monkeypatch.setattr(backends.subprocess, "run", run)

    fake(0)
    assert backends.unsatisfied(["paru", "vim"]) == set()
    assert calls[-1] == ["pacman", "-T", "--", "paru", "vim"]
    fake(127, "vim\n")
    assert backends.unsatisfied(["paru", "vim"]) == {"vim"}
    calls.clear()
    assert backends.unsatisfied([]) == set() and calls == []
    fake(1, err="error: something broke")
    with pytest.raises(BackendError, match="something broke"):
        backends.unsatisfied(["x"])

    fake(1, "libfoo\n", "error: package 'zz' was not found\n")
    assert backends.installed_any(["libfoo", "zz"]) == {"libfoo"}
    assert calls[-1] == ["pacman", "-Qq", "--", "libfoo", "zz"]
    fake(0, "a\nb\n")
    assert backends.installed_any(["a", "b"]) == {"a", "b"}
    fake(1, "", "error: could not open database\n")
    with pytest.raises(BackendError, match="could not open database"):
        backends.installed_any(["a"])

    fake(0, QI)
    assert [i.name for i in backends.installed_info()][:2] == ["paru-bin", "dotnet-sdk-9.0-bin"]
    assert calls[-1] == ["pacman", "-Qi"]
    fake(1, err="error: boom")
    with pytest.raises(BackendError):
        backends.installed_info()

    def oserror(*a, **k):
        raise OSError("no pacman")

    monkeypatch.setattr(backends.subprocess, "run", oserror)
    with pytest.raises(BackendError):
        backends.unsatisfied(["x"])


def test_installed_any_ignores_provider_fallback(monkeypatch):
    """pacman 7.1: `-Qq -- sh libgl` prints the providers (bash, libglvnd), not the names."""
    monkeypatch.setattr(backends.subprocess, "run", lambda *a, **k: _Res(0, "bash\nlibglvnd\n"))
    assert backends.installed_any(["sh", "libgl"]) == set()
    monkeypatch.setattr(backends.subprocess, "run",
                        lambda *a, **k: _Res(1, "libfoo\nbash\n", "error: package 'zz' was not found\n"))
    assert backends.installed_any(["libfoo", "sh", "zz"]) == {"libfoo"}


def test_status_and_deploy_survive_unexpected_names(env, monkeypatch, capsys):
    env.write_kdl(PROVIDES_KDL)
    env.set_installed(pacman=["vim"], foreign=["paru-bin"], flatpak=["org.A"])
    env.infos = backends.parse_qi(QI)
    env.deps = {"libfoo"}
    # a misbehaving query returning names that were not asked for must not leak through
    monkeypatch.setattr(backends, "installed_any", lambda names: set(names) & {"libfoo"} | {"bash"})
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "bash" not in out and "libfoo" in out
    assert main(["deploy", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "--asexplicit -- libfoo" in out and "bash" not in out
