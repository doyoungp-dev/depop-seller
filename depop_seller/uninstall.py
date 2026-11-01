"""Delete Depop Seller from this computer, from its own Settings tab.

What goes: the app itself, its icons, and its housekeeping folder (the log, the per-machine
settings, the copy an update kept of the previous version). What stays unless the seller ticks
"also delete my data": the data folder - photos in the usual place, listings, descriptions, style,
API key. Batches the seller chose to keep somewhere else always stay where they are; the page
lists them. Things outside the app (the Chrome helper, the Claude app) are the seller's to remove,
and the page says how.

The app cannot delete itself while it runs: its Python holds its own files. So it writes a small
script to the temp folder, starts it detached, answers the page and shuts down; the script waits
for the app's process to end and then does the work. Nothing is erased outright - folders go to the
Recycle Bin / Trash - except an installed copy's program files, which Windows' own uninstaller
(Inno Setup's unins000.exe) removes, as it does for any program.

A developer's git checkout is refused: that folder is a working copy, not an installed app.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config
from .desktop import no_console, windows_desktop_dir


def install_kind() -> str:
    """'installed' (Windows installer), 'copy' (a folder set up by setup.ps1 / setup.sh), or
    'developer' (a git checkout, which is never deleted from here)."""
    if (config.PROJECT_ROOT / ".git").exists():
        return "developer"
    if config.bundled_runtime() and (config.PROJECT_ROOT.parent / "unins000.exe").is_file():
        return "installed"
    return "copy"


def _housekeeping() -> list[Path]:
    """The app's own per-machine folder (and the macOS log, which lives apart)."""
    folder = config.machine_config_file().parent
    paths = [folder]
    log = config.LOG_FILE
    if not log.is_relative_to(folder):
        # macOS keeps it as ~/Library/Logs/Depop Seller.log (a shared folder: only the file goes);
        # Linux in a folder of its own
        paths.append(log if log.parent.name == "Logs" else log.parent)
    return paths


def _safe_data_dir() -> Path | None:
    """The data folder, if it is one it is sane to remove - never the home folder or a drive root."""
    data = config.DATA_DIR.resolve()
    home = Path.home().resolve()
    if data in (home, Path(data.anchor)) or data in home.parents or len(data.parts) < 3:
        return None
    return data


