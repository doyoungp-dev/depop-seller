"""Batches kept wherever the seller chooses - the Desktop, Downloads, an external drive - next to
the ones in the usual folder, and the system folder chooser that picks the place."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path

import pytest

from depop_seller import config, desktop
from depop_seller.review import ReviewHandler, ReviewServer, _Server


@pytest.fixture
def desk(tmp_path: Path) -> Path:
    folder = tmp_path / "Desktop"
    folder.mkdir()
    return folder


def test_a_batch_can_live_in_any_folder_and_is_found_by_its_name(batch, desk: Path):
    server = ReviewServer()
    made = server.new_batch("Autumn knits", str(desk))
    root = desk / "Autumn knits"
    assert made["elsewhere"] is True and made["raw"] == str(root / "raw_image")
    assert (root / "raw_image").is_dir() and not any((root / "raw_image").iterdir())    # empty until photos come
    assert config.batch_paths("Autumn knits").root == root
    assert {d.name for d in config.batch_dirs()} == {"20990101", "Autumn knits"}
    assert config.last_batch_location() == desk                  # the next new batch offers the same place
    assert (config.PRODUCT_IMAGE_DIR / config.ELSEWHERE_FILE).is_file()   # travels with the data folder

    plain = server.new_batch("Plain")                             # no place chosen: the usual folder
    assert plain["elsewhere"] is False and (config.PRODUCT_IMAGE_DIR / "Plain" / "raw_image").is_dir()
    assert config.last_batch_location() == config.PRODUCT_IMAGE_DIR

    listed = {b["name"]: b for b in server.batches()["batches"]}
    assert listed["Autumn knits"]["elsewhere"] is True and listed["Autumn knits"]["folder"] == str(root)
    assert listed["20990101"]["elsewhere"] is False and listed["20990101"]["photos"] == 8
    (root / "raw_image" / "IMG_1.jpg").write_bytes((batch.raw / "IMG_1001.jpg").read_bytes())
    (root / "IMG_2.jpg").write_bytes(b"put next to raw_image by mistake")
    listed = {b["name"]: b for b in server.batches()["batches"]}
    assert listed["Autumn knits"]["photos"] == 1 and listed["Autumn knits"]["loose_photos"] == 1
    assert server.add_photo("Autumn knits", "IMG_3.jpg", b"jpeg bytes")["written"] is True
    assert (root / "raw_image" / "IMG_3.jpg").is_file()


def test_names_stay_unique_and_some_places_are_refused(batch, desk: Path, tmp_path: Path, monkeypatch):
    server = ReviewServer()
    server.new_batch("Autumn knits", str(desk))
    for name, place in (("20990101", str(desk)), ("Autumn knits", None), ("Autumn knits", str(tmp_path))):
        with pytest.raises(ValueError, match="already exists"):
            server.new_batch(name, place)

    (desk / "Ready made").mkdir()                                 # an empty folder of that name is used
    assert server.new_batch("Ready made", str(desk))["folder"] == str(desk / "Ready made")
    (desk / "Holiday").mkdir()
    (desk / "Holiday" / "notes.txt").write_text("someone else's", encoding="utf-8")
    with pytest.raises(ValueError, match="other things in it"):
        server.new_batch("Holiday", str(desk))

    with pytest.raises(FileNotFoundError):
        server.new_batch("Nowhere", str(tmp_path / "no such folder"))
    with pytest.raises(ValueError, match="folder button"):
        server.new_batch("Relative", "Desktop")
    with pytest.raises(ValueError, match="inside the batch"):
        server.new_batch("Nested", str(desk / "Autumn knits" / "raw_image"))
    app = tmp_path / "app"
    (app / "sub").mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", app)
    with pytest.raises(ValueError, match="app itself"):            # an update would replace it
        server.new_batch("In the app", str(app / "sub"))


def test_renaming_keeps_a_batch_where_it_lives(batch, desk: Path):
    server = ReviewServer()
    server.new_batch("Autumn knits", str(desk))
    server.rename_batch("Autumn knits", "Winter knits")
    assert (desk / "Winter knits" / "raw_image").is_dir() and not (desk / "Autumn knits").exists()
    assert config.batch_paths("Winter knits").root == desk / "Winter knits"
    assert "Autumn knits" not in config.batches_elsewhere()
    with pytest.raises(ValueError, match="already exists"):
        server.rename_batch("Winter knits", "20990101")
    server.rename_batch("20990101", "January")                    # the usual folder works as before
    assert (config.PRODUCT_IMAGE_DIR / "January" / "raw_image").is_dir()


def test_a_batch_whose_folder_went_away_is_shown_and_can_be_taken_off_the_list(batch, desk: Path):
    server = ReviewServer()
    server.new_batch("On a drive", str(desk))
    shutil.rmtree(desk / "On a drive")                            # moved, deleted, or the drive unplugged
    info = server.batches()
    assert info["missing"] == [{"name": "On a drive", "folder": str(desk / "On a drive")}]
    assert "On a drive" not in {b["name"] for b in info["batches"]}
    with pytest.raises(FileNotFoundError, match="moved"):
        config.batch_paths("On a drive")
    with pytest.raises(ValueError, match="already exists"):       # the name is still taken until forgotten
        server.new_batch("On a drive")

    moved_to = desk.parent / "Pictures"                           # the seller moved it: found again
    (moved_to / "Was moved" / "raw_image").mkdir(parents=True)
    (moved_to / "Was moved" / "manifest.csv").write_text("kept", encoding="utf-8")
    server.new_batch("Was moved", str(desk))
    shutil.rmtree(desk / "Was moved")
    with pytest.raises(ValueError, match="already exists"):       # not there either: still refused
        server.new_batch("Was moved", str(desk))
    assert server.new_batch("Was moved", str(moved_to))["folder"] == str(moved_to / "Was moved")
    assert (moved_to / "Was moved" / "manifest.csv").read_text(encoding="utf-8") == "kept"   # its work came along
    assert config.batch_paths("Was moved").root == moved_to / "Was moved"
    with pytest.raises(LookupError):
        server.forget_batch("20990101")                           # only batches kept elsewhere
    assert server.forget_batch("On a drive") == {"forgotten": "On a drive"}
    assert server.batches()["missing"] == []
    assert batch.raw.is_dir()                                     # nothing else was touched


def test_the_folder_chooser_is_the_system_s_own_on_windows_and_mac(tmp_path: Path, monkeypatch):
    prompt = 'Where "here" & there'
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    cmd, extra = desktop.folder_picker_command(prompt, tmp_path)
    assert cmd[:3] == ["powershell", "-NoProfile", "-STA"]
    script = cmd[-1]
    assert "IFileDialog" in script and "d.SetOptions(0x20" in script   # Explorer's Select Folder (pick folders)
    assert "$owner.TopMost = $true" in script and "$owner.Show()" in script   # shown, or Windows never displays it
    assert "FolderBrowserDialog" in script                        # the fallback
    assert prompt not in " ".join(cmd)                            # text travels in the environment, not the script
    assert extra["env"]["DEPOP_PICK_PROMPT"] == prompt and extra["env"]["DEPOP_PICK_START"] == str(tmp_path)

    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    cmd, extra = desktop.folder_picker_command(prompt, tmp_path)
    assert cmd[0] == "osascript" and cmd[-2:] == [prompt, str(tmp_path)] and extra == {}
    script = " ".join(cmd[1:-2])
    assert "choose folder" in script and "activate" in script and "-128" in script   # cancel is not an error
    cmd, _ = desktop.folder_picker_command(prompt, tmp_path / "gone")
    assert cmd[-1] == prompt                                      # no starting folder that is not there

    monkeypatch.setattr(desktop.sys, "platform", "linux")
    assert desktop.folder_picker_command(prompt, None)[0][:3] == ["zenity", "--file-selection", "--directory"]

    answers = iter([str(tmp_path) + chr(10), "", None])

    def fake_run(cmd, **kw):
        out = next(answers)
        if out is None:
            raise FileNotFoundError("no zenity")
        return subprocess.CompletedProcess(cmd, 0 if out else 1, stdout=out.encode(), stderr=b"")

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    assert desktop.choose_folder("pick") == tmp_path
    assert desktop.choose_folder("pick") is None                  # cancelled
    with pytest.raises(RuntimeError, match="folder chooser"):
        desktop.choose_folder("pick")


def test_choosing_a_place_from_the_page(batch, desk: Path, monkeypatch):
    picked = {}

    def fake_choose(prompt, start):
        picked.update(prompt=prompt, start=start)
        return picked.get("answer")

    monkeypatch.setattr(desktop, "choose_folder", fake_choose)
    srv = _Server(("127.0.0.1", 0), partial(ReviewHandler, ReviewServer()))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(path, body, origin=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        if origin:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    try:
        picked["answer"] = desk
        assert post("/batches/choose-folder", {"purpose": "new"}) == (200, {"folder": str(desk)})
        assert "new batch" in picked["prompt"] and picked["start"] == config.PRODUCT_IMAGE_DIR
        picked["answer"] = None
        assert post("/batches/choose-folder", {"purpose": "import"}) == (200, {"folder": None})
        assert post("/batches/choose-folder", {"purpose": "new"}, "https://evil.example")[0] == 403
        status, made = post("/batches/new", {"name": "From the page", "location": str(desk)})
        assert status == 200 and made["folder"] == str(desk / "From the page")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/batches") as r:
            info = json.load(r)
        assert info["new_batch_location"] == str(desk)
        assert any(b["name"] == "From the page" and b["elsewhere"] for b in info["batches"])
    finally:
        srv.shutdown()
        srv.server_close()


def _trash_into(tmp_path: Path):
    """A stand-in for the Recycle Bin: the folder really leaves its place, into tmp_path/bin."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)

    def move(path):
        shutil.move(str(path), str(bin_ / Path(path).name))
        return "the Recycle Bin"
    return bin_, move


