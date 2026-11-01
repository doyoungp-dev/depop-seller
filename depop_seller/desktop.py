"""Desktop integration: the bits that differ between Windows, macOS and Linux.

The pages have to run in the user's own Chrome - that is where the helper extension lives, and
without it the Depop button falls back to an automated browser Depop blocks. So "open the app"
means Chrome's `--app=` mode: the same browser and the same profile, but a window with no tabs and
no address bar, with its own icon in the dock or taskbar. Any Chromium browser will do; if none is
found the default browser is used instead.
"""

from __future__ import annotations

import logging
import os
import shutil
import ssl
import subprocess
import sys
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)

WINDOW_SIZE = (1360, 900)


def no_console() -> dict:
    """Keyword arguments for starting a console program in the background.

    The app runs without a console (pythonw on Windows). Windows then gives any console program it
    starts - Claude Code, taskkill, PowerShell - a console window of its own: a black box popping
    up in front of someone who has no idea what it is. CREATE_NO_WINDOW stops that. Only for work
    that happens out of sight; the sign-in terminal is meant to be seen and does not use this.
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}

def https_context() -> ssl.SSLContext | None:
    """The TLS context for the app's own https requests (Check for updates, Update, the White
    Background model), or None for Python's default.

    python.org's Python for macOS carries no list of trusted certificates until its "Install
    Certificates" step is run, which no seller does - so every request failed verification and
    Check for updates said GitHub could not be reached. truststore checks against the Mac's own
    Keychain, as the anthropic SDK (which brings it in) already does for photo grouping; certifi's
    bundle is the fallback. Windows' Python already reads the Windows certificate store, so there
    nothing changes.
    """
    if os.name == "nt":
        return None
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None

# Most preferred first. No --user-data-dir: the window must use the profile the extension is in.
_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
_WINDOWS = [
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
]
_LINUX = ["google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"]


def app_browser() -> Path | None:
    """The Chromium browser to open app windows with, or None to fall back to the default browser."""
    override = os.environ.get("DEPOP_BROWSER", "").strip()
    if override:
        p = Path(os.path.expandvars(override)).expanduser()
        return p if p.exists() else None
    if sys.platform == "darwin":
        candidates = [Path(c).expanduser() for c in _MAC]
    elif sys.platform == "win32":
        candidates = [Path(os.path.expandvars(c)) for c in _WINDOWS]
    else:
        candidates = [Path(found) for name in _LINUX if (found := shutil.which(name))]
    return next((c for c in candidates if c.exists()), None)


def app_window(url: str, *, size: tuple[int, int] = WINDOW_SIZE) -> str:
    """Open `url` as an app window. Returns the name of whatever opened it (for the console line)."""
    exe = app_browser()
    if exe is None:
        webbrowser.open(url)
        return "default browser"
    cmd = [str(exe), f"--app={url}", f"--window-size={size[0]},{size[1]}"]
    kwargs = {"start_new_session": True} if os.name != "nt" else {}
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    except OSError as e:                      # a browser that moved or is not runnable
        log.warning("could not open %s as an app window (%s); using the default browser", exe.name, e)
        webbrowser.open(url)
        return "default browser"
    return exe.stem if sys.platform == "win32" else exe.name


def open_folder(path: Path) -> None:
    """Show a folder in Explorer / Finder / the Linux file manager."""
    path = Path(path)
    if sys.platform == "win32":
        os.startfile(str(path))               # noqa: S606 - Windows only, path comes from our own config
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


# The page cannot ask the browser for a real folder path, so the server opens the system's own
# folder chooser and hands back what the seller picked. Text goes in through the environment
# (Windows) or argv (macOS), never pasted into the script, so quotes in a path cannot break it.
#
# Windows: the app runs windowless, and Windows does not show a dialog from a background program
# at all unless it hangs off a real, shown, always-on-top window - with a hidden owner or none,
# the dialog existed and waited but never appeared (seen on 2026-11-01 by capturing the screen;
# this version was the only one that showed). So a 1-pixel invisible TopMost form is shown first
# and owns the dialog. The dialog is Explorer's own "Select Folder" (IFileOpenDialog with
# FOS_PICKFOLDERS - sidebar, Desktop, Downloads, New folder); the old tree-style
# FolderBrowserDialog is only a fallback if the C# helper cannot be compiled.
_WINDOWS_PICKER = r'''
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$modern = $true
try {
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class DepopFolderPicker {
  [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialogRCW {}
  [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileDialog {
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint c, IntPtr f); void SetFileTypeIndex(uint i); void GetFileTypeIndex(out uint i);
    void Advise(IntPtr p, out uint c); void Unadvise(uint c); void SetOptions(uint fos); void GetOptions(out uint fos);
    void SetDefaultFolder(IShellItem si); void SetFolder(IShellItem si); void GetFolder(out IShellItem si);
    void GetCurrentSelection(out IShellItem si); void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string n);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string n); void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string t); void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void GetResult(out IShellItem si); void AddPlace(IShellItem si, int fdap); void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string e);
    void Close(int hr); void SetClientGuid(ref Guid g); void ClearClientData(); void SetFilter(IntPtr f);
  }
  [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv); void GetParent(out IShellItem si);
    void GetDisplayName(uint sigdn, [MarshalAs(UnmanagedType.LPWStr)] out string name);
    void GetAttributes(uint mask, out uint attrs); void Compare(IShellItem si, uint hint, out int order);
  }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, ref Guid riid, out IShellItem item);
  public static string Pick(string title, string start, IntPtr owner) {
    IFileDialog d = (IFileDialog)new FileOpenDialogRCW();
    d.SetOptions(0x20 | 0x40 | 0x800);
    d.SetTitle(title);
    if (!String.IsNullOrEmpty(start)) {
      try { Guid g = typeof(IShellItem).GUID; IShellItem si; SHCreateItemFromParsingName(start, IntPtr.Zero, ref g, out si); d.SetFolder(si); } catch {}
    }
    if (d.Show(owner) != 0) return null;
    IShellItem r; d.GetResult(out r); string p; r.GetDisplayName(0x80058000, out p); return p;
  }
}
"@
} catch { $modern = $false }
$area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true; $owner.ShowInTaskbar = $false; $owner.FormBorderStyle = 'None'; $owner.Opacity = 0
$owner.StartPosition = 'Manual'; $owner.Width = 1; $owner.Height = 1
$owner.Left = $area.Left + [int](($area.Width - 900) / 2); $owner.Top = $area.Top + [int](($area.Height - 620) / 2)
$owner.Show(); $owner.Activate()
$start = ''
if ($env:DEPOP_PICK_START -and (Test-Path -LiteralPath $env:DEPOP_PICK_START)) { $start = $env:DEPOP_PICK_START }
$picked = $null
if ($modern) {
  $picked = [DepopFolderPicker]::Pick($env:DEPOP_PICK_PROMPT, $start, $owner.Handle)
} else {
  $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
  $dialog.Description = $env:DEPOP_PICK_PROMPT; $dialog.ShowNewFolderButton = $true
  if ($start) { $dialog.SelectedPath = $start }
  if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $picked = $dialog.SelectedPath }
}
$owner.Close()
if ($picked) { [Console]::Out.Write($picked) }
'''

_MAC_PICKER = [
    "on run argv",
    "activate",
    "try",
    "if (count of argv) > 1 then",
    "set chosen to choose folder with prompt (item 1 of argv) default location (POSIX file (item 2 of argv))",
    "else",
    "set chosen to choose folder with prompt (item 1 of argv)",
    "end if",
    "on error number -128",                     # Cancel
    "return \"\"",
    "end try",
    "return POSIX path of chosen",
    "end run",
]


def folder_picker_command(prompt: str, start: Path | None) -> tuple[list[str], dict]:
    """The command that shows this system's folder chooser, and extra keyword arguments for it."""
    start_ok = start is not None and Path(start).is_dir()
    if sys.platform == "win32":
        env = {**os.environ, "DEPOP_PICK_PROMPT": prompt, "DEPOP_PICK_START": str(start) if start_ok else ""}
        return (["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", _WINDOWS_PICKER],
                {"env": env, **no_console()})
    if sys.platform == "darwin":
        cmd = ["osascript"]
        for line in _MAC_PICKER:
            cmd += ["-e", line]
        return cmd + [prompt] + ([str(start)] if start_ok else []), {}
    cmd = ["zenity", "--file-selection", "--directory", "--title", prompt]
    if start_ok:
        cmd += ["--filename", str(start) + os.sep]
    return cmd, {}


