"""The app's web side: the HTTP request handler, the local server and `serve()`.
Stdlib only, on 127.0.0.1. Every batch-specific route takes ?batch=<folder name>; the work
itself is done by review.ReviewServer, one per running app.

saves manifests, runs the grouping step for new batches, and runs the apply step.
Stdlib only. Every batch-specific route takes ?batch=<folder name>.

Routes:
  GET  /                      the page (static/review.html)
  GET  /icon.png              the app icon, used as the favicon and so as the app window's icon
  GET  /app.css               the stylesheet every page shares
  GET  /batches/cover         ?batch= : a 512 px JPEG of the batch's first photo (made on demand)
  POST /batches/photos        ?batch=&name= : the raw bytes of one photo, written into raw_image/
  POST /batches/import        {batch, folder}: copy every photo from a folder on this computer
  POST /batches/rename        {name, to}: rename a batch folder and its rows in the DB
  GET  /style                 the description style page (static/style.html)
  GET  /style/state           the style text, its history and any running rewrite
  POST /style/save            {text}: write description_style.md (previous version kept)
  POST /style/instruct        {instruction}: ask Claude Code to rewrite the style; poll /style/status
  GET  /style/status          the proposed rewrite: running / summary / diff / markdown
  POST /style/restore         {name}: bring a previous version back
  GET  /version               the app's version and process, and whether the code on disk is newer
  POST /updates/check         ask GitHub whether a newer release exists (only when the user asks)
  POST /updates/install       download, check and install it in a background thread, then restart
  GET  /updates/status        {running, phase, error, installed, restart}
  POST /quit                  stop the app (the desktop icon runs it without a window)
  POST /closing               the app window went away: stop too, unless something is still running
  POST /settings/share        write a zip of the app to the Desktop, to give to someone else
  GET  /settings              the settings page (static/settings.html)
  GET  /settings/state        API key status (masked), Claude Code status, paths
  POST /settings/key          {key}: write ANTHROPIC_API_KEY into .env
  POST /settings/key/test     check the key with a free models.list call
  POST /settings/login        sign Claude Code in through the browser (`claude auth login`, no window)
  GET  /settings/login/status {running, url, ok, detail} of that sign-in
  POST /settings/login/code   {code}: the code the sign-in page shows when the link had to be opened by hand
  POST /settings/login/terminal  the fallback: a terminal window where /login can be typed
  POST /settings/login/test   `claude auth status`: signed in, and to which plan
  GET  /settings/uninstall/plan  ?delete_data=0|1 : what Delete Depop Seller would remove, and what stays
  POST /settings/uninstall    {"delete_data"}: start the delete (uninstall.py) and close the app
  GET  /batches               every batch folder with its status, plus API key availability
  GET  /state?batch=          current grouping as JSON (404 if the batch has no manifest yet)
  GET  /thumbs/<file>?batch=  cached thumbnail
  GET  /large/<file>?batch=   2048 px JPEG (the white-background version if there is one), made on first request
  GET  /white/status?batch=   {running, phase, done, total, error, model, white: {stem: stamp}}
  POST /white?batch=          {"stems": [...], "download": bool}: put the clothes on white (background thread)
  POST /white/restore?batch=  {"stems": [...]}: bring the original photos back
  POST /save?batch=           {"items": [[seq, ...], ...], "unused": [seq, ...], "deleted": [seq, ...],
                               "views": {seq: view}}  (deleted = not for sale; raw files are never touched)
  POST /group?batch=          {"model": ...}  -> scan + Claude grouping in a background thread
  GET  /group/status?batch=   {"running", "phase", "done", "total", "cost", "error"}
  POST /apply?batch=          {"force": bool}  -> apply step in a background thread
  GET  /apply/status?batch=   {"running", "done", "total", "written", "error"}
  GET  /hub                   the batches page (static/hub.html): every date folder, its status, Review / Sell links
  POST /batches/new           {"name", "location"?} -> creates <location or product_image>/<name>/raw_image
  POST /batches/choose-folder {"purpose": "new"|"import", "start"?} -> the system's folder chooser: {"folder"|null}
  POST /batches/forget        {"name"} -> takes a batch kept elsewhere off the list (nothing on disk changes)
  POST /batches/delete        {"name"} -> the batch folder goes to the Recycle Bin / Trash, its rows leave the DB
  GET  /shop                  the Shop page (static/shop.html): what is selling and what has sold on Depop
  GET  /shop/state            both lists as last read, with totals worked out now (shop.state)
  POST /shop/request          {"what": "selling"|"sold"|"both"} -> a one-time pass for the Chrome helper
  POST /shop/import           from the helper only: {token, selling?, sold?, sold_since?, counts?, error?} - what it read
  GET  /shop/export?list=     selling|sold as last refreshed, as a CSV download (no pictures)
  POST /batches/open          {"name"} -> opens the batch's raw_image folder in Explorer / Finder
  GET  /sell                  the selling page (static/sell.html)
  GET  /sell/state?batch=     items with photos + listing status/description from the DB (synced from the manifest)
  POST /sell/open?batch=&item=   open Depop's listing form in the listing browser with the item's photos
  GET  /sell/status?batch=&item= progress of that job
  POST /sell/item?batch=&item=   {"status"?, "description"?, "depop_url"?} -> saved to the DB
  GET  /sell/photos?batch=&item= the item's upload list for the Chrome extension: [{name, url}] (max 8) + description
  POST /sell/describe?batch=     {"items": [id, ...], "facts": {id: text}?} -> drafts descriptions in a background thread
  GET  /sell/describe/status?batch=  per-item drafting status

Responses carry CORS headers so the helper extension can call this server from depop.com.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from . import __version__, desktop
from .config import DEFAULT_MODEL, batch_paths
from .review import TEST_FORM, ReviewServer, code_mtime
from .session import MAX_UPLOAD_BYTES

log = logging.getLogger(__name__)


# The helper extension runs on depop.com and fetches the item's photos and description from this
# server, so those routes need CORS - and only those. Everything else (including every route that
# writes) stays same-origin, or any web page the seller has open could drive the server.
DEPOP_ORIGINS = ("https://www.depop.com", "https://depop.com")
CORS_PATHS = ("/sell/photos", "/sell/item", "/large/", "/shop/import")


class ReviewHandler(BaseHTTPRequestHandler):
    server_state: ReviewServer  # injected via functools.partial

    def __init__(self, server_state: ReviewServer, *args, **kwargs) -> None:
        self.server_state = server_state
        super().__init__(*args, **kwargs)

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        log.debug("%s " + fmt, self.address_string(), *args)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        allowed = self._cors_origin()
        if allowed:
            self.send_header("Access-Control-Allow-Origin", allowed)
        self.end_headers()
        self.wfile.write(body)

    def _cors_origin(self) -> str | None:
        """The Origin to allow for this request: depop.com, on the routes the extension uses."""
        origin = self.headers.get("Origin")
        path = urlsplit(self.path).path
        return origin if origin in DEPOP_ORIGINS and path.startswith(CORS_PATHS) else None

    def _foreign_origin(self) -> bool:
        """True when a POST comes from a page that is not ours and not the extension's depop.com."""
        origin = self.headers.get("Origin")
        if origin is None:                        # the extension's fetch and our own pages on same-origin
            return False
        if origin in DEPOP_ORIGINS:
            return not urlsplit(self.path).path.startswith(CORS_PATHS)
        if origin.startswith("chrome-extension://"):
            # the helper's background script hands over the Shop lists (which still need the
            # one-time pass from /shop/request, so another extension gets nowhere with this) and
            # marks an item "opened" after the Depop button - the two writes it makes, and only those
            return urlsplit(self.path).path not in ("/shop/import", "/sell/item")
        host = urlsplit(origin).hostname
        return host not in ("127.0.0.1", "localhost", "::1")

    def do_OPTIONS(self) -> None:  # noqa: N802 - CORS preflight for the extension's POSTs
        allowed = self._cors_origin()
        self.send_response(HTTPStatus.NO_CONTENT if allowed else HTTPStatus.FORBIDDEN)
        if allowed:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def _text(self, text: str, status: HTTPStatus) -> None:
        self._send(status, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _route(self) -> tuple[str, str | None]:
        parts = urlsplit(self.path)
        values = parse_qs(parts.query).get("batch")
        return parts.path, (values[0] if values else None)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path, batch = self._route()
        self.server_state.note_request()
        try:
            if path == "/":
                page = (files("depop_seller") / "static" / "review.html").read_bytes()
                self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
            elif path == "/sell":
                page = (files("depop_seller") / "static" / "sell.html").read_bytes()
                self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
            elif path == "/hub":
                page = (files("depop_seller") / "static" / "hub.html").read_bytes()
                self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
            elif path == "/shop":
                page = (files("depop_seller") / "static" / "shop.html").read_bytes()
                self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
            elif path == "/shop/state":
                from . import shop
                self._json(shop.state() | {"refreshing": self.server_state.shop_requests.running()})
            elif path == "/shop/export":
                from . import shop
                kind = (parse_qs(urlsplit(self.path).query).get("list") or [""])[0]
                try:
                    name, body = shop.export_csv(kind)
                except ValueError as e:
                    self._text(str(e), HTTPStatus.BAD_REQUEST)
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')   # Chrome saves it to Downloads
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/style":
                page = (files("depop_seller") / "static" / "style.html").read_bytes()
                self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
            elif path == "/version":
                self._json({"version": __version__, "pid": os.getpid(),
                            "started": self.server_state.started_at.strftime("%Y-%m-%d %H:%M"),
                            "stale": code_mtime() > self.server_state.code_mtime,
                            "platform": {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux")})
            elif path == "/updates/status":
                self._json(self.server_state.update_job)
            elif path == "/settings":
                page = (files("depop_seller") / "static" / "settings.html").read_bytes()
                self._send(HTTPStatus.OK, page, "text/html; charset=utf-8")
            elif path == "/settings/state":
                from . import settings as app_settings
                self._json(app_settings.state())
            elif path == "/settings/uninstall/plan":
                from . import uninstall
                query = parse_qs(urlsplit(self.path).query)
                self._json(uninstall.plan((query.get("delete_data") or ["0"])[0] == "1"))
            elif path == "/settings/login/status":
                from . import settings as app_settings
                self._json(app_settings.SIGN_IN.status())
            elif path == "/style/state":
                self._json(self.server_state.style_state())
            elif path == "/style/status":
                self._json(self.server_state.style_job)
            elif path == "/batches/cover":
                self._send(HTTPStatus.OK, self.server_state.batch_cover(batch), "image/jpeg")
            elif path == "/app.css":         # the look every page shares
                css = (files("depop_seller") / "static" / "app.css").read_bytes()
                self._send(HTTPStatus.OK, css, "text/css; charset=utf-8")
            elif path == "/icon.png":        # the app window's dock / taskbar icon
                icon = (files("depop_seller") / "static" / "icon.png").read_bytes()
                self._send(HTTPStatus.OK, icon, "image/png")
            elif path == "/sell/testform":   # stand-in for Depop's form, used by the listing smoke test
                self._send(HTTPStatus.OK, TEST_FORM.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/sell/state":
                self._json(self.server_state.sell_state(batch))
            elif path == "/sell/status":
                item = int((parse_qs(urlsplit(self.path).query).get("item") or ["0"])[0])
                self._json(self.server_state.lister.status(f"{batch_paths(batch).batch}/{item}"))
            elif path == "/sell/describe/status":
                self._json(self.server_state.describe_state.get(batch_paths(batch).batch, {}))
            elif path == "/sell/photos":
                item = int((parse_qs(urlsplit(self.path).query).get("item") or ["0"])[0])
                host = self.headers.get("Host") or "127.0.0.1:8765"
                self._json(self.server_state.sell_photos(batch, item, f"http://{host}"))
            elif path == "/batches":
                self._json(self.server_state.batches())
            elif path == "/state":
                self._json(self.server_state.session(batch).state())
            elif path == "/white/status":
                self._json(self.server_state.white_status(batch))
            elif path == "/apply/status":
                self._json(self.server_state.session(batch).apply_state)
            elif path == "/group/status":
                self._json(self.server_state.group_state.get(batch_paths(batch).batch) or {"running": False})
            elif path == "/suggestions":
                self._json(self.server_state.suggestions(batch))
            elif path.startswith("/thumbs/") or path.startswith("/large/"):
                kind, name = path[1:].split("/", 1)
                if "/" in name or "\\" in name or not name.endswith(".jpg"):
                    self._text("not found", HTTPStatus.NOT_FOUND)
                    return
                if kind == "thumbs":
                    file = self.server_state.session(batch).thumb_image(name[:-4])
                else:
                    file = self.server_state.session(batch).large_image(name[:-4])
                if file is None:
                    self._text("not found", HTTPStatus.NOT_FOUND)
                    return
                self._send(HTTPStatus.OK, file.read_bytes(), "image/jpeg")
            else:
                self._text("not found", HTTPStatus.NOT_FOUND)
        except (LookupError, FileNotFoundError) as e:
            self._text(str(e), HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path, batch = self._route()
        self.server_state.note_request()
        if self._foreign_origin():
            # Read a small refused body first: Windows resets a connection closed with unread data,
            # and the caller then sees the connection abort instead of this refusal.
            length = int(self.headers.get("Content-Length") or 0)
            if 0 < length <= 1024 * 1024:
                self.rfile.read(length)
            self._text("this server only accepts requests from its own pages", HTTPStatus.FORBIDDEN)
            return
        try:
            if path == "/save":
                self._json(self.server_state.session(batch).save(self._body()))
            elif path == "/white":
                body = self._body()
                self._json(self.server_state.start_white(batch, [str(t) for t in body.get("stems") or []],
                                                         bool(body.get("download"))), HTTPStatus.ACCEPTED)
            elif path == "/white/restore":
                stems = [str(t) for t in self._body().get("stems") or []]
                self._json({"restored": self.server_state.session(batch).restore_originals(stems)})
            elif path == "/apply":
                self.server_state.session(batch).start_apply(bool(self._body().get("force")))
                self._json({"started": True}, HTTPStatus.ACCEPTED)
            elif path == "/group":
                model = self._body().get("model") or DEFAULT_MODEL
                self._json(self.server_state.start_group(batch, model), HTTPStatus.ACCEPTED)
            elif path == "/batches/new":
                body = self._body()
                self._json(self.server_state.new_batch(str(body.get("name") or ""), body.get("location")))
            elif path == "/batches/choose-folder":
                body = self._body()
                self._json(self.server_state.choose_folder(str(body.get("purpose") or "new"), body.get("start")))
            elif path == "/shop/request":
                self._json(self.server_state.shop_requests.start(str(self._body().get("what") or "both")))
            elif path == "/shop/import":
                from . import shop
                length = int(self.headers.get("Content-Length") or 0)
                if length > 40 * 1024 * 1024:
                    raise ValueError("far more than a shop list - refused")
                body = self._body()
                try:
                    job = self.server_state.shop_requests.take(str(body.get("token") or ""))
                except PermissionError as e:
                    self._text(str(e), HTTPStatus.FORBIDDEN)
                    return
                self._json(shop.import_lists(job, body))
            elif path == "/batches/delete":
                self._json(self.server_state.delete_batch(str(self._body().get("name") or "")))
            elif path == "/batches/forget":
                self._json(self.server_state.forget_batch(str(self._body().get("name") or "")))
            elif path == "/batches/open":
                self._json(self.server_state.open_batch_folder(str(self._body().get("name") or "")))
            elif path.startswith("/settings/"):
                from . import settings as app_settings

                if path == "/settings/key":
                    self._json(app_settings.save_api_key(str(self._body().get("key") or "")))
                elif path == "/settings/key/test":
                    self._json(app_settings.test_api_key())
                elif path == "/settings/login":
                    self._json(app_settings.SIGN_IN.start())
                elif path == "/settings/login/code":
                    self._json(app_settings.SIGN_IN.send_code(str(self._body().get("code") or "")))
                elif path == "/settings/uninstall":
                    self._json(self.server_state.start_uninstall(self.server, bool(self._body().get("delete_data"))))
                elif path == "/settings/login/terminal":
                    self._json(app_settings.open_login_terminal())
                elif path == "/settings/login/test":
                    self._json(app_settings.test_claude_login())
                elif path == "/settings/share":
                    from .share import make_share_zip

                    self._json(make_share_zip())
                else:
                    self._text("not found", HTTPStatus.NOT_FOUND)
            elif path == "/closing":
                self._json(self.server_state.arm_close(self.server))
            elif path == "/updates/check":
                from . import updates

                self._json(updates.check())
            elif path == "/updates/install":
                self._json(self.server_state.start_update(self.server), HTTPStatus.ACCEPTED)
            elif path == "/quit":
                log.info("quit requested from the app")
                self._json({"stopping": True})
                threading.Thread(target=self.server.shutdown, name="quit", daemon=True).start()
            elif path == "/style/save":
                self._json(self.server_state.save_style(str(self._body().get("text") or "")))
            elif path == "/style/instruct":
                self._json(self.server_state.start_style_edit(str(self._body().get("instruction") or "")),
                           HTTPStatus.ACCEPTED)
            elif path == "/style/restore":
                self._json(self.server_state.restore_style(str(self._body().get("name") or "")))
            elif path == "/batches/rename":
                body = self._body()
                self._json(self.server_state.rename_batch(str(body.get("name") or ""), str(body.get("to") or "")))
            elif path == "/batches/import":
                body = self._body()
                self._json(self.server_state.import_folder(batch, str(body.get("folder") or "")))
            elif path == "/batches/photos":
                query = parse_qs(urlsplit(self.path).query)
                name = (query.get("name") or [""])[0]
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    raise ValueError("no photo in the request")
                if length > MAX_UPLOAD_BYTES:
                    raise ValueError(f"{name} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                data = self.rfile.read(length)
                replace = (query.get("replace") or ["0"])[0] == "1"
                self._json(self.server_state.add_photo(batch, name, data, replace))
            elif path == "/sell/describe":
                body = self._body()
                self._json(self.server_state.start_describe(
                    batch, [int(i) for i in body.get("items") or []], body.get("facts") or {}), HTTPStatus.ACCEPTED)
            elif path in ("/sell/open", "/sell/item", "/sell/reorder"):
                item = int((parse_qs(urlsplit(self.path).query).get("item") or ["0"])[0])
                if path == "/sell/open":
                    self._json(self.server_state.sell_open(batch, item), HTTPStatus.ACCEPTED)
                elif path == "/sell/reorder":
                    seqs = [int(x) for x in self._body().get("seqs") or []]
                    rows = self.server_state.session(batch).reorder_item(item, seqs)
                    self._json({"photos": [{"seq": r.seq, "stem": r.stem, "file": r.raw_file, "view": r.view} for r in rows]})
                else:
                    self._json(self.server_state.sell_update(batch, item, self._body()))
            elif path == "/suggestions/dismiss":
                body = self._body()
                self._json(self.server_state.dismiss_suggestion(batch, str(body.get("a_stem")), str(body.get("b_stem"))))
            else:
                self._text("not found", HTTPStatus.NOT_FOUND)
        except FileExistsError as e:
            self._text(str(e), HTTPStatus.CONFLICT)
        except (LookupError, FileNotFoundError) as e:
            self._text(str(e), HTTPStatus.NOT_FOUND)
        except (ValueError, RuntimeError) as e:
            self._text(str(e), HTTPStatus.BAD_REQUEST)


class _Server(ThreadingHTTPServer):
    # HTTPServer enables SO_REUSEADDR, which on Windows lets a second process bind the same
    # port instead of failing. We want a hard failure so a double launch is detected. On macOS
    # and Linux it means something else - a second listener is refused either way - and without
    # it the port stays blocked for up to a minute after the app closes, so reopening it at once
    # found the port "busy" and showed a window onto a server that had already gone.
    allow_reuse_address = os.name != "nt"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _bind(port: int, state: ReviewServer, wait_s: float = 0) -> _Server | None:
    """Take the port, or None if another copy of the app has it. After an update the new copy
    waits here for the old one to finish handing over."""
    deadline = time.monotonic() + wait_s
    while True:
        if not _port_in_use(port):
            try:
                return _Server(("127.0.0.1", port), partial(ReviewHandler, state))
            except OSError:
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def serve(batch: str | None = None, port: int = 8765, open_browser: bool = True, page: str = "",
          quiet: bool = False, wait_for_port: float = 0) -> None:
    url = f"http://127.0.0.1:{port}/{page}" + (f"?batch={batch}" if batch else "")
    state = ReviewServer()
    server = _bind(port, state, wait_for_port)
    if server is None:
        # Most likely a window is already running (e.g. the icon was double-clicked twice).
        print(f"port {port} is busy - the app is probably already open; showing it: {url}")
        if open_browser:
            desktop.app_window(url)
        return
    stop = "stop it from the app's Settings tab" if quiet else "close this window or press Ctrl+C to stop"
    print(f"depop_seller: {url}   ({stop})")
    if wait_for_port:
        # Started by an update, in place of the copy that installed it: that copy's window
        # reconnects within seconds. If it never does, do not linger unseen in the background.
        state.arm_close(server, grace=60)
    if open_browser:
        print(f"opened an app window with {desktop.app_window(url)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
