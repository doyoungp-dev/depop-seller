"""Delete Depop Seller from Settings: what goes, what stays, on Windows and on a Mac."""

from __future__ import annotations

import json
import shlex
import sys
import threading
from pathlib import Path

import pytest

from depop_seller import config, uninstall


@pytest.fixture
def machine(tmp_path: Path, monkeypatch):
    """A pretend computer: an app folder, a data folder, the app's own folder, a Desktop."""
    app = tmp_path / "Programs" / "Depop Seller" / "app"
    (app / "depop_seller").mkdir(parents=True)
    data = tmp_path / "home" / "DepopSeller"
    (data / "product_image").mkdir(parents=True)
    own = tmp_path / "local" / "Depop Seller"
    own.mkdir(parents=True)
    desk = tmp_path / "Desktop"
    desk.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", app)
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "PRODUCT_IMAGE_DIR", data / "product_image")
    monkeypatch.setattr(config, "machine_config_file", lambda: own / "config.json")
    monkeypatch.setattr(config, "LOG_FILE", own / "app.log")
    monkeypatch.setattr(config, "bundled_runtime", lambda: False)
    monkeypatch.setattr(uninstall, "windows_desktop_dir", lambda: desk)
    monkeypatch.setattr(uninstall.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    return {"app": app, "data": data, "own": own, "desk": desk, "tmp": tmp_path}


def test_a_developer_copy_is_never_deleted_from_the_app(machine):
    (machine["app"] / ".git").mkdir()
    assert uninstall.install_kind() == "developer"
    with pytest.raises(RuntimeError, match="developer"):
        uninstall.start(False)


def test_what_goes_and_what_stays(machine, monkeypatch):
    elsewhere = machine["tmp"] / "Pictures" / "Autumn knits"
    (elsewhere / "raw_image").mkdir(parents=True)
    config.remember_batch("Autumn knits", elsewhere)
    monkeypatch.setattr(uninstall.sys, "platform", "win32")
    (machine["desk"] / "Depop Seller.lnk").write_text("shortcut", encoding="utf-8")

    p = uninstall.plan(delete_data=False)
    paths = [r["path"] for r in p["remove"]]
    assert p["kind"] == "copy" and str(machine["app"]) in paths and str(machine["own"]) in paths
    assert str(machine["desk"] / "Depop Seller.lnk") in paths
    assert str(machine["data"]) not in paths and p["keeps_data"] is True          # data stays by default
    assert p["batches_elsewhere"] == [{"name": "Autumn knits", "path": str(elsewhere)}]

    p = uninstall.plan(delete_data=True)
    assert str(machine["data"].resolve()) in [r["path"] for r in p["remove"]] and p["keeps_data"] is False
    assert str(elsewhere) not in [r["path"] for r in p["remove"]]                  # never batches kept elsewhere

    monkeypatch.setattr(config, "DATA_DIR", machine["tmp"] / "home")              # a data folder that is the home folder
    p = uninstall.plan(delete_data=True)
    assert p["data_folder"] is None and not any(r["path"] == str((machine["tmp"] / "home").resolve()) for r in p["remove"])


def test_an_installed_copy_goes_through_windows_own_uninstaller(machine, monkeypatch):
    install = machine["app"].parent
    (install / "unins000.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "bundled_runtime", lambda: True)
    monkeypatch.setattr(uninstall.sys, "platform", "win32")
    assert uninstall.install_kind() == "installed"
    job = uninstall.windows_job(delete_data=False, pid=4242)
    assert job["uninstaller"] == str(install / "unins000.exe") and job["pid"] == 4242
    assert str(install) not in job["to_bin"] and str(machine["own"]) in job["to_bin"]   # the uninstaller does the program

    monkeypatch.setattr(config, "bundled_runtime", lambda: False)
    (machine["desk"] / "Depop Seller.lnk").write_text("shortcut", encoding="utf-8")
    job = uninstall.windows_job(delete_data=True, pid=7)
    assert job["uninstaller"] is None and str(machine["app"]) in job["to_bin"]
    assert job["shortcut"].endswith("Depop Seller.lnk") and not any(p.endswith(".lnk") for p in job["to_bin"])
    assert job["app_root"] == str(machine["app"])                                  # only a shortcut into the app goes


def test_on_a_mac_everything_goes_to_the_trash_and_odd_folder_names_are_safe(machine, monkeypatch):
    monkeypatch.setattr(uninstall.sys, "platform", "darwin")
    odd = machine["tmp"] / "Applications" / "Depop Seller's copy; rm -rf ~"
    odd.mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", odd)
    logs = machine["tmp"] / "Library" / "Logs"
    logs.mkdir(parents=True)
    (logs / "Depop Seller.log").write_text("log", encoding="utf-8")
    monkeypatch.setattr(config, "LOG_FILE", logs / "Depop Seller.log")

    script = uninstall.posix_script(delete_data=False, pid=99)
    assert "kill -0 99" in script and '"$HOME/.Trash/' in script
    assert f"totrash {shlex.quote(str(odd))}" in script                            # one argument, never run as code
    assert f"totrash {shlex.quote(str(logs / 'Depop Seller.log'))}" in script     # just the log, not ~/Library/Logs
    assert str(machine["data"]) not in script

    started = {}
    monkeypatch.setattr(uninstall.subprocess, "Popen", lambda argv, **kw: started.update(argv=argv, kw=kw))
    out = uninstall.start(delete_data=True, pid=99)
    assert started["argv"][0] == "/bin/sh" and started["kw"]["start_new_session"] is True and started["kw"]["cwd"] != str(odd)
    written = Path(started["argv"][1]).read_text(encoding="utf-8")
    assert shlex.quote(str(machine["data"].resolve())) in written and out["bin"] == "the Trash"


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows path runs PowerShell")
def test_on_windows_the_script_gets_its_plan_as_a_file(machine, monkeypatch):
    started = {}
    monkeypatch.setattr(uninstall.subprocess, "Popen", lambda argv, **kw: started.update(argv=argv, kw=kw))
    out = uninstall.start(delete_data=False, pid=1234)
    assert started["argv"][0] == "powershell" and "SendToRecycleBin" in started["argv"][-1]
    assert started["kw"]["creationflags"] & 0x08000000                              # no console window
    assert started["kw"]["cwd"] != str(machine["app"])                              # never standing in what it removes
    job = json.loads(Path(started["kw"]["env"]["DEPOP_UNINSTALL_PLAN"]).read_text(encoding="utf-8"))
    assert job["pid"] == 1234 and str(machine["app"]) in job["to_bin"] and out["bin"] == "the Recycle Bin"


def test_deleting_waits_for_running_work_then_closes_the_app(machine, monkeypatch):
    from depop_seller.review import ReviewServer

    server = ReviewServer()

    class FakeHttp:
        def __init__(self):
            self.stopped = threading.Event()

        def shutdown(self):
            self.stopped.set()

    server.style_job["running"] = True
    with pytest.raises(RuntimeError, match="still rewriting the style"):
        server.start_uninstall(FakeHttp(), False)
    server.style_job["running"] = False

    calls = []
    monkeypatch.setattr(uninstall, "start", lambda delete_data: calls.append(delete_data) or {"remove": [], "bin": "x"})
    http = FakeHttp()
    assert server.start_uninstall(http, True) == {"remove": [], "bin": "x"} and calls == [True]
    assert http.stopped.wait(5)                                                    # the app closes so it can go