def choose_folder(prompt: str, start: Path | None = None) -> Path | None:
    """Show the system's folder chooser; the folder picked, or None if the seller cancelled."""
    cmd, extra = folder_picker_command(prompt, start)
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=30 * 60, check=False, **extra)
    except FileNotFoundError as e:
        raise RuntimeError("this computer has no folder chooser the app can open") from e
    except subprocess.TimeoutExpired:
        return None
    chosen = done.stdout.decode("utf-8", "replace").strip()
    if not chosen:                                   # cancelled (zenity and osascript-on-error exit non-zero)
        return None
    folder = Path(chosen)                            # pathlib drops a trailing slash, keeps D:\ whole
    return folder if folder.is_dir() else None


def _windows_recycle(path: Path) -> None:
    """SHFileOperation with FOF_ALLOWUNDO: the folder goes to the Recycle Bin, silently."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=str(path) + chr(0) + chr(0),   # a double-NUL-ended list
                         fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Windows could not move it to the Recycle Bin (code {result})")


def move_to_trash(path: Path) -> str:
    """Put a folder in the Recycle Bin (Windows) or the Trash (macOS), never erase it outright:
    a delete in the app can then still be undone. Returns where it went; raises if it is still
    there, so nothing is ever reported as deleted that was not."""
    path = Path(path)
    if sys.platform == "win32":
        _windows_recycle(path)
        where = "the Recycle Bin"
    elif sys.platform == "darwin":
        where = "the Trash"
        trash = Path.home() / ".Trash"
        target = trash / path.name
        n = 2
        while target.exists():                      # the Trash already holds one of that name
            target = trash / f"{path.name} {n}"
            n += 1
        try:
            shutil.move(str(path), str(target))
        except OSError:                             # e.g. another drive, or the Trash is protected: ask Finder
            done = subprocess.run(["osascript", "-e", "on run argv",
                                   "-e", 'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)',
                                   "-e", "end run", str(path)], capture_output=True, check=False)
            if done.returncode != 0:
                raise OSError("the Mac could not move it to the Trash: "
                              + done.stderr.decode("utf-8", "replace").strip()[-200:])
    else:
        done = subprocess.run(["gio", "trash", str(path)], capture_output=True, check=False)
        if done.returncode != 0:
            raise OSError("could not move it to the trash: " + done.stderr.decode("utf-8", "replace").strip()[-200:])
        where = "the trash"
    if path.exists():
        raise OSError(f"{path} is still there - nothing was deleted")
    return where


def windows_desktop_dir() -> Path | None:
    """The real Desktop, which OneDrive's folder backup often moves out of the home directory."""
    if os.name != "nt":
        return None
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            raw, _ = winreg.QueryValueEx(handle, "Desktop")
        folder = Path(os.path.expandvars(raw))
        if folder.is_dir():
            return folder
    except OSError:
        pass
    fallback = Path.home() / "Desktop"
    return fallback if fallback.is_dir() else None


def ensure_desktop_shortcut(project_root: Path) -> Path | None:
    """Put the app's icon on the Desktop if it is not there.

    Setup makes it, but setup gets skipped when a .venv already exists and its last step can fail,
    and then there is no way into the app except finding a file in a folder. Best effort: nothing
    here may stop the app from starting.
    """
    desktop = windows_desktop_dir()
    if desktop is None:
        return None
    link = desktop / "Depop Seller.lnk"
    if link.exists():
        return link
    maker = project_root / "make_desktop_icon.ps1"
    if not maker.is_file():
        return None
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(maker)],
                       cwd=str(project_root), capture_output=True, timeout=60, check=False, **no_console())
    except (OSError, subprocess.SubprocessError):
        return None
    if link.exists():
        log.info("put the Depop Seller icon on the Desktop")
        return link
    return None
