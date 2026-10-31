"""White-background photos: cut the clothes out of a photo and put them on plain white, the way
shop catalogues do.

Runs entirely on this computer with a segmentation model (BiRefNet, the tiny build) under
onnxruntime. The model file is fetched once, from GitHub, and only after the user has said yes in
the Review page; after that no network is involved. Nothing here touches raw_image/: the result is a
JPEG in the batch's cache/white/ folder that the rest of the app prefers over the original when it
exists (see `ReviewSession.large_image` / `thumb_image`), and deleting it restores the original.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

from . import config

log = logging.getLogger(__name__)

MODEL_NAME = "birefnet-tiny"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx"
MODEL_PREFIX = "https://github.com/danielgatis/rembg/releases/download/"
MODEL_SHA256 = "5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333"
MODEL_BYTES = 224_005_088
MODEL_MB = 224                      # what the page says before downloading

NET_SIZE = 1024                     # the network's fixed input size
CANVAS_PX = 2048                    # output is a square canvas, like Depop's own crops
MARGIN = 0.06                       # white space around the garment, as a share of the canvas
JPEG_QUALITY = 88


class ModelUnavailable(RuntimeError):
    """The cut-out model or its runtime is missing (the page offers to fetch it)."""


def model_path() -> Path:
    """Next to the per-machine settings, not in the data folder: it is the app's, not the seller's."""
    return config.machine_config_file().parent / "models" / f"{MODEL_NAME}.onnx"


def runtime_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def model_ready() -> bool:
    p = model_path()
    return p.is_file() and p.stat().st_size == MODEL_BYTES


# ---- getting the model -----------------------------------------------------------------

def download_model(progress: Callable[[int, int], None] | None = None) -> Path:
    """Fetch the model once. Only the one pinned URL is ever opened, the size is bounded and the
    bytes must match the pinned hash, so a tampered or truncated download is never kept."""
    dest = model_path()
    if model_ready():
        return dest
    if not MODEL_URL.startswith(MODEL_PREFIX):
        raise RuntimeError("refusing to download the model from an unexpected address")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    got = 0
    req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "depop-seller"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, part.open("wb") as out:
            while chunk := resp.read(1 << 16):
                got += len(chunk)
                if got > MODEL_BYTES * 2:
                    raise RuntimeError("the download is far larger than expected")
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(got, MODEL_BYTES)
        if digest.hexdigest() != MODEL_SHA256:
            raise RuntimeError("the downloaded model does not match the expected file; nothing was installed")
        part.replace(dest)
    except OSError as e:
        raise RuntimeError(f"could not download the cut-out model ({e}); check the internet connection") from e
    finally:
        part.unlink(missing_ok=True)
    log.info("cut-out model installed: %s (%d bytes)", dest, got)
    return dest


# ---- the cut-out ------------------------------------------------------------------------

_session = None


def _load_session():
    global _session
    if _session is None:
        if not runtime_available():
            raise ModelUnavailable("the cut-out library (onnxruntime) is not installed")
        if not model_ready():
            raise ModelUnavailable("the cut-out model has not been downloaded yet")
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _session = ort.InferenceSession(str(model_path()), sess_options=opts, providers=["CPUExecutionProvider"])
    return _session


def predict_mask(im: Image.Image) -> np.ndarray:
    """Foreground probability, 0..1, at the network's own resolution (NET_SIZE square)."""
    sess = _load_session()
    small = np.asarray(im.convert("RGB").resize((NET_SIZE, NET_SIZE), Image.LANCZOS), dtype=np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = ((small - mean) / std).transpose(2, 0, 1)[None].astype(np.float32)
    logits = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    return 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))


def _box(a: np.ndarray, r: int) -> np.ndarray:
    """Mean over a (2r+1) square window, by cumulative sums."""
    h, w = a.shape
    pad = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    k = 2 * r + 1
    s = c[k:k + h, k:k + w] - c[:h, k:k + w] - c[k:k + h, :w] + c[:h, :w]
    return s / float(k * k)


def _guided(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """Guided filter (He et al.): pulls a soft mask onto the edges of the photo itself."""
    mg, ms = _box(guide, r), _box(src, r)
    cov = _box(guide * src, r) - mg * ms
    var = _box(guide * guide, r) - mg * mg
    a = cov / (var + eps)
    b = ms - a * mg
    return _box(a, r) * guide + _box(b, r)


def refine_alpha(im: Image.Image, mask: np.ndarray) -> np.ndarray:
    """Turn the network's 1024 px mask into a full-size alpha with crisp, photo-following edges."""
    w, h = im.size
    m = np.asarray(Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC),
                   dtype=np.float32) / 255.0
    guide = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    r = max(4, round(max(w, h) / 180))
    m = np.clip(_guided(guide, m, r, 1e-3), 0, 1)
    # a soft threshold: the model's halo becomes a sharp edge, faint specks vanish
    return drop_strays(np.clip((m - 0.35) / 0.35, 0, 1) ** 1.2)


