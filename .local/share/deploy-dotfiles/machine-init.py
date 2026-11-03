#!/usr/bin/env python3
"""Add or update this machine in ~/.config/machines.toml (called by deploy-dotfiles.sh).

Usage: machine-init.py [--noconfirm] [--machine NAME] [--dry-run] [--file PATH]

On success, prints ONLY the logical name on stdout; prompts and messages go
to stderr. Stdlib only (runs with the system python3 before uv exists).

Format (shared with pkgnote): each machine is a table; keys are labels only.
Every string value, and every element of a list value, is used verbatim as a
class name, except "none" (no class). Booleans, numbers and nested tables are
errors, and so is the same class twice in one machine. The file is public.

Detection for new machines is read-only and needs no root; a detection that
fails just gives no default. MACHINE_INIT_PROC_CPUINFO, MACHINE_INIT_EFIVARS
and MACHINE_INIT_GRUB_DIR override /proc/cpuinfo, /sys/firmware/efi/efivars and
/boot/grub (for tests).

Machine names and class names follow the hostname label rule (RFC 1123):
letters, digits and '-', no leading/trailing '-', 1-63 characters.

Editing an existing table is minimal: only the lines of changed keys are
replaced (keeping their inline comment), new keys are appended to the table,
removed keys are deleted; all other lines and comments are kept.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

NONE_VALUE = "none"
BASE_KEYS = ["form", "cpu", "gpu", "bootloader", "filesystem", "encryption", "secureboot"]
ROLES_KEY = "roles"
# Logical machine names and class names (hostname label, RFC 1123).
NAME_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
NAME_RULE = "letters, digits and '-', no leading/trailing '-', 1-63 characters"
BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
HEADER_RE = re.compile(r"^\s*\[\s*([A-Za-z0-9_-]+)\s*\]\s*(#.*)?$")
KEY_LINE_RE = re.compile(r'^(\s*)([A-Za-z0-9_-]+|"(?:[^"\\]|\\.)*")(\s*=\s*)(.*)$')
LOADER_INFO = "LoaderInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"


class InitError(Exception):
    pass


# ---------------------------------------------------------------- I/O


def err(msg: str = "") -> None:
    print(msg, file=sys.stderr, flush=True)


def bold(text: str) -> str:
    if sys.stderr.isatty():
        return f"\033[1m{text}\033[0m"
    return f"**{text}**"


def _readline() -> str:
    """One line from stdin without read-ahead.

    The caller (deploy-dotfiles.sh) keeps reading the same stdin after this
    script exits, so buffered reads would swallow its answers.
    """
    if sys.stdin is None:  # stdin closed (<&-)
        raise InitError("no input (stdin is closed)")
    if sys.stdin is not sys.__stdin__:
        return sys.stdin.readline()  # replaced stdin (tests)
    buf = b""
    while True:
        try:
            c = os.read(0, 1)
        except OSError as exc:
            raise InitError(f"no input (cannot read stdin: {exc.strerror})") from exc
        if not c:
            break
        buf += c
        if c == b"\n":
            break
    return buf.decode(errors="replace")


def read_line(prompt: str) -> str:
    sys.stderr.write(prompt)
    sys.stderr.flush()
    line = _readline()
    if not line:
        raise InitError("no input (stdin closed)")
    return line.strip()


# ---------------------------------------------------------------- format


def classes_of(name: str, attrs: dict) -> list[str]:
    """Classes of one machine; raises InitError on an invalid table."""
    out: list[str] = []
    for key, value in attrs.items():
        for v in value if isinstance(value, list) else [value]:
            if not isinstance(v, str) or not v.strip():
                raise InitError(
                    f"[{name}] {key}: values must be strings or lists of strings (got {v!r}); "
                    f'write "{NONE_VALUE}" for "not present"'
                )
            if v == NONE_VALUE:
                continue
            if not NAME_RE.match(v):
                raise InitError(f"[{name}] {key}: invalid class name `{v}` ({NAME_RULE})")
            if v in out:
                raise InitError(f"[{name}]: class `{v}` appears twice ({key})")
            out.append(v)
    return out


def load(path: Path) -> tuple[str, dict[str, dict]]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise InitError(f"{path}: cannot parse TOML: {exc}") from exc
    for name, attrs in data.items():
        if not isinstance(attrs, dict):
            raise InitError(f"{path}: `{name}` must be a machine table (`[{name}]`)")
        if not NAME_RE.match(name):
            raise InitError(f"{path}: invalid machine name `{name}` ({NAME_RULE})")
        classes_of(name, attrs)
    return text, data


def format_string(v: str) -> str:
    # JSON string escapes are valid TOML basic-string escapes; TOML also forbids raw DEL.
    return json.dumps(v, ensure_ascii=False).replace("\x7f", "\\u007f")


def format_key(k: str) -> str:
    return k if BARE_KEY_RE.match(k) else format_string(k)


def format_value(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(format_string(v) for v in value) + "]"
    return format_string(value)


def format_table(name: str, attrs: dict) -> list[str]:
    return [f"[{name}]"] + [f"{format_key(k)} = {format_value(v)}" for k, v in attrs.items()]


def _scan(text: str, depth: int) -> tuple[int, int | None]:
    """Track [] depth through one line of a TOML value; returns (depth, comment start)."""
    i, quote = 0, None
    while i < len(text):
        c = text[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#":
            return depth, i
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        i += 1
    return depth, None


def _key_spans(lines: list[str], start: int, end: int) -> dict[str, tuple[int, int, str]]:
    """{key: (first line, last line + 1, inline comment)} for the key lines in [start, end)."""
    spans = {}
    i = start
    while i < end:
        m = KEY_LINE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        raw = m.group(2)
        key = json.loads(raw) if raw.startswith('"') else raw
        depth, cpos = _scan(m.group(4), 0)
        comment = m.group(4)[cpos:] if cpos is not None else ""
        j = i + 1
        while depth > 0 and j < end:
            depth, cpos = _scan(lines[j], depth)
            if cpos is not None and not comment:
                comment = lines[j][cpos:]
            j += 1
        spans[key] = (i, j, comment)
        i = j
    return spans


def render(text: str, name: str, attrs: dict, old: dict | None) -> str:
    """Return the file text with [name] updated minimally (or appended).

    Everything outside the changed key lines is kept verbatim, comments included.
    """
    if old == attrs and old is not None:
        return text
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    starts = [i for i, line in enumerate(lines) if HEADER_RE.match(line)]
    found = [i for i in starts if HEADER_RE.match(lines[i]).group(1) == name]
    if not found:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines += format_table(name, attrs)
        return "\n".join(lines) + "\n"

    start = found[0]
    end = next((i for i in starts if i > start), len(lines))
    spans = _key_spans(lines, start + 1, end)
    edits: list[tuple[int, int, list[str]]] = []
    for key, (a, b, comment) in spans.items():
        if key not in attrs:
            edits.append((a, b, []))
        elif (old or {}).get(key) != attrs[key]:
            m = KEY_LINE_RE.match(lines[a])
            line = f"{m.group(1)}{m.group(2)}{m.group(3)}{format_value(attrs[key])}"
            edits.append((a, b, [f"{line}  {comment}" if comment else line]))
    new_keys = [f"{format_key(k)} = {format_value(v)}" for k, v in attrs.items() if k not in spans]
    if new_keys:
        last = max((b for (_, b, _) in spans.values()), default=start + 1)
        edits.append((last, last, new_keys))
    for a, b, repl in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        lines[a:b] = repl
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------- detection


def run(cmd: list[str]) -> tuple[int, str]:
    """Run a read-only command; (returncode, stdout). Missing command -> (127, "")."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return res.returncode, res.stdout


