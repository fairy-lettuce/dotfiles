"""テスト共通: 実 ~/.pacman・machines.toml・yadm・flatpak に一切触らない環境を作る。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

MACHINES_TOML = """
[ruan]
form = "desktop"
cpu = "intel-cpu"
gpu = "nvidia-gpu"
bootloader = "grub"
filesystem = "ext4"
encryption = "none"
secureboot = "none"
roles = ["personal", "gaming", "dualboot"]

[tribios]
form = "laptop"
cpu = "intel-cpu"
gpu = "intel-gpu"
bootloader = "systemd-boot"
filesystem = "btrfs"
encryption = "luks"
secureboot = "secureboot"
roles = ["work", "touch"]
"""


class Env:
    def __init__(self, root: Path, monkeypatch):
        self.root = root
        self.pacman = root / "pacman"
        self.pacman.mkdir()
        self.state = root / "state"
        self.flatpak: set[str] = set()
        (root / "machines.toml").write_text(MACHINES_TOML)
        (root / "yadmcfg").write_text("[local]\n\thostname = ruan\n")
        monkeypatch.setenv("PKGNOTE_PACMAN_DIR", str(self.pacman))
        monkeypatch.setenv("PKGNOTE_MACHINES_FILE", str(root / "machines.toml"))
        monkeypatch.setenv("PKGNOTE_YADM_CONFIG", str(root / "yadmcfg"))
        monkeypatch.setenv("PKGNOTE_STATE_DIR", str(self.state))
        from pkgnote import backends

        self.native: set[str] = set()
        self.foreign: set[str] = set()
        # システムへの問い合わせ(pacman -Q / flatpak list)はすべてモックする
        monkeypatch.setattr(backends, "installed_pacman", lambda: set(self.native))
        monkeypatch.setattr(backends, "installed_foreign", lambda: set(self.foreign))
        monkeypatch.setattr(backends, "installed_flatpak", lambda: set(self.flatpak))
        # provides / 依存の判定(pacman -T / -Qq / -Qi)もモック。
        # deps: その名前で依存として入っているもの。infos: インストール済みの PkgInfo。
        self.deps: set[str] = set()
        self.infos: list = []

        def unsatisfied(names):
            provided = {n for i in self.infos for n in i.provides} | {i.name for i in self.infos}
            return set(names) - self.deps - provided

        monkeypatch.setattr(backends, "unsatisfied", unsatisfied)
        monkeypatch.setattr(backends, "installed_any", lambda names: set(names) & self.deps)
        monkeypatch.setattr(backends, "installed_info", lambda: list(self.infos))

        def no_exec(cmd):
            raise AssertionError(f"テスト中にコマンドを実行しようとした: {cmd}")

        monkeypatch.setattr(backends, "run_command", no_exec)
        # AUR ヘルパーの有無は実機に依存させない(既定はあることにする)
        monkeypatch.setattr(backends, "command_available", lambda _name: True)

    @property
    def kdl_path(self) -> Path:
        return self.pacman / "packages.kdl"

    def write_kdl(self, text: str) -> None:
        self.kdl_path.write_text(textwrap.dedent(text))

    def read_kdl(self) -> str:
        return self.kdl_path.read_text()

    def set_installed(self, pacman=(), foreign=(), flatpak=()) -> None:
        self.native = set(pacman)
        self.foreign = set(foreign)
        self.flatpak = set(flatpak)


@pytest.fixture
def env(tmp_path, monkeypatch):
    from pkgnote import term

    term.configure("never")
    return Env(tmp_path, monkeypatch)
