"""The Shop tab: what is selling and what has sold on Depop, as the Chrome helper reads it."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime
from functools import partial
from pathlib import Path

import pytest

from depop_seller import config, shop
from depop_seller.review import ReviewHandler, ReviewServer, _Server

# Shaped like Depop's own answers (field names as seen on the selling hub, 2026-11-01).
SELLING = [
    {"id": 1, "slug": "shop-y2k-top-red", "description": "Vintage Y2K top in red\nBrand: X\n#y2k", "status": "ONSALE",
     "likeCount": 7, "price": {"priceAmount": "40.00", "currencyName": "USD", "discountedPriceAmount": "32.00",
                               "nationalShippingCost": "5.00"},
     "sizes": ["M"], "pictures": [[{"url": "https://pics/small.jpg", "width": 150, "height": 150},
                                   {"url": "https://pics/card.jpg", "width": 480, "height": 480},
                                   {"url": "https://pics/big.jpg", "width": 1280, "height": 1280}]],
     "dateCreated": "2026-10-20T10:00:00Z", "dateUpdated": "2026-10-21T10:00:00Z"},
    {"id": 2, "slug": "shop-jeans", "description": "Baggy jeans", "status": "ONSALE", "likeCount": 2,
     "price": {"priceAmount": "25.50", "currencyName": "USD", "discountedPriceAmount": None},
     "sizes": [{"name": "W30"}], "pictures": [], "dateCreated": "2026-10-25T10:00:00Z", "dateUpdated": "2026-10-25T10:00:00Z"},
]
SOLD = [
    {"purchase_id": 11, "status": "shipping_pending", "sold_timestamp": "2026-10-30T15:00:00Z", "is_bundle": False,
     "currency": "USD", "items_amount": "30.00", "seller_amount": "26.10",
     "buyer": {"username": "someone", "first_name": "A", "last_name": "B"},          # must never be kept
     "line_items": [{"product_id": 5, "description": "Lace cami\nmore", "picture_url": "https://pics/cami.jpg"}]},
    {"purchase_id": 12, "status": "delivered_pending_feedback", "sold_timestamp": "2026-09-12T15:00:00Z", "is_bundle": True,
     "currency": "USD", "items_amount": "50.00", "seller_amount": "44.00",
     "line_items": [{"product_id": 6, "description": "Skirt", "picture_url": ""},
                    {"product_id": 7, "description": "Belt", "picture_url": ""}]},
]


def test_depop_items_become_what_the_shop_tab_shows():
    top = shop.selling_item(SELLING[0])
    assert top["title"] == "Vintage Y2K top in red"                       # the description's first line
    assert (top["price"], top["full_price"], top["currency"]) == (32.0, 40.0, "USD")
    assert top["picture"] == "https://pics/card.jpg"                      # the size closest to a card
    assert top["url"] == "https://www.depop.com/products/shop-y2k-top-red/"
    assert (top["sizes"], top["likes"], top["listed"]) == (["M"], 7, "2026-10-20")
    jeans = shop.selling_item(SELLING[1])
    assert jeans["full_price"] is None and jeans["sizes"] == ["W30"] and jeans["picture"] == ""

    sale = shop.sold_item(SOLD[0])
    assert sale["to_ship"] is True and sale["status_label"] == "To ship" and sale["earned"] == 26.10
    assert sale["items"] == [{"title": "Lace cami", "picture": "https://pics/cami.jpg", "product_id": 5}]
    assert "buyer" not in json.dumps(sale) and "someone" not in json.dumps(sale)
    bundle = shop.sold_item(SOLD[1])
    assert bundle["bundle"] is True and bundle["status_label"] == "Delivered" and len(bundle["items"]) == 2


def test_totals_add_up_and_this_month_is_counted_on_this_computer_s_calendar():
    items = [shop.selling_item(r) for r in SELLING]
    t = shop.selling_totals(items)
    assert t == {"count": 2, "currency": "USD", "value": 57.5, "average": 28.75, "likes": 9, "other_currencies": {}}
    sales = [shop.sold_item(r) for r in SOLD]
    s = shop.sold_totals(sales, now=datetime(2026, 10, 31, 12))
    assert (s["sales"], s["items"], s["gross"], s["earned"], s["to_ship"]) == (2, 3, 80.0, 70.10, 1)
    assert s["this_month"] == {"sales": 1, "earned": 26.10}
    refund = shop.sold_item({**SOLD[0], "purchase_id": 13, "status": "refunded"})
    s = shop.sold_totals(sales + [refund], now=datetime(2026, 10, 31, 12))
    assert (s["sales"], s["refunded"], s["earned"]) == (2, 1, 70.10)          # a refund is not money received
    assert refund["status_label"] == "Refunded"
    euro = shop.selling_item({**SELLING[1], "id": 3, "price": {"priceAmount": "10", "currencyName": "EUR"}})
    mixed = shop.selling_totals(items + [euro])
    assert mixed["currency"] == "USD" and mixed["other_currencies"] == {"EUR": {"count": 1, "value": 10.0}}


@pytest.fixture
def server(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "shop.db")
    srv = _Server(("127.0.0.1", 0), partial(ReviewHandler, ReviewServer()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _call(port, path, body=None, origin=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text else None), r.headers.get("Access-Control-Allow-Origin")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers.get("Access-Control-Allow-Origin")


def test_a_refresh_is_only_taken_from_depop_with_the_app_s_own_pass(server):
    depop = "https://www.depop.com"
    assert _call(server, "/shop/state")[1]["selling"] is None              # nothing read yet

    status, _, _ = _call(server, "/shop/import", {"token": "made-up", "selling": SELLING}, origin=depop)
    assert status == 403                                                    # no pass: refused
    assert _call(server, "/shop/request", {"what": "both"}, origin="https://evil.example")[0] == 403

    token = _call(server, "/shop/request", {"what": "both"})[1]["token"]
    assert _call(server, "/shop/import", {"token": token}, origin=depop, method="OPTIONS")[0] == 204
    status, out, allow = _call(server, "/shop/import", {"token": token, "selling": SELLING, "sold": SOLD,
                                                         "counts": {"selling": 2, "total": 9}}, origin=depop)
    assert status == 200 and allow == depop and out["stored"] == {"selling": 2, "sold": 2}
    assert _call(server, "/shop/import", {"token": token, "selling": []}, origin=depop)[0] == 403   # used once
    assert _call(server, "/shop/import", {"token": token}, origin="https://evil.example")[0] == 403
    # the helper hands lists over from its background script; an extension origin is accepted
    # there (with a pass) and nowhere else
    assert _call(server, "/shop/request", {"what": "both"}, origin="chrome-extension://abc")[0] == 403
    assert _call(server, "/shop/import", {"token": "made-up"}, origin="chrome-extension://abc")[0] == 403

    state = _call(server, "/shop/state")[1]
    assert [i["id"] for i in state["selling"]["items"]] == [2, 1]          # newest listing first
    assert state["selling"]["totals"]["value"] == 57.5 and state["selling"]["expected"] == 2
    assert state["sold"]["items"][0]["id"] == 11 and state["sold"]["totals"]["to_ship"] == 1
    first_sync = state["selling"]["synced_at"]

    token = _call(server, "/shop/request", {"what": "selling"})[1]["token"]
    out = _call(server, "/shop/import", {"token": token, "error": "Depop says you are not signed in"}, origin=depop)[1]
    assert out["error"].startswith("Depop says")
    state = _call(server, "/shop/state")[1]
    assert state["selling"]["error"].startswith("Depop says") and len(state["selling"]["items"]) == 2   # old list kept
    assert state["selling"]["items_from"] == first_sync and state["sold"]["error"] is None


def test_the_helper_reads_the_lists_without_buyers_and_matches_the_app_s_version():
    root = config.PROJECT_ROOT
    manifest = json.loads((root / "chrome_extension" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["background"]["service_worker"] == "background.js" and (root / "chrome_extension" / "background.js").is_file()
    assert manifest["permissions"] == ["storage"]                         # no new powers over the browser
    for page in ("shop", "sell"):
        html = (root / "depop_seller" / "static" / f"{page}.html").read_text(encoding="utf-8")
        assert f"const HELPER_VERSION = '{manifest['version']}';" in html, page
    js = (root / "chrome_extension" / "depop.js").read_text(encoding="utf-8")
    picked = re.search(r"function pickSold\(r\) \{(.*?)\n\}", js, re.S).group(1)
    assert "buyer" not in picked.replace("// no buyer", "") and "address" not in picked.replace("no address", "")
    assert "/api/v1/shop/products/" in js and "/presentation/api/v1/receipts/" in js
    assert "type: 'shop-import'" in js and "Authorization" in js
    assert "/shop/import`" not in js and "fetch(`${job.server}" not in js   # the tab itself never calls the app
    bg = (root / "chrome_extension" / "background.js").read_text(encoding="utf-8")
    assert "/shop/import" in bg and "8765" in bg                           # only the app's own address
    page = (root / "depop_seller" / "static" / "shop.html").read_text(encoding="utf-8")
    assert "depop-seller:shop-sync" in page and "/shop/request" in page
