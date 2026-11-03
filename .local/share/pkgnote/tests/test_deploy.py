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