def detect_hostname() -> str:
    rc, out = run(["hostnamectl", "hostname"])
    return out.strip() if rc == 0 and out.strip() else socket.gethostname()


def detect_form() -> str | None:
    rc, out = run(["hostnamectl", "chassis"])
    chassis = out.strip().lower() if rc == 0 else ""
    if chassis in ("laptop", "notebook", "convertible"):
        return "laptop"
    if chassis in ("desktop", "tower"):
        return "desktop"
    return None


def detect_cpu() -> str | None:
    path = os.environ.get("MACHINE_INIT_PROC_CPUINFO", "/proc/cpuinfo")
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return None
    m = re.search(r"^vendor_id\s*:\s*(\S+)", text, re.M)
    return {"GenuineIntel": "intel-cpu", "AuthenticAMD": "amd-cpu"}.get(m.group(1)) if m else None


GPU_VENDORS = {"8086": "intel-gpu", "10de": "nvidia-gpu", "1002": "amd-gpu"}


def detect_gpu() -> list[str]:
    rc, out = run(["lspci", "-nn"])
    if rc != 0:
        return []
    found: list[str] = []
    for line in out.splitlines():
        if not re.search(r"\[(0300|0302|0380)\]", line):
            continue
        ids = re.findall(r"\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]", line)
        if ids:
            cls = GPU_VENDORS.get(ids[-1][0].lower())
            if cls and cls not in found:
                found.append(cls)
    return found


def _loader_product() -> str | None:
    """Current boot loader from EFI variables (no root needed)."""
    rc, out = run(["bootctl", "status"])
    m = re.search(r"^Current Boot Loader:\s*\n\s*Product:\s*(.+)$", out, re.M)
    if m:
        return m.group(1).strip()
    efivars = Path(os.environ.get("MACHINE_INIT_EFIVARS", "/sys/firmware/efi/efivars"))
    try:
        raw = (efivars / LOADER_INFO).read_bytes()[4:]  # skip the attribute header
    except OSError:
        return None
    return raw.decode("utf-16-le", errors="replace").rstrip("\x00").strip() or None