def test_deleting_a_batch_removes_its_folder_and_its_rows(batch, desk: Path, tmp_path: Path, monkeypatch):
    from depop_seller import db
    from depop_seller.group import decisions_to_rows, group_local
    from depop_seller.manifest import write_manifest
    from depop_seller.scan import scan_batch

    bin_, move = _trash_into(tmp_path)
    monkeypatch.setattr(desktop, "move_to_trash", move)
    server = ReviewServer()
    photos = scan_batch(batch)
    write_manifest(batch.manifest, decisions_to_rows(photos, group_local(batch, photos)))
    server.sell_update("20990101", 1, {"status": "listed", "description": "red top"})

    server.group_state["20990101"] = {"running": True}
    with pytest.raises(RuntimeError, match="still being worked on"):
        server.delete_batch("20990101")
    assert batch.root.is_dir()
    server.group_state.clear()

    out = server.delete_batch("20990101")
    assert out == {"deleted": "20990101", "folder": str(batch.root), "where": "the Recycle Bin"}
    assert not batch.root.exists() and (bin_ / "20990101" / "raw_image" / "IMG_1001.jpg").is_file()
    conn = db.connect()
    try:
        assert db.item_rows(conn, "20990101") == {}
        assert conn.execute("SELECT COUNT(*) FROM photos WHERE batch = ?", ("20990101",)).fetchone()[0] == 0
    finally:
        conn.close()
    assert "20990101" not in {b["name"] for b in server.batches()["batches"]}

    server.new_batch("Elsewhere", str(desk))                      # one kept elsewhere leaves the list too
    server.delete_batch("Elsewhere")
    assert not (desk / "Elsewhere").exists() and "Elsewhere" not in config.batches_elsewhere()
    assert desk.is_dir()                                          # the place it was in stays
    with pytest.raises(FileNotFoundError):
        server.delete_batch("Elsewhere")


