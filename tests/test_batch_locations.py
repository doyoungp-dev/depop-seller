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
