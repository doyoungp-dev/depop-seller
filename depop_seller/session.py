"""One batch on disk as the app works with it: its photos, its manifest (grouping, order, views)
and the safe names for batches and photos. Used by review.ReviewServer for every batch route."""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path

from . import config
from .apply import apply_batch, convert
from .config import MAX_PHOTOS_PER_ITEM, VIEWS, BatchPaths
from .manifest import Row, deleted, items, normalize, summary, unused, write_manifest

log = logging.getLogger(__name__)


PHOTO_SUFFIXES = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024          # one photo; a HEIC is about 4 MB
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _same_place_key(path: Path) -> str:
    """A folder's identity for comparing places: resolved, and case-blind where the OS is."""
    return os.path.normcase(str(Path(path).resolve()))


def check_batch_location(place: Path) -> None:
    """Refuse a folder no batch may live in: the app's own folder (an update or the installer
    replaces everything there, so the photos would go with it), or the inside of another batch."""
    here = Path(_same_place_key(place))
    app_folders = [config.PROJECT_ROOT] + ([config.PROJECT_ROOT.parent] if config.bundled_runtime() else [])
    for app in app_folders:
        if here == Path(_same_place_key(app)) or Path(_same_place_key(app)) in here.parents:
            raise ValueError("that folder is part of the Depop Seller app itself, which updates replace - "
                             "choose another place, such as Documents or the Desktop")
    for batch in config.batch_dirs():
        b = Path(_same_place_key(batch))
        if here == b or b in here.parents:
            raise ValueError(f"that folder is inside the batch {batch.name} - choose a place outside it")


def safe_batch_name(name: str) -> str:
    """A batch name is any label the seller likes, as long as it is a safe folder name."""
    name = (name or "").strip()
    if not name:
        raise ValueError("the batch needs a name")
    if len(name) > 60:
        raise ValueError("the name is too long (60 characters max)")
    if any(c in name for c in '\\/:*?"<>|') or any(ord(c) < 32 for c in name):
        raise ValueError('a name cannot contain \\ / : * ? " < > |')
    if name.startswith(".") or name != name.rstrip(". "):
        raise ValueError("a name cannot start with a dot or end with a dot or space")
    if name.split(".")[0].upper() in _RESERVED:
        raise ValueError(f"{name} is a reserved name on Windows")
    return name


def safe_photo_name(name: str) -> str:
    """The file name of an uploaded photo: a bare file name with a picture extension, never a path."""
    name = Path((name or "").replace("\\", "/")).name.strip()
    if not name or name.startswith("."):
        raise ValueError(f"bad photo name {name!r}")
    if Path(name).suffix.lower() not in PHOTO_SUFFIXES:
        raise ValueError(f"{name} is not a photo ({', '.join(sorted(PHOTO_SUFFIXES))})")
    return name