def test_delete_comes_only_from_the_app_s_own_page(batch, tmp_path: Path, monkeypatch):
    _, move = _trash_into(tmp_path)
    monkeypatch.setattr(desktop, "move_to_trash", move)
    srv = _Server(("127.0.0.1", 0), partial(ReviewHandler, ReviewServer()))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        def post(origin=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/batches/delete", method="POST",
                                         data=json.dumps({"name": "20990101"}).encode())
            req.add_header("Content-Type", "application/json")
            if origin:
                req.add_header("Origin", origin)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code

        assert post("https://evil.example") == 403 and batch.root.is_dir()      # another site cannot
        assert post() == 200 and not batch.root.exists()
    finally:
        srv.shutdown()
        srv.server_close()


def test_moving_to_the_trash_on_a_mac_and_on_linux(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    (home / ".Trash" / "Autumn knits").mkdir(parents=True)          # one of that name is already there
    folder = tmp_path / "Autumn knits"
    (folder / "raw_image").mkdir(parents=True)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(desktop.Path, "home", lambda: home)
    assert desktop.move_to_trash(folder) == "the Trash"
    assert not folder.exists() and (home / ".Trash" / "Autumn knits 2" / "raw_image").is_dir()

    monkeypatch.setattr(desktop.sys, "platform", "linux")
    (folder / "raw_image").mkdir(parents=True)
    seen = []
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, b"", b""))
    with pytest.raises(OSError, match="still there"):              # never claims a delete that did not happen
        desktop.move_to_trash(folder)
    assert seen[0][:2] == ["gio", "trash"]