def _components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Label 4-connected regions of a small boolean mask (0 = background). No scipy needed."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    n = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if labels[y0, x0]:
            continue
        n += 1
        labels[y0, x0] = n
        stack = [(y0, x0)]
        while stack:
            y, x = stack.pop()
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not labels[yy, xx]:
                    labels[yy, xx] = n
                    stack.append((yy, xx))
    return labels, n


def drop_strays(alpha: np.ndarray, work_px: int = 192) -> np.ndarray:
    """Remove things that are not the garment: the photographer's feet at the edge of a flat lay, a
    lamp beside a mannequin. The biggest region is the garment; a region is kept with it when it is
    close to it (a strap, a sleeve the model split off) or big and inside the frame (the other half
    of a two-piece set). Anything else - small, far away, or a big shape cut off by the frame - goes."""
    h, w = alpha.shape
    step = max(1, max(h, w) // work_px)
    small = alpha[::step, ::step] > 0.5
    labels, n = _components(small)
    if n <= 1:
        return alpha
    areas = np.bincount(labels.ravel(), minlength=n + 1)
    areas[0] = 0
    main = int(areas.argmax())
    near = labels == main
    for _ in range(3):                                     # "close" = within 3 working pixels
        grown = near.copy()
        grown[1:] |= near[:-1]; grown[:-1] |= near[1:]; grown[:, 1:] |= near[:, :-1]; grown[:, :-1] |= near[:, 1:]
        near = grown
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    keep = np.zeros(n + 1, dtype=bool)
    for k in range(1, n + 1):
        area = areas[k]
        keep[k] = (k == main or near[labels == k].any() or area >= 0.6 * areas[main]
                   or (area >= 0.1 * areas[main] and k not in edge))
    wanted = keep[labels]
    grown = wanted.copy()                                  # a margin, so the cut never bites the garment
    grown[1:] |= wanted[:-1]; grown[:-1] |= wanted[1:]; grown[:, 1:] |= wanted[:, :-1]; grown[:, :-1] |= wanted[:, 1:]
    full = np.asarray(Image.fromarray(grown.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)) > 0
    return alpha * full


def compose(im: Image.Image, alpha: np.ndarray, canvas_px: int = CANVAS_PX, margin: float = MARGIN) -> Image.Image:
    """The garment on pure white, centred and scaled to fill a square canvas."""
    ys, xs = np.where(alpha > 0.5)
    if len(xs) == 0:                      # a blank white picture would be worse than saying so
        raise ValueError("no clothes were found in this photo")
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    rgb = np.asarray(im.convert("RGB"), dtype=np.float32)
    a = alpha[..., None]
    flat = rgb * a + 255.0 * (1.0 - a)
    out = Image.fromarray(np.clip(flat + 0.5, 0, 255).astype(np.uint8))
    out = out.crop(box)
    inner = round(canvas_px * (1 - 2 * margin))
    scale = inner / max(out.size)
    out = out.resize((max(1, round(out.width * scale)), max(1, round(out.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGB", (canvas_px, canvas_px), (255, 255, 255))
    canvas.paste(out, ((canvas_px - out.width) // 2, (canvas_px - out.height) // 2))
    return canvas


def white_background(im: Image.Image, mask_fn: Callable[[Image.Image], np.ndarray] | None = None) -> Image.Image:
    """`im` (upright, RGB) -> the same photo with only the clothes, on white."""
    mask = (mask_fn or predict_mask)(im)
    return compose(im, refine_alpha(im, mask))


def make_white(src: Path, dst: Path, thumb_dst: Path, thumb_px: int = config.THUMB_SIZE,
               mask_fn: Callable[[Image.Image], np.ndarray] | None = None) -> None:
    """Cut out `src` (a photo of any size), write the 2048 px result to `dst` and its thumbnail."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        result = white_background(im, mask_fn)
    dst.parent.mkdir(parents=True, exist_ok=True)
    thumb_dst.parent.mkdir(parents=True, exist_ok=True)
    for path, image, quality in ((dst, result, JPEG_QUALITY), (thumb_dst, result.resize((thumb_px, thumb_px), Image.LANCZOS), 80)):
        tmp = path.with_name(path.name + ".part")
        image.save(tmp, "JPEG", quality=quality, optimize=True)
        tmp.replace(path)
