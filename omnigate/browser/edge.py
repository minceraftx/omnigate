"""Edge launcher: locate Edge, copy the user profile, launch with CDP port."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from omnigate.browser.cdp import free_port

# Standard Edge install locations (Windows)
_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]

# Lock/transient files in a profile that must not be copied (Chrome-family).
_TRANSIENT = {
    "SingletonLock", "SingletonSocket", "SingletonCookie",
    "lockfile", "DevToolsActivePort",
    "Default/Cookies-journal", "Default/Web Data-journal",
}


def find_edge() -> str | None:
    """Locate the Edge executable."""
    for p in _EDGE_PATHS:
        if os.path.exists(p):
            return p
    return None


def find_edge_profile_dir() -> str:
    """Locate the Edge user data directory (parent of Default/Profile N)."""
    return os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")


def copy_profile(src_user_data: str, dst_user_data: str) -> str:
    """Copy Edge user-data content into dst_user_data (dst becomes user-data-dir).

    Copied content lands at dst root, so `dst/Default`, `dst/Local State` exist.
    Returns dst_user_data. Raises RuntimeError on failure (e.g. file locks).
    """
    dst = Path(dst_user_data)
    dst.mkdir(parents=True, exist_ok=True)

    def _ignore(src: str, names: list[str]) -> set[str]:
        ignored = set()
        for n in names:
            if n in _TRANSIENT:
                ignored.add(n)
        return ignored

    try:
        shutil.copytree(
            src_user_data,
            str(dst),
            ignore=_ignore,
            dirs_exist_ok=True,
            copy_function=shutil.copy2,
        )
    except (OSError, shutil.Error) as exc:
        raise RuntimeError(f"Failed to copy Edge profile: {exc}") from exc
    return str(dst)


def prepare_profile() -> tuple[str, str]:
    """Copy the real Edge user profile to a fresh temp dir.

    Returns (user_data_dir, temp_dir). temp_dir is the parent that must be
    cleaned up by the caller. user_data_dir becomes the --user-data-dir value.
    """
    src = find_edge_profile_dir()
    if not os.path.isdir(src):
        raise RuntimeError(f"Edge profile dir not found: {src}")
    temp_dir = tempfile.mkdtemp(prefix="omnigate-profile-")
    user_data_dir = os.path.join(temp_dir, "user-data")
    copy_profile(src, user_data_dir)
    return user_data_dir, temp_dir


def build_launch_args(
    port: int,
    user_data_dir: str,
    headless: bool = True,
) -> list[str]:
    """Build the Edge command line for CDP launch."""
    args = [
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeSidebarV2",
    ]
    if headless:
        args.append("--headless=new")
    return args


def launch_edge(
    edge_path: str,
    port: int,
    user_data_dir: str,
    headless: bool = True,
) -> subprocess.Popen:
    """Launch Edge with CDP. Returns the process handle."""
    args = [edge_path, *build_launch_args(port, user_data_dir, headless), "about:blank"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
