"""Paths, constants, and secret loading. Nothing here touches the network.

Two folders, kept apart on purpose:

* the **app folder** (`PROJECT_ROOT`) is the software - downloaded, updated or replaced freely,
  and holds nothing of the seller's;
* the **data folder** (`DATA_DIR`, `~/DepopSeller` by default) holds everything personal: the
  photos and their grouping, the listings database, the house style and the API key.

That split is what makes moving to another computer one step: copy the data folder across, install
the app from wherever, and the two find each other again. `DEPOP_SELLER_DATA` overrides the
location, or `data_dir` in the per-machine config file if the folder lives somewhere else.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Depop Seller"


def bundled_runtime() -> bool:
    """True when the app runs on the Python that the Windows installer ships, which sits in
    `runtime\\` next to the app folder. Such an install has no .venv and no pip, and the installer
    owns its shortcuts; a manual install runs from a .venv inside the app folder."""
    try:
        return Path(sys.executable).resolve().parent == (PROJECT_ROOT.parent / "runtime").resolve()
    except OSError:
        return False


def machine_config_file() -> Path:
    """Per-machine settings - only where the data folder is. Never copied between computers."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "depop-seller"
    return base / "config.json"


def default_data_dir() -> Path:
    return Path.home() / "DepopSeller"


def resolve_data_dir() -> Path:
    """Where this machine keeps the seller's data: env var, then the machine config, then home."""
    override = os.environ.get("DEPOP_SELLER_DATA", "").strip()
    if override:
        return Path(override).expanduser()
    config = machine_config_file()
    if config.is_file():
        try:
            saved = json.loads(config.read_text(encoding="utf-8")).get("data_dir")
        except (ValueError, OSError):
            saved = None
        if saved:
            return Path(saved).expanduser()
    return default_data_dir()


def set_data_dir(folder: Path) -> Path:
    """Remember a data folder for this machine (the folder itself is never moved here)."""
    config = machine_config_file()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"data_dir": str(folder)}, indent=2) + chr(10), encoding="utf-8")
    return folder


DATA_DIR = resolve_data_dir()
PRODUCT_IMAGE_DIR = Path(os.environ.get("DEPOP_SELLER_PRODUCT_DIR", DATA_DIR / "product_image"))
DB_PATH = DATA_DIR / "depop_seller.db"
STYLE_FILE = DATA_DIR / "description_style.md"                  # the seller's own
STYLE_TEMPLATE = PROJECT_ROOT / "description_style.example.md"  # ships with the app
STYLE_HISTORY = DATA_DIR / "style_history"
ENV_FILE = DATA_DIR / ".env"


# What used to live in the app folder, and where it belongs now. Kept in this order so the big
# one moves first: on the same drive every move is a rename, so it is instant either way.
MOVED_INTO_DATA_DIR = (
    ("product_image", lambda: PRODUCT_IMAGE_DIR),
    ("depop_seller.db", lambda: DB_PATH),
    ("description_style.md", lambda: STYLE_FILE),
    ("style_history", lambda: STYLE_HISTORY),
    (".env", lambda: ENV_FILE),
)


def migrate_into_data_dir() -> list[str]:
    """Move an older install's data out of the app folder, once. Never overwrites anything."""
    moved = []
    for name, target_of in MOVED_INTO_DATA_DIR:
        old, new = PROJECT_ROOT / name, target_of()
        if not old.exists() or new.exists():
            continue
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))     # a rename when both are on one drive
        moved.append(name)
    return moved


def _log_file() -> Path:
    """Where the app writes its messages when it runs without a window."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Depop Seller"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
        return base / "Depop Seller.log"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "depop-seller"
    return base / "app.log"


LOG_FILE = _log_file()

RAW_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
THUMB_SIZE = 512            # long edge of the cached thumbnails sent to the model / review page
OUTPUT_MAX_PX = 2048        # long edge of the JPEGs written to sort_image/
OUTPUT_JPEG_QUALITY = 90
MAX_PHOTOS_PER_ITEM = 8     # Depop's listing limit
# White Background (whitebg.py) stays in the code but is switched off: the cut-outs were not good
# enough to sell with. Off means no checkboxes or buttons on the Review page, /white refused, and
# cut-outs made while it was on are ignored (left on disk) so originals are shown and uploaded.
WHITE_BACKGROUND = False

DEFAULT_MODEL = "claude-opus-5"

# Photo views, in Depop's photo-slot order (Cover is simply an item's first photo).
VIEWS = ("front", "back", "side", "label", "detail", "flaw", "other")
MODEL_VIEWS = VIEWS


@dataclass(frozen=True)
class BatchPaths:
    """Everything the pipeline reads or writes for one batch folder."""

    batch: str
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw_image"

    @property
    def thumbs(self) -> Path:
        return self.root / "thumbs"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def white(self) -> Path:
        """White-background versions (2048 px, and 512 px in white/thumbs/), named like the photo's stem."""
        return self.cache / "white"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.csv"

    @property
    def review_html(self) -> Path:
        return self.root / "review.html"

    @property
    def sort_image(self) -> Path:
        return self.root / "sort_image"