def detect_bootloader() -> str | None:
    product = (_loader_product() or "").lower()
    if product.startswith("systemd-boot"):
        return "systemd-boot"
    if product.startswith("grub"):
        return "grub"
    if not product and Path(os.environ.get("MACHINE_INIT_GRUB_DIR", "/boot/grub")).is_dir():
        return "grub"  # last resort (e.g. legacy BIOS boot: no EFI variables)
    return None


def detect_filesystem() -> str | None:
    rc, out = run(["findmnt", "-no", "FSTYPE", "/"])
    return (out.strip() or None) if rc == 0 else None


def detect_encryption() -> str | None:
    rc, out = run(["findmnt", "-no", "SOURCE", "/"])
    source = re.sub(r"\[.*\]$", "", out.strip()) if rc == 0 else ""
    if not source:
        return None
    rc, out = run(["lsblk", "-no", "TYPE", "-s", source])
    if rc != 0 or not out.strip():
        return None
    return "luks" if "crypt" in out.split() else NONE_VALUE


def detect_secureboot() -> str | None:
    rc, out = run(["bootctl", "status"])
    m = re.search(r"Secure Boot:\s*(\w+)", out)
    if m:
        return "secureboot" if m.group(1).lower() == "enabled" else NONE_VALUE
    rc, out = run(["mokutil", "--sb-state"])
    if rc == 0 and "SecureBoot" in out:
        return "secureboot" if "enabled" in out.lower() else NONE_VALUE
    return None


DETECTORS = {
    "form": detect_form,
    "cpu": detect_cpu,
    "gpu": detect_gpu,
    "bootloader": detect_bootloader,
    "filesystem": detect_filesystem,
    "encryption": detect_encryption,
    "secureboot": detect_secureboot,
}


def detect(key: str):
    """Detected default for key: str, list (several GPUs) or None."""
    fn = DETECTORS.get(key)
    if fn is None:
        return None
    try:
        value = fn()
    except Exception:  # noqa: BLE001 - a failing detection just gives no default
        return None
    if isinstance(value, list):
        return None if not value else value[0] if len(value) == 1 else value
    return value


# ---------------------------------------------------------------- prompts


def show(value) -> str:
    return ", ".join(value) if isinstance(value, list) else str(value)


def parse_values(text: str):
    items = [v.strip() for v in text.split(",") if v.strip()]
    return items[0] if len(items) == 1 else items


def as_list(value) -> list[str]:
    return value if isinstance(value, list) else [value]


def warn_unused(key: str, value, other_classes: set[str]) -> None:
    for v in as_list(value):
        if v != NONE_VALUE and v not in other_classes:
            err(f"  [WARN] {key}: `{v}` is not used by any other machine (typo?)")


def ask_name(default: str, machines: dict) -> str:
    while True:
        name = read_line(f"{bold('hostname')} (default: {default}): ") or default
        if not NAME_RE.match(name):
            err(f"  Invalid name `{name}`: {NAME_RULE}.")
            continue
        if name in machines:
            return name
        err(f"  [WARNING] `{name}` is a new machine. This name will be PUBLIC on GitHub")
        err("  (machines.toml is published with the dotfiles; it must not contain a company name).")
        while True:
            ans = read_line(f"  Use `{name}` as the public name of this machine? [y/n]: ").lower()
            if ans in ("y", "n"):
                break
        if ans == "y":
            return name


def ask_value(key: str, default, taken: list[str], other_classes: set[str]):
    while True:
        hint = f" (default: {show(default)})" if default is not None else ""
        text = read_line(f"{bold(key)}{hint}: ")
        if not text:
            if default is None:
                err(f'  Enter a value (or "{NONE_VALUE}").')
                continue
            value = default
        else:
            value = parse_values(text)
            if value == []:
                continue
        bad = [v for v in as_list(value) if v != NONE_VALUE and not NAME_RE.match(v)]
        if bad:
            err(f"  Invalid class name `{bad[0]}`: {NAME_RULE}.")
            continue
        dup = [v for v in as_list(value) if v != NONE_VALUE and (v in taken or as_list(value).count(v) > 1)]
        if dup:
            err(f"  `{dup[0]}` is already used as a class of this machine; choose another value.")
            continue
        warn_unused(key, value, other_classes)
        return value


