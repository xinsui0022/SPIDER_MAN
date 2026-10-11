"""File-only local tool/game discovery; no process access or game mutation."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

GAME_FILENAME = "Spider-Man.exe"
GAME_DIRECTORY = "Marvel's Spider-Man Remastered"


def executable_path(value):
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    discovered = shutil.which(expanded) if not Path(expanded).is_absolute() else None
    return Path(discovered or expanded).resolve()


def steam_roots():
    roots = []
    if os.name == "nt":
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as entry:
                    roots.append(Path(winreg.QueryValueEx(entry, value)[0]))
            except OSError:
                pass
    for name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        if os.environ.get(name):
            roots.append(Path(os.environ[name]) / "Steam")
    return roots


def steam_libraries():
    roots = steam_roots()
    libraries = list(roots)
    for root in roots:
        config = root / "steamapps" / "libraryfolders.vdf"
        try:
            if config.stat().st_size > 1024 * 1024:
                continue
            text = config.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for value in re.findall(r'"path"\s+"((?:\\.|[^"\\])*)"', text, re.IGNORECASE):
            libraries.append(Path(value.replace("\\\\", "\\").replace('\\"', '"')))
    return libraries


def game_executable(explicit=None):
    """Explicit CLI/env path wins; otherwise discover one Steam installation.

    A missing fallback is intentional: runtime tools report it and tell the
    operator to set COOPSYNC_GAME_EXE. Fixed offsets are always gated elsewhere
    by the exact build SHA256 before any memory reads.
    """
    value = explicit if explicit is not None else os.environ.get("COOPSYNC_GAME_EXE")
    if value:
        path = executable_path(value)
        if path.name.casefold() != GAME_FILENAME.casefold():
            raise ValueError("COOPSYNC_GAME_EXE/--game must name Spider-Man.exe")
        return path
    candidates = {}
    for root in steam_libraries():
        path = (root / "steamapps" / "common" / GAME_DIRECTORY / GAME_FILENAME).resolve()
        if path.is_file():
            candidates[os.path.normcase(str(path))] = path
    if len(candidates) > 1:
        raise ValueError("Multiple Spider-Man installations; set COOPSYNC_GAME_EXE or --game explicitly")
    if candidates:
        return next(iter(candidates.values()))
    return (Path.cwd() / GAME_FILENAME).resolve()


def objdump_executable(explicit=None):
    value = explicit if explicit is not None else os.environ.get("COOPSYNC_OBJDUMP")
    return executable_path(value or shutil.which("objdump.exe") or shutil.which("objdump") or "objdump.exe")