# Batches live in PRODUCT_IMAGE_DIR unless the seller chose another folder for one (the Desktop,
# Downloads, an external drive...). Those are listed here by name - the name is still what the
# whole app, the URLs and the database know a batch by, so it stays unique across both places.
# The list sits inside the default batches folder, so it travels with the data folder; the
# batches it points to do not, since they live wherever the seller put them.
ELSEWHERE_FILE = "batches-elsewhere.json"


def _elsewhere_file() -> Path:
    return PRODUCT_IMAGE_DIR / ELSEWHERE_FILE


def batches_elsewhere() -> dict[str, Path]:
    """name -> batch folder, for every batch kept outside the default folder (found or not)."""
    try:
        saved = json.loads(_elsewhere_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): Path(v) for k, v in (saved.get("batches") or {}).items() if v}


def last_batch_location() -> Path:
    """The folder the last new batch went into, so the next one offers the same place."""
    try:
        saved = json.loads(_elsewhere_file().read_text(encoding="utf-8")).get("last_location")
    except (OSError, ValueError):
        saved = None
    return Path(saved) if saved and Path(saved).is_dir() else PRODUCT_IMAGE_DIR


def _save_elsewhere(batches: dict[str, Path], last_location: Path | None = None) -> None:
    f = _elsewhere_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    data = {"batches": {k: str(v) for k, v in sorted(batches.items())},
            "last_location": str(last_location) if last_location else current.get("last_location")}
    tmp = f.with_name(f.name + ".part")
    tmp.write_text(json.dumps(data, indent=2) + chr(10), encoding="utf-8")
    tmp.replace(f)


def remember_batch(name: str, root: Path) -> None:
    """Note a batch that lives outside the default folder (and that folder as the next default)."""
    batches = batches_elsewhere()
    batches[name] = Path(root)
    _save_elsewhere(batches, last_location=Path(root).parent)


def forget_batch(name: str) -> None:
    """Take a batch off the list. Its folder and photos are never touched."""
    batches = batches_elsewhere()
    if batches.pop(name, None) is not None:
        _save_elsewhere(batches)


def rename_batch_record(old: str, new: str, root: Path) -> None:
    """A batch kept elsewhere was renamed in place: list it under its new name."""
    batches = batches_elsewhere()
    if batches.pop(old, None) is not None:
        batches[new] = Path(root)
        _save_elsewhere(batches)


def set_last_batch_location(folder: Path) -> None:
    _save_elsewhere(batches_elsewhere(), last_location=Path(folder))


def is_batch_folder(root: Path) -> bool:
    return (Path(root) / "raw_image").is_dir()


def batch_dirs() -> list[Path]:
    """Every batch folder, oldest first: the default folder's and the ones kept elsewhere. Names
    are free text, so "newest" means the folder whose photos were added or changed most
    recently - not the alphabetically last name."""
    dirs: dict[str, Path] = {}
    if PRODUCT_IMAGE_DIR.is_dir():
        dirs = {p.name: p for p in PRODUCT_IMAGE_DIR.iterdir() if is_batch_folder(p)}
    for name, root in batches_elsewhere().items():
        if name not in dirs and root.name == name and is_batch_folder(root):
            dirs[name] = root
    return sorted(dirs.values(), key=lambda p: ((p / "raw_image").stat().st_mtime, p.name))


def missing_batches() -> dict[str, Path]:
    """Batches on the elsewhere list whose folder is gone - moved, deleted, or on a drive that is
    not plugged in."""
    return {name: root for name, root in batches_elsewhere().items() if not is_batch_folder(root)}


def batch_paths(batch: str | None = None) -> BatchPaths:
    """Paths for a batch folder; with no name, the most recently used batch."""
    if not batch:
        candidates = batch_dirs()
        if not candidates:
            raise FileNotFoundError(f"no batch folders with a raw_image/ subfolder under {PRODUCT_IMAGE_DIR}")
        batch = candidates[-1].name
    root = PRODUCT_IMAGE_DIR / batch
    if not is_batch_folder(root):
        elsewhere = batches_elsewhere().get(batch)
        if elsewhere is not None:
            if not is_batch_folder(elsewhere):
                raise FileNotFoundError(f"the folder of {batch} is not at {elsewhere} any more - "
                                        "was it moved, or is its drive unplugged?")
            root = elsewhere
        elif is_batch_folder(Path(batch)):                  # a folder path also works (the CLI)
            root = Path(batch)
    if not is_batch_folder(root):
        raise FileNotFoundError(f"no raw_image folder under {root}")
    return BatchPaths(batch=root.name, root=root)


def load_api_key() -> str | None:
    """ANTHROPIC_API_KEY from the environment, else from the .env file in the data folder.

    The .env value is read without exporting it: the key must stay out of this process's
    environment so that child processes (the Claude Code CLI drafting descriptions on the
    subscription) can never inherit it and bill the API by accident.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    for candidate in (ENV_FILE, PROJECT_ROOT / ".env"):        # the app folder is the old home
        if key:
            break
        key = (dotenv_values(candidate).get("ANTHROPIC_API_KEY") or "").strip()
    return key or None