def ask_roles(existing: list[str] | None, taken: list[str], all_roles: list[str], other_classes: set[str]):
    err(f'{bold(ROLES_KEY)}: Input roles for this machine. Press "q" to end. Press "ls" to list existing roles.')
    if existing is not None:
        err(f"  (Enter on an empty first line keeps the current roles: {show(existing) or '(none)'})")
    roles: list[str] = []
    first = True
    while True:
        text = read_line("> ")
        if first and not text and existing is not None:
            return list(existing)
        first = False
        if text == "q":
            return roles
        if text == "ls":
            err("  roles used by machines: " + (", ".join(all_roles) or "(none)"))
            continue
        for role in re.split(r"[,\s]+", text):
            if not role:
                continue
            if not NAME_RE.match(role):
                err(f"  `{role}` skipped (invalid: {NAME_RULE})")
                continue
            if role == NONE_VALUE or role in roles or role in taken:
                err(f"  `{role}` skipped (duplicate or reserved)")
                continue
            warn_unused(ROLES_KEY, role, other_classes)
            roles.append(role)


# ---------------------------------------------------------------- main


def machines_file() -> Path:
    env = os.environ.get("PKGNOTE_MACHINES_FILE")
    return Path(env) if env else Path.home() / ".config" / "machines.toml"


def all_keys(machines: dict) -> list[str]:
    keys = list(BASE_KEYS)
    for attrs in machines.values():
        for k in attrs:
            if k not in keys and k != ROLES_KEY:
                keys.append(k)
    return keys


def build(name: str, machines: dict, noconfirm: bool) -> dict:
    current = machines.get(name)
    others = {n: a for n, a in machines.items() if n != name}
    other_classes = {c for n, a in others.items() for c in classes_of(n, a)}
    all_roles: list[str] = []
    for attrs in machines.values():
        for r in as_list(attrs.get(ROLES_KEY, [])):
            if r not in all_roles:
                all_roles.append(r)

    def default_for(key):
        if current is not None and key in current:
            return current[key]
        return detect(key)

    if noconfirm:
        if current is not None:
            return dict(current)
        attrs, missing = {}, []
        for key in all_keys(machines):
            value = detect(key)
            if value is None:
                missing.append(key)
            else:
                attrs[key] = value
        attrs[ROLES_KEY] = []
        if missing:
            err(f"  [WARN] not detected (left out): {', '.join(missing)}")
        return attrs

    attrs: dict = {}
    taken: list[str] = []
    for key in all_keys(machines):
        default = default_for(key)
        if key == "gpu" and isinstance(default, list) and current is None:
            err(f"  Several GPUs detected: {show(default)} (Enter keeps all; comma-separate to choose)")
        value = ask_value(key, default, taken, other_classes)
        attrs[key] = value
        taken += [v for v in as_list(value) if v != NONE_VALUE]
    existing_roles = None if current is None else as_list(current.get(ROLES_KEY, []))
    attrs[ROLES_KEY] = ask_roles(existing_roles, taken, all_roles, other_classes)
    # keep keys the existing table has but we did not ask (none today; future-proof)
    if current is not None:
        for k, v in current.items():
            attrs.setdefault(k, v)
    return attrs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Add or update this machine in machines.toml")
    ap.add_argument("--noconfirm", action="store_true", help="no prompts; keep or detect values")
    ap.add_argument("--machine", metavar="NAME", help="logical name (default: current hostname)")
    ap.add_argument("--dry-run", action="store_true", help="print the TOML that would be written")
    ap.add_argument("--file", type=Path, help="machines.toml (default: $PKGNOTE_MACHINES_FILE or ~/.config/machines.toml)")
    args = ap.parse_args(argv)
    path = args.file or machines_file()
    try:
        text, machines = load(path)
        default_name = args.machine or detect_hostname()
        if args.noconfirm:
            if not NAME_RE.match(default_name):
                raise InitError(f"invalid machine name `{default_name}` ({NAME_RULE})")
            name = default_name
        else:
            err("Setting classes for this machine...")
            name = ask_name(default_name, machines)
        attrs = build(name, machines, args.noconfirm)
        classes_of(name, attrs)
        new_text = render(text, name, attrs, machines.get(name))
        expected = dict(machines)
        expected[name] = attrs
        try:
            reparsed = tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            raise InitError(f"{path}: the updated file would not parse ({exc}); edit [{name}] by hand") from exc
        if reparsed != expected:
            raise InitError(f"{path}: unsupported layout; edit [{name}] by hand")
        if machines.get(name) == attrs:
            err(f"  {path}: [{name}] unchanged")
        elif args.dry_run:
            err(f"  [dry-run] would write {path}:")
            err(new_text.rstrip("\n"))
        else:
            write_atomic(path, new_text)
            err(f"  wrote [{name}] to {path}")
    except InitError as exc:
        err(f"machine-init: error: {exc}")
        return 1
    except KeyboardInterrupt:
        err("\nmachine-init: interrupted; nothing was written")
        return 130
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
