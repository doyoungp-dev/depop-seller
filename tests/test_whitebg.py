"""White Background: the cut-out maths, the cache that keeps originals safe, the job, the download."""

from __future__ import annotations

import hashlib
import io
import time

import numpy as np
import pytest
from PIL import Image

from depop_seller import whitebg
from depop_seller.apply import apply_batch
from depop_seller.group import decisions_to_rows, group_local
from depop_seller.manifest import read_manifest, write_manifest
from depop_seller.review import ReviewServer, ReviewSession
from depop_seller.scan import scan_batch


def centre_mask(_im) -> np.ndarray:
    """Stands in for the network: the middle of the picture is the garment, as in conftest's photos."""
    m = np.zeros((whitebg.NET_SIZE, whitebg.NET_SIZE), dtype=np.float32)
    n = whitebg.NET_SIZE
    m[n // 6:5 * n // 6, n // 4:3 * n // 4] = 1.0
    return m


@pytest.fixture(autouse=True)
def switched_on(monkeypatch):
    """The feature is off in the app (config.WHITE_BACKGROUND); these tests exercise it switched on."""
    monkeypatch.setattr("depop_seller.config.WHITE_BACKGROUND", True)


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(whitebg, "predict_mask", centre_mask)
    monkeypatch.setattr(whitebg, "runtime_available", lambda: True)
    monkeypatch.setattr(whitebg, "model_ready", lambda: True)


def _session(batch) -> ReviewSession:
    photos = scan_batch(batch)
    write_manifest(batch.manifest, decisions_to_rows(photos, group_local(batch, photos)))
    return ReviewSession(batch, read_manifest(batch.manifest))


def _wait(server: ReviewServer, batch: str) -> dict:
    for _ in range(200):
        st = server.white_state[batch]
        if not st["running"]:
            return st
        time.sleep(0.05)
    raise AssertionError("the white-background job never finished")


def test_garment_lands_on_pure_white_and_is_centred():
    im = Image.new("RGB", (400, 300), (120, 110, 100))
    im.paste((200, 20, 20), (50, 60, 150, 200))                      # a red garment off to one side
    alpha = np.zeros((300, 400), dtype=np.float32)
    alpha[60:200, 50:150] = 1.0
    out = whitebg.compose(im, alpha, canvas_px=200, margin=0.1)
    assert out.size == (200, 200)
    assert out.getpixel((2, 2)) == (255, 255, 255) and out.getpixel((197, 197)) == (255, 255, 255)
    assert out.getpixel((100, 100)) == (200, 20, 20)                  # garment colour kept, centre of canvas
    reds = np.argwhere(np.asarray(out)[..., 1] < 100)
    assert 15 <= reds[:, 0].min() and reds[:, 0].max() <= 185         # margin all round
    assert abs((reds[:, 1].min() + reds[:, 1].max()) / 2 - 100) <= 2


def test_strays_go_but_straps_and_the_second_half_of_a_set_stay():
    a = np.zeros((400, 400), dtype=np.float32)
    a[100:300, 100:300] = 1                 # the garment
    a[60:100, 180:190] = 1                  # a strap touching it
    a[20:30, 20:30] = 1                     # a far speck
    a[330:400, 20:120] = 1                  # feet: medium, cut off by the frame
    a[330:390, 250:390] = 1                 # the other half of a set: big-ish, inside the frame
    out = whitebg.drop_strays(a)
    assert out[200, 200] == 1 and out[80, 185] == 1 and out[360, 300] == 1
    assert out[25, 25] == 0 and out[380, 60] == 0


def test_a_photo_with_no_clothes_is_refused_not_turned_into_a_blank_square():
    im = Image.new("RGB", (100, 80), (10, 200, 10))
    with pytest.raises(ValueError, match="no clothes"):
        whitebg.compose(im, np.zeros((80, 100), dtype=np.float32), canvas_px=64)


def test_cut_out_is_cached_used_everywhere_and_can_be_undone(batch, ready):
    session = _session(batch)
    raw = batch.raw / "IMG_1001.jpg"
    before = raw.read_bytes()
    original = session.large_image("IMG_1001")
    assert original.parent.name == "large"

    server = ReviewServer()
    server.sessions[batch.batch] = session
    server.start_white(batch.batch, ["IMG_1001", "IMG_1001", "not-a-photo"], download=False)
    st = _wait(server, batch.batch)
    assert st["error"] is None and st["failed"] == [] and st["total"] == 1

    white = session.large_image("IMG_1001")
    assert white == batch.white / "IMG_1001.jpg" and white != original
    assert session.thumb_image("IMG_1001") == batch.white / "thumbs" / "IMG_1001.jpg"
    with Image.open(white) as im:
        assert im.size == (whitebg.CANVAS_PX, whitebg.CANVAS_PX) and im.getpixel((3, 3)) == (255, 255, 255)
    assert session.large_image("IMG_1002").parent.name == "large"          # others untouched
    photos = {p["stem"]: p for g in session.state()["items"] for p in g["photos"]}
    assert photos["IMG_1001"]["white"] > 0 and photos["IMG_1002"]["white"] == 0
    assert raw.read_bytes() == before                                       # the original is never modified

    assert session.restore_originals(["IMG_1001", "IMG_1002"]) == 1
    assert session.large_image("IMG_1001") == original
    assert session.thumb_image("IMG_1001").parent == batch.thumbs
    assert not any(batch.white.rglob("*.jpg"))
    assert session.state()["items"][0]["photos"][0]["white"] == 0


def test_export_writes_the_white_version_and_manifest_order_is_untouched(batch, ready):
    session = _session(batch)
    server = ReviewServer()
    server.sessions[batch.batch] = session
    order = [(r.stem, r.item_id, r.photo_no) for r in session.rows]
    server.start_white(batch.batch, ["IMG_1001"], download=False)
    _wait(server, batch.batch)
    apply_batch(batch, session.rows, force=True)
    with Image.open(batch.sort_image / "1_1.jpg") as im:
        assert im.getpixel((3, 3)) == (255, 255, 255)
    with Image.open(batch.sort_image / "1_2.jpg") as im:
        assert im.getpixel((3, 3)) != (255, 255, 255)                       # the grey floor of a normal photo
    assert order == [(r.stem, r.item_id, r.photo_no) for r in read_manifest(batch.manifest)]


def test_job_refuses_empty_selection_missing_model_without_consent_and_deleted_photos(batch, monkeypatch):
    session = _session(batch)
    server = ReviewServer()
    server.sessions[batch.batch] = session
    monkeypatch.setattr(whitebg, "runtime_available", lambda: True)
    monkeypatch.setattr(whitebg, "model_ready", lambda: False)
    with pytest.raises(ValueError):
        server.start_white(batch.batch, [], download=True)
    with pytest.raises(RuntimeError, match="downloaded first"):
        server.start_white(batch.batch, ["IMG_1001"], download=False)
    session.rows[0].deleted = True
    with pytest.raises(ValueError):
        server.start_white(batch.batch, ["IMG_1001"], download=True)         # deleted = not for sale
    assert server.white_status(batch.batch)["model"] == {"runtime": True, "ready": False, "mb": whitebg.MODEL_MB}


def test_a_running_job_keeps_the_app_open_and_one_bad_photo_does_not_stop_the_rest(batch, ready, monkeypatch):
    session = _session(batch)
    server = ReviewServer()
    server.sessions[batch.batch] = session
    real = whitebg.make_white

    def flaky(src, dst, thumb, **kw):
        if src.stem == "IMG_1002":
            raise ValueError("cannot read")
        time.sleep(0.05)
        return real(src, dst, thumb, **kw)

    monkeypatch.setattr(whitebg, "make_white", flaky)
    server.start_white(batch.batch, ["IMG_1001", "IMG_1002", "IMG_1003"], download=False)
    assert server.busy() == "cutting out photos"
    with pytest.raises(RuntimeError, match="already"):
        server.start_white(batch.batch, ["IMG_1001"], download=False)
    st = _wait(server, batch.batch)
    assert st["failed"] == ["IMG_1002"] and "IMG_1002" in st["error"]
    assert sorted(p.stem for p in batch.white.glob("*.jpg")) == ["IMG_1001", "IMG_1003"]


def test_replacing_a_photo_drops_its_stale_cut_out(batch, ready):
    session = _session(batch)
    server = ReviewServer()
    server.sessions[batch.batch] = session
    server.start_white(batch.batch, ["IMG_1001"], download=False)
    _wait(server, batch.batch)
    server.add_photo(batch.batch, "IMG_1001.jpg", (batch.raw / "IMG_1002.jpg").read_bytes(), replace=True)
    assert not (batch.white / "IMG_1001.jpg").exists()


def test_switched_off_the_app_hides_it_refuses_it_and_shows_originals(batch, ready, monkeypatch):
    """With WHITE_BACKGROUND off, cut-outs made while it was on are ignored (but kept on disk), so
    the review page, the Sell page, the Depop upload and the export all use the original photos."""
    session = _session(batch)
    server = ReviewServer()
    server.sessions[batch.batch] = session
    server.start_white(batch.batch, ["IMG_1001"], download=False)
    _wait(server, batch.batch)
    assert session.large_image("IMG_1001").parent.name == "white"

    monkeypatch.setattr("depop_seller.config.WHITE_BACKGROUND", False)
    state = session.state()
    assert state["white_enabled"] is False
    assert all(p["white"] == 0 for g in state["items"] for p in g["photos"])
    assert session.large_image("IMG_1001").parent.name == "large"
    assert session.thumb_image("IMG_1001").parent == batch.thumbs
    with pytest.raises(RuntimeError, match="switched off"):
        server.start_white(batch.batch, ["IMG_1002"], download=True)
    apply_batch(batch, session.rows, force=True)
    with Image.open(batch.sort_image / "1_1.jpg") as im:
        assert im.getpixel((3, 3)) != (255, 255, 255)                      # the original's grey floor
    assert (batch.white / "IMG_1001.jpg").is_file()                        # nothing deleted


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_model_download_is_verified_and_never_half_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("depop_seller.config.machine_config_file", lambda: tmp_path / "config.json")
    payload = b"pretend onnx" * 1000
    monkeypatch.setattr(whitebg, "MODEL_BYTES", len(payload))
    monkeypatch.setattr(whitebg, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    asked: list[str] = []

    def fake_open(req, timeout=0):
        asked.append(req.full_url)
        return FakeResponse(fake_open.data)

    monkeypatch.setattr(whitebg.urllib.request, "urlopen", fake_open)

    fake_open.data = payload[:-5] + b"XXXXX"                               # same size, wrong bytes
    with pytest.raises(RuntimeError, match="does not match"):
        whitebg.download_model()
    assert not whitebg.model_path().exists() and not list(whitebg.model_path().parent.glob("*.part"))

    seen: list[int] = []
    fake_open.data = payload
    whitebg.download_model(lambda got, total: seen.append(got))
    assert whitebg.model_ready() and seen[-1] == len(payload)
    assert set(asked) == {whitebg.MODEL_URL}                               # only ever the pinned address
    whitebg.download_model()                                               # already there: no second download
    assert len(asked) == 2

    monkeypatch.setattr(whitebg, "MODEL_URL", "https://example.com/evil.onnx")
    whitebg.model_path().unlink()
    with pytest.raises(RuntimeError, match="unexpected address"):
        whitebg.download_model()
