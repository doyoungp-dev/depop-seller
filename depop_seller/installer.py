"""Build DepopSellerSetup.exe, the Windows installer - for whoever makes releases, not for sellers.

What people install is the app together with the Python it runs on, so nothing has to be set up by
hand and no console window ever appears:

    <install>/runtime/   Python's official "embeddable" build for Windows, with the app's libraries
                         in Lib/site-packages and a python3XX._pth that also puts ../app on the path
    <install>/app/       exactly what DepopSeller.zip holds - the folder the in-app updater keeps
                         current, so code updates stay small and never need the installer again

`build()` stages both under build/installer/, proves the staged copy works on its own by starting
its server and asking it for /version, and has Inno Setup (a free installer builder, installed on
the release machine) compile installer/DepopSeller.iss into dist/DepopSellerSetup.exe.

The libraries are the exact versions the release machine's tests ran against: every package
installed there is passed to pip as a constraint, so the bundle cannot drift to newer releases.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import platform
import py_compile
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
import zipfile
from pathlib import Path

from . import updates

EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
ISS = Path("installer") / "DepopSeller.iss"
SETUP_NAME = updates.INSTALLER_NAME


class BuildError(RuntimeError):
    pass


def find_iscc() -> Path | None:
    """Inno Setup's compiler: DEPOP_ISCC, PATH, then where its installer puts it."""
    candidates = [os.environ.get("DEPOP_ISCC", ""), shutil.which("ISCC") or ""]
    if os.environ.get("LOCALAPPDATA"):                             # installed for the current user
        candidates.append(str(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno Setup 6" / "ISCC.exe"))
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:                                                   # installed for everyone
            candidates.append(str(Path(base) / "Inno Setup 6" / "ISCC.exe"))
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def pth_text(tag: str) -> str:
    """The runtime's path file. With it, Python ignores every other Python on the machine
    (PYTHONPATH, the registry, user site-packages) and looks only here."""
    lines = [f"python{tag}.zip", ".", r"Lib\site-packages", r"..\app", "",
             "# Depop Seller: the libraries are in Lib\\site-packages, the app itself in ..\\app", "import site", ""]
    return chr(10).join(lines)


def constraints() -> list[str]:
    """Every package installed where the release is built, pinned: the bundle gets exactly the
    versions the tests passed with. Constraints only pin; they never add a package."""
    pins: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = (dist.metadata["Name"] or "").strip()
        key = name.lower().replace("_", "-").replace(".", "-")
        if name and key != "depop-seller" and key not in pins:       # the first one Python would import
            pins[key] = f"{name}=={dist.version}"
    return sorted(pins.values(), key=str.lower)


def dependencies(pyproject: Path) -> list[str]:
    return list(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"])


def embeddable(cache: Path, version: str) -> Path:
    """Python's embeddable zip for this exact version, downloaded once from python.org."""
    target = cache / f"python-{version}-embed-amd64.zip"
    if not target.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(".part")
        request = urllib.request.Request(EMBED_URL.format(v=version), headers={"User-Agent": "depop-seller-release"})
        with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:
            shutil.copyfileobj(response, out)
        part.replace(target)
    with zipfile.ZipFile(target) as z:
        names = set(z.namelist())
    tag = version_tag(version)
    if not {"python.exe", "pythonw.exe", f"python{tag}._pth", f"python{tag}.zip"} <= names:
        target.unlink()
        raise BuildError(f"{target.name} is not Python's embeddable package - deleted, run again")
    return target


def version_tag(version: str) -> str:
    major, minor = version.split(".")[:2]
    return f"{major}{minor}"


def stage_runtime(stage: Path, embed_zip: Path, version: str, requirements: list[str], say=print) -> Path:
    runtime = stage / "runtime"
    with zipfile.ZipFile(embed_zip) as z:
        z.extractall(runtime)
    tag = version_tag(version)
    (runtime / f"python{tag}._pth").write_text(pth_text(tag), encoding="utf-8")
    site = runtime / "Lib" / "site-packages"
    site.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        pins = Path(tmp) / "constraints.txt"
        pins.write_text(chr(10).join(constraints()) + chr(10), encoding="utf-8")
        say(f"   libraries: {', '.join(requirements)}")
        done = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                               "--no-warn-script-location", "--only-binary=:all:", "--target", str(site),
                               "-c", str(pins), *requirements], capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError("could not gather the libraries: " + (done.stderr or done.stdout).strip()[-800:])
    shutil.rmtree(site / "bin", ignore_errors=True)               # console scripts nobody runs
    return runtime


def stage_app(stage: Path, release_zip: Path) -> Path:
    """The app folder is the release zip, unpacked: the same bytes the updater compares against."""
    app = stage / "app"
    prefix = updates.ZIP_ROOT + "/"
    with zipfile.ZipFile(release_zip) as z:
        for member in z.namelist():
            if not member.startswith(prefix) or member.endswith("/"):
                continue
            target = app / member[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(member))
    return app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke_test(stage: Path, version: str, say=print) -> None:
    """Start the staged app exactly as the installed one starts - its own runtime, its own path
    file, nothing from this machine's Python - and ask it for /version."""
    python = stage / "runtime" / "python.exe"
    probe = ("import depop_seller, PIL, pillow_heif, anthropic, dotenv, onnxruntime, sqlite3, ssl, "
             "depop_seller.review, depop_seller.settings, depop_seller.describe, depop_seller.group, "
             "depop_seller.updates, depop_seller.whitebg; import json; print(json.dumps({'version': depop_seller.__version__, "
             "'app': depop_seller.__file__, 'pil': PIL.__file__}))")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "ANTHROPIC_"))}
        env.update(DEPOP_SELLER_DATA=str(Path(tmp) / "data"), LOCALAPPDATA=str(Path(tmp) / "local"))
        # -B: the run writes no compiled files into the bundle - they would name this computer's folders
        done = subprocess.run([str(python), "-B", "-c", probe], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
        if done.returncode != 0:
            raise BuildError("the staged app does not import: " + done.stderr.strip()[-800:])
        where = json.loads(done.stdout)
        if where["version"] != version:
            raise BuildError(f"the staged app says it is {where['version']}, expected {version}")
        for key, folder in (("app", stage / "app"), ("pil", stage / "runtime")):
            if not Path(where[key]).resolve().is_relative_to(folder.resolve()):
                raise BuildError(f"the staged app loaded {key} from outside the bundle: {where[key]}")

        port = _free_port()
        server = subprocess.Popen([str(python), "-B", "-m", "depop_seller", "hub", "--no-browser", "--port", str(port)],
                                  cwd=str(stage / "app"), env=env | {"DEPOP_QUIET": "1"},
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            answer = None
            for _ in range(80):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/version", timeout=2) as r:
                        answer = json.load(r)
                    break
                except OSError:
                    if server.poll() is not None:
                        break
                    time.sleep(0.25)
            if not answer or answer.get("version") != version:
                raise BuildError(f"the staged app did not start and answer /version (got {answer})")
            req = urllib.request.Request(f"http://127.0.0.1:{port}/quit", data=b"{}", method="POST")
            urllib.request.urlopen(req, timeout=5).close()
            server.wait(timeout=20)
        finally:
            if server.poll() is None:
                server.kill()
    say(f"   the bundle starts on its own and answers as {version}")


def strip_build_paths(stage: Path) -> int:
    """Recompile the stage's .pyc files so each names its source relative to the install folder.

    pip and Python write the full path of a module's source into its compiled file, and on the
    release machine that path runs through the home folder - on Windows, the owner's real name - out
    to everyone who downloads the installer. Python swaps the stored path for the real one whenever
    it loads a module whose source is there, so the app behaves the same and still starts compiled.
    """
    count = 0
    for pyc in sorted(stage.rglob("*.pyc")):
        try:
            source = Path(importlib.util.source_from_cache(str(pyc)))
        except ValueError:                        # not in a __pycache__: a wheel shipped it that way
            continue
        if not source.is_file():                  # its module is gone, so Python never loads it
            pyc.unlink()
            continue
        level = re.search(r"\.opt-(\d)\.pyc$", pyc.name)
        try:
            py_compile.compile(str(source), cfile=str(pyc), dfile=str(source.relative_to(stage)),
                               doraise=True, optimize=int(level.group(1)) if level else 0)
        except py_compile.PyCompileError as e:
            raise BuildError(f"could not recompile {source.relative_to(stage)}: {e.msg}") from e
        count += 1
    return count


def _spellings(folder: Path) -> set[str]:
    """The ways a folder can be written into a file: either slash, and Windows' short 8.3 name
    (TEMP is often spelt that way, and it keeps the first letters of the user's name)."""
    names = {str(folder), folder.as_posix()}
    if os.name == "nt":
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(str(folder), buffer, len(buffer)):
            names |= {buffer.value, Path(buffer.value).as_posix()}
    return names


def check_no_local_paths(stage: Path, *folders: Path) -> None:
    """Refuse a bundle in which any file names one of these folders of the release machine, in
    UTF-8 or UTF-16, in any case."""
    markers = {s.encode(encoding).lower() for f in folders for s in _spellings(f)
               for encoding in ("utf-8", "utf-16-le")}

    def names_one(file: Path) -> bool:
        data = file.read_bytes().lower()
        return any(m in data for m in markers)

    found = [p.relative_to(stage).as_posix() for p in sorted(stage.rglob("*")) if p.is_file() and names_one(p)]
    if found:
        raise BuildError(f"{len(found)} file(s) in the bundle name a folder of this computer, "
                         f"e.g. {', '.join(found[:3])}")


# Windows refuses paths over 260 characters unless long paths were switched on, which they are not
# by default. Installed, every file sits under C:\Users\<name>\AppData\Local\Programs\Depop Seller\ -
# at most about 66 characters, since Windows caps profile folder names at 20 - so nothing inside may
# be longer than this, compiled files included.
MAX_INSIDE = 259 - 70


def check_path_lengths(stage: Path) -> None:
    longest = max((p for p in stage.rglob("*") if p.is_file()), key=lambda p: len(str(p.relative_to(stage))))
    if len(str(longest.relative_to(stage))) > MAX_INSIDE:
        raise BuildError(f"{longest.relative_to(stage)} is too long a path for Windows once installed "
                         f"({len(str(longest.relative_to(stage)))} > {MAX_INSIDE} characters)")


def compile_setup(root: Path, stage: Path, out_dir: Path, version: str) -> Path:
    iscc = find_iscc()
    if iscc is None:
        raise BuildError("Inno Setup is not installed - get it from https://jrsoftware.org/isdl.php "
                         "(any 6.x; it can be installed for the current user only)")
    out_dir.mkdir(parents=True, exist_ok=True)
    setup = out_dir / SETUP_NAME
    setup.unlink(missing_ok=True)
    done = subprocess.run([str(iscc), "/Q", f"/DAppVersion={version}", f"/DStageDir={stage}",
                           f"/DOutputDir={out_dir}", str(root / ISS)], capture_output=True, text=True)
    if done.returncode != 0 or not setup.is_file():
        raise BuildError("Inno Setup could not build the installer: " + (done.stdout + done.stderr).strip()[-1500:])
    return setup


def build(root: Path, release_zip: Path, version: str, *, say=print) -> Path:
    """Stage the runtime and the app, prove they run, and compile dist/DepopSellerSetup.exe."""
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise BuildError("the Windows installer is built on 64-bit Windows")
    python_version = platform.python_version()
    stage = root / "build" / "installer"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    say(f"   Python {python_version} (embeddable, from python.org)")
    embed = embeddable(root / "build", python_version)
    stage_runtime(stage, embed, python_version, dependencies(root / "pyproject.toml"), say=say)
    stage_app(stage, release_zip)
    say(f"   {strip_build_paths(stage)} compiled files re-pointed inside the bundle")
    smoke_test(stage, version, say=say)                            # on exactly the files that ship
    check_no_local_paths(stage, Path.home(), root.resolve())
    check_path_lengths(stage)
    setup = compile_setup(root, stage, root / "dist", version)
    say(f"   {setup.name}: {setup.stat().st_size / 1024 / 1024:.1f} MB")
    return setup