class ReviewSession:
    """One batch's rows plus the state of its background jobs."""

    def __init__(self, paths: BatchPaths, rows: list[Row]) -> None:
        self.paths = paths
        self.rows = rows
        self.lock = threading.Lock()
        self.apply_state: dict = {"running": False, "done": 0, "total": 0, "written": None, "error": None}
        self.manifest_mtime = self._mtime()

    def _mtime(self) -> int:
        return self.paths.manifest.stat().st_mtime_ns if self.paths.manifest.exists() else 0

    def _row(self, stem: str) -> Row | None:
        with self.lock:
            return next((r for r in self.rows if r.stem == stem), None)

    def original_large(self, stem: str):
        """Path of a 2048 px JPEG of the *original* photo, converting it once."""
        row = self._row(stem)
        if row is None:
            return None
        out = self.paths.cache / "large" / f"{stem}.jpg"
        if not out.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            convert(self.paths.raw / row.raw_file, out, max_px=2048, quality=85)
        return out

    def large_image(self, stem: str):
        """Path of the 2048 px JPEG the rest of the app shows and uploads: the white-background
        version when the seller made one, else the original converted once."""
        white = self.paths.white / f"{stem}.jpg"
        if config.WHITE_BACKGROUND and white.is_file() and self._row(stem) is not None:
            return white
        return self.original_large(stem)

    def white_stamps(self) -> dict[str, int]:
        """stem -> when its white-background version was made, for photos that have one. The page
        appends it to image URLs so a new cut-out replaces the cached picture."""
        folder = self.paths.white
        if not config.WHITE_BACKGROUND or not folder.is_dir():
            return {}
        return {p.stem: p.stat().st_mtime_ns // 1_000_000 for p in folder.glob("*.jpg")}

    def restore_originals(self, stems: list[str]) -> int:
        """Delete the white-background versions of these photos. The originals were never touched."""
        n = 0
        for stem in stems:
            if self._row(stem) is None:
                continue
            for f in (self.paths.white / f"{stem}.jpg", self.paths.white / "thumbs" / f"{stem}.jpg"):
                if f.is_file():
                    f.unlink()
                    n += f.parent.name != "thumbs"
        return n

    def thumb_image(self, stem: str):
        """Path of the 512 px thumbnail, making it from the original if it is not there.

        thumbs/ is a cache and is gitignored, so a batch folder copied from another computer (or
        one trimmed to save space) can arrive without it. Rebuilding beats showing broken tiles.
        """
        white = self.paths.white / "thumbs" / f"{stem}.jpg"
        if config.WHITE_BACKGROUND and white.is_file():
            return white
        out = self.paths.thumbs / f"{stem}.jpg"
        if out.is_file():
            return out
        row = self._row(stem)
        source = self.paths.raw / row.raw_file if row else None
        if source is None or not source.is_file():
            return None
        from .scan import make_thumbnail

        out.parent.mkdir(parents=True, exist_ok=True)
        make_thumbnail(source, out)
        log.info("rebuilt a missing thumbnail for %s", stem)
        return out

    # ---- state -------------------------------------------------------------------------

    @staticmethod
    def _photo(r: Row, white: dict[str, int]) -> dict:
        return {
            "seq": r.seq, "file": r.raw_file, "stem": r.stem, "gap": r.gap_s, "taken": r.taken_at,
            "view": r.view, "confidence": r.confidence, "note": r.note, "white": white.get(r.stem, 0),
        }

    def state(self) -> dict:
        white = self.white_stamps()
        with self.lock:
            grouped = items(self.rows)
            count = sum(1 for p in self.paths.sort_image.glob("*.jpg")) if self.paths.sort_image.is_dir() else 0
            return {
                "batch": self.paths.batch,
                "views": list(VIEWS),
                "max_photos": MAX_PHOTOS_PER_ITEM,
                "white_enabled": config.WHITE_BACKGROUND,
                "items": [{"id": i, "photos": [self._photo(r, white) for r in g]} for i, g in grouped.items()],
                "unused": [self._photo(r, white) for r in unused(self.rows)],
                "deleted": [self._photo(r, white) for r in deleted(self.rows)],
                "summary": summary(self.rows),
                "sort_image_count": count,
                "manifest": str(self.paths.manifest),
            }

    # ---- save --------------------------------------------------------------------------

    def _check_unchanged(self) -> None:
        """Refuse to write over a manifest that changed on disk since this session loaded it."""
        if self._mtime() != self.manifest_mtime:
            raise FileExistsError(
                "manifest.csv was changed by something else (another review window or a tool) since this "
                "page loaded it. Close other review windows, then Reload this page and redo your edits.")

    def _write_manifest(self) -> None:
        normalize(self.rows)
        if self.paths.manifest.exists():
            shutil.copy2(self.paths.manifest, self.paths.manifest.with_name("manifest.bak.csv"))
        write_manifest(self.paths.manifest, self.rows)
        self.manifest_mtime = self._mtime()

    def save(self, payload: dict) -> dict:
        with self.lock:
            self._check_unchanged()
            by_seq = {r.seq: r for r in self.rows}
            # Validate the whole payload before touching a single row.
            assign: dict[int, tuple[int, int, bool, bool]] = {}   # seq -> (item, photo_no, skip, deleted)
            placements = [(item_no, photo_no, seq, False)
                          for item_no, seqs in enumerate(payload.get("items") or [], 1)
                          for photo_no, seq in enumerate(seqs, 1)]
            placements += [(0, 0, seq, False) for seq in payload.get("unused") or []]
            placements += [(0, 0, seq, True) for seq in payload.get("deleted") or []]
            for item_no, photo_no, seq, is_deleted in placements:
                seq = int(seq)
                if seq not in by_seq:
                    raise ValueError(f"unknown photo seq {seq}")
                if seq in assign:
                    raise ValueError(f"photo seq {seq} appears more than once")
                assign[seq] = (item_no, photo_no, item_no == 0, is_deleted)
            if set(assign) != set(by_seq):
                raise ValueError("every photo must appear exactly once across items, unused and deleted")
            views = {int(seq): view for seq, view in (payload.get("views") or {}).items()}
            for seq, view in views.items():
                if seq not in by_seq or view not in VIEWS:
                    raise ValueError(f"bad view {view!r} for photo seq {seq}")

            for seq, (item_no, photo_no, skip, is_deleted) in assign.items():
                r = by_seq[seq]
                r.item_id, r.photo_no, r.skip, r.deleted = item_no, photo_no, skip, is_deleted
            for seq, view in views.items():
                by_seq[seq].view = view
            self._write_manifest()
            log.info("saved %s: %s", self.paths.manifest.name, summary(self.rows))
        return self.state()

    def reorder_item(self, item_id: int, seqs: list[int]) -> list[Row]:
        """Set one item's photo order (the Sell page's drag and drop): `seqs` is the item's
        photos in the new order, first = cover. Writes manifest.csv like save()."""
        with self.lock:
            self._check_unchanged()
            group = items(self.rows).get(item_id)
            if not group:
                raise LookupError(f"item {item_id} not found")
            if sorted(seqs) != sorted(r.seq for r in group) or len(set(seqs)) != len(seqs):
                raise ValueError(f"the new order must list each of item {item_id}'s photos exactly once")
            by_seq = {r.seq: r for r in group}
            for n, seq in enumerate(seqs, 1):
                by_seq[seq].photo_no = n
            self._write_manifest()
            log.info("item %s reordered: %s", item_id, [by_seq[s].stem for s in seqs])
            return [by_seq[s] for s in seqs]

    # ---- apply -------------------------------------------------------------------------

    def start_apply(self, force: bool) -> None:
        with self.lock:
            if self.apply_state["running"]:
                raise RuntimeError("apply is already running")
            leftovers = [p for p in self.paths.sort_image.iterdir() if p.is_file()] if self.paths.sort_image.is_dir() else []
            if leftovers and not force:
                raise FileExistsError(f"sort_image already contains {len(leftovers)} file(s)")
            kept = sum(1 for r in self.rows if not r.skip)
            self.apply_state = {"running": True, "done": 0, "total": kept, "written": None, "error": None}
            rows = list(self.rows)

        def progress(done: int, total: int) -> None:
            self.apply_state["done"], self.apply_state["total"] = done, total

        def work() -> None:
            try:
                n = apply_batch(self.paths, rows, force=force, progress=progress)
                self.apply_state.update(written=n)
            except Exception as e:  # surfaced to the page; the CLI log has the traceback
                log.exception("apply failed")
                self.apply_state.update(error=str(e))
            finally:
                self.apply_state["running"] = False

        threading.Thread(target=work, name="apply", daemon=True).start()