def plan(delete_data: bool) -> dict:
    """What a delete would do, for the page to show before anything happens."""
    kind = install_kind()
    remove: list[dict] = []
    if kind == "installed":
        remove.append({"what": "Depop Seller (the program, its Start menu and Desktop icons)",
                       "path": str(config.PROJECT_ROOT.parent)})
    elif kind == "copy":
        remove.append({"what": "Depop Seller (the app folder)", "path": str(config.PROJECT_ROOT)})
        desk = windows_desktop_dir() if sys.platform == "win32" else None
        if desk and (desk / "Depop Seller.lnk").exists():
            remove.append({"what": "the Desktop icon", "path": str(desk / "Depop Seller.lnk")})
    for p in _housekeeping():
        if p.exists():
            remove.append({"what": "its log and settings on this computer", "path": str(p)})
    data = _safe_data_dir()
    if delete_data and data is not None and data.exists():
        remove.append({"what": "your data folder (photos in the usual place, listings, style, API key)", "path": str(data)})
    elsewhere = [{"name": d.name, "path": str(d)} for d in config.batch_dirs()
                 if d.parent.resolve() != config.PRODUCT_IMAGE_DIR.resolve()]
    return {
        "kind": kind,
        "platform": {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux"),
        "bin": "the Recycle Bin" if sys.platform == "win32" else "the Trash",
        "remove": remove,
        "data_folder": str(data) if data else None,
        "keeps_data": not (delete_data and data is not None),
        "batches_elsewhere": elsewhere,
    }


# ---- the script that does it after the app has gone ---------------------------------------

_WINDOWS_SCRIPT = r'''
$plan = Get-Content -LiteralPath $env:DEPOP_UNINSTALL_PLAN -Raw | ConvertFrom-Json
try { Wait-Process -Id ([int]$plan.pid) -Timeout 90 -ErrorAction Stop } catch { }
Start-Sleep -Seconds 1
Add-Type -AssemblyName Microsoft.VisualBasic
function ToBin([string]$p) {
  if (-not (Test-Path -LiteralPath $p)) { return }
  if (Test-Path -LiteralPath $p -PathType Container) {
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p, 'OnlyErrorDialogs', 'SendToRecycleBin')
  } else {
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p, 'OnlyErrorDialogs', 'SendToRecycleBin')
  }
}
if ($plan.uninstaller) {
  Start-Process -FilePath $plan.uninstaller -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
}
foreach ($p in $plan.to_bin) { try { ToBin $p } catch { } }
if ($plan.shortcut -and (Test-Path -LiteralPath $plan.shortcut)) {
  $target = (New-Object -ComObject WScript.Shell).CreateShortcut($plan.shortcut).TargetPath
  if ($target -and $target.StartsWith($plan.app_root, [System.StringComparison]::OrdinalIgnoreCase)) { try { ToBin $plan.shortcut } catch { } }
}
Remove-Item -LiteralPath $env:DEPOP_UNINSTALL_PLAN -Force -ErrorAction SilentlyContinue
'''


def windows_job(delete_data: bool, pid: int) -> dict:
    """The plan the PowerShell script carries out (as JSON, so no path ever needs quoting)."""
    kind = install_kind()
    p = plan(delete_data)
    to_bin = [r["path"] for r in p["remove"]
              if not (kind == "installed" and r["path"] == str(config.PROJECT_ROOT.parent))
              and not r["path"].lower().endswith(".lnk")]
    shortcut = next((r["path"] for r in p["remove"] if r["path"].lower().endswith(".lnk")), None)
    return {
        "pid": pid,
        "uninstaller": str(config.PROJECT_ROOT.parent / "unins000.exe") if kind == "installed" else None,
        "to_bin": to_bin,
        "shortcut": shortcut,
        "app_root": str(config.PROJECT_ROOT),
    }


def posix_script(delete_data: bool, pid: int) -> str:
    """The shell script for macOS (and Linux): wait, then move each path to the Trash."""
    paths = [r["path"] for r in plan(delete_data)["remove"]]
    lines = [
        "#!/bin/sh",
        f"while kill -0 {int(pid)} 2>/dev/null; do sleep 0.5; done",
        "sleep 2",                                       # the .app's own script ends just after
        "totrash() {",
        '  [ -e "$1" ] || return 0',
        '  if command -v gio >/dev/null 2>&1 && [ "$(uname)" != "Darwin" ]; then gio trash "$1"; return; fi',
        '  name=$(basename "$1"); dest="$HOME/.Trash/$name"; n=2',
        '  while [ -e "$dest" ]; do dest="$HOME/.Trash/$name $n"; n=$((n+1)); done',
        '  mkdir -p "$HOME/.Trash" && mv "$1" "$dest"',
        "}",
    ]
    lines += [f"totrash {shlex.quote(p)}" for p in paths]
    lines.append('rm -f "$0"')
    return chr(10).join(lines) + chr(10)


def start(delete_data: bool, pid: int | None = None) -> dict:
    """Write and start the script, detached, and return what it will do."""
    kind = install_kind()
    if kind == "developer":
        raise RuntimeError("This is a developer's copy (a git checkout) - delete its folder yourself if you mean to.")
    pid = pid or os.getpid()
    what = plan(delete_data)
    folder = Path(tempfile.gettempdir())
    if sys.platform == "win32":
        job = folder / f"depop-seller-uninstall-{pid}.json"
        job.write_text(json.dumps(windows_job(delete_data, pid)), encoding="utf-8")
        flags = no_console().get("creationflags", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
        # cwd: a process standing in a folder keeps Windows from removing it - the app's own folder was
        # left behind, empty, when the script started there (found by the first real test)
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _WINDOWS_SCRIPT],
                         env={**os.environ, "DEPOP_UNINSTALL_PLAN": str(job)}, creationflags=flags, cwd=str(folder),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    else:
        script = folder / f"depop-seller-uninstall-{pid}.sh"
        script.write_text(posix_script(delete_data, pid), encoding="utf-8")
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, cwd=str(folder), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return what