def test_settings_lists_each_batch_where_it_is(batch, desk: Path, tmp_path: Path, monkeypatch):
    from depop_seller import settings

    server = ReviewServer()
    server.new_batch("Autumn knits", str(desk))
    server.new_batch("Lost one", str(desk))
    shutil.rmtree(desk / "Lost one")                              # moved away: not listed, only counted
    _, move = _trash_into(tmp_path)
    monkeypatch.setattr(desktop, "move_to_trash", move)
    server.new_batch("Gone")
    server.delete_batch("Gone")                                   # deleted: not there at all

    env = settings.environment()
    listed = {b["name"]: b for b in env["batch_list"]}
    assert set(listed) == {"20990101", "Autumn knits"}
    assert listed["Autumn knits"] == {"name": "Autumn knits", "folder": str(desk / "Autumn knits"),
                                      "photos": 0, "elsewhere": True}
    assert listed["20990101"]["elsewhere"] is False and listed["20990101"]["photos"] == 8
    assert env["batches_elsewhere"] == 1 and env["batches_missing"] == 1 and env["photos"] == 8


def test_claude_code_is_found_where_the_windows_app_keeps_it_now(tmp_path: Path, monkeypatch):
    """After a Claude app update on Windows, Claude Code moved out of the packaged app's
    LocalCache into LOCALAPPDATA / Claude-Data / claude_<id> / claude-code / <version> / <build> / claude.exe.
    Both places are searched, the new one first; the newest version wins."""
    from depop_seller import describe

    monkeypatch.setattr(describe.sys, "platform", "win32")
    monkeypatch.setattr(describe.os, "name", "nt")
    monkeypatch.setattr(describe, "CLI_NAME", "claude.exe")
    monkeypatch.setattr(describe, "CLAUDE_CLI_CANDIDATES", [])
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(describe, "_LOCALAPPDATA", tmp_path / "Local")
    monkeypatch.setattr(describe, "_APPDATA", tmp_path / "Roaming")
    monkeypatch.setattr(describe.Path, "home", classmethod(lambda cls: tmp_path))
    assert describe.find_claude_cli() is None

    old = tmp_path / "Local" / "Packages" / "Claude_abc" / "LocalCache" / "Roaming" / "Claude" / "claude-code" / "2.1.200"
    old.mkdir(parents=True)
    (old / "claude.exe").write_text("", encoding="utf-8")
    assert describe.find_claude_cli() == old / "claude.exe"                  # an older Claude app still works

    bundle = tmp_path / "Local" / "Claude-Data" / "claude_abc" / "claude-code"
    for version, build in (("2.1.9", "aaa"), ("2.1.309", "9078b9c1d466")):
        (bundle / version / build).mkdir(parents=True)
        (bundle / version / build / "claude.exe").write_text("", encoding="utf-8")
    assert describe.find_claude_cli() == bundle / "2.1.309" / "9078b9c1d466" / "claude.exe"
