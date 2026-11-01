"""Your Depop shop as Depop sees it: what is for sale and what has sold.

Depop's selling hub pages load their lists a page at a time from Depop's own web API - the
"selling" list from `webapi.depop.com/api/v1/shop/products/?statusFilter=selling` (24 a page,
`cursor` for the next), the "sold" list from `/presentation/api/v1/receipts/?role=seller`
(12 a page, `after` for the next). Infinite scrolling is just the page asking for the next one.

The app never talks to Depop itself (its bot protection blocked an automated browser before).
The Chrome helper does, inside a depop.com tab of the seller's own Chrome, with the seller's own
sign-in - exactly the requests Depop's page makes - and its background script hands the items to
`/shop/import`. Not the tab itself: Chrome blocks a website from reaching this computer
(Local Network Access) and Depop's consent script blocks unknown hosts too, while an extension's
background script may reach the hosts it has permission for (checked on 2026-11-01: 91 for sale
and 105 sales read in about 7 seconds; the page itself could not reach 127.0.0.1).
It picks out the fields below and leaves the rest behind: no buyer names, no addresses. The
sign-in token never leaves Chrome.

This module turns those picked fields into what the Shop tab shows, works out the totals, and
keeps one snapshot per list in the database, so the tab shows the last refresh straight away.

The sold list only grows, so a Refresh does not read all of it every time: sales from the last
`RECHECK_DAYS` are read again (their state still moves - shipped, delivered, now and then a
refund) and older ones are kept from the last refresh. Every sale is read again when the last full
read is more than `FULL_EVERY_DAYS` old, so a late change is caught within a month. The selling
list is read whole every time: a listing anywhere in it can be edited, sold or deleted, and it is
bounded by what is for sale now, not by everything ever sold.
"""

from __future__ import annotations

import csv
import io
import json
import secrets
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from . import db

KINDS = ("selling", "sold")
REQUEST_TTL_S = 10 * 60          # how long a Refresh may take before its pass expires
MAX_ITEMS = 20000                # far beyond any shop; a sanity cap on what is accepted
RECHECK_DAYS = 90                # sales younger than this are read again on every Refresh
FULL_EVERY_DAYS = 30             # and every sale at least this often

# Depop's receipt states, as a seller would say them.
STATUS_LABELS = {
    "shipping_pending": "To ship",
    "shipped": "Shipped",
    "in_transit": "On its way",
    "delivered": "Delivered",
    "delivered_pending_feedback": "Delivered",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "refunded": "Refunded",
}


def _money(value) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _title(description: str) -> str:
    """The first line of a Depop description is its headline."""
    first = (description or "").strip().splitlines()[0].strip() if (description or "").strip() else ""
    return first[:120] + ("…" if len(first) > 120 else "")


def _size_names(sizes) -> list[str]:
    out = []
    for s in sizes or []:
        if isinstance(s, str):
            out.append(s)
        elif isinstance(s, dict):
            name = s.get("name") or s.get("value") or s.get("size") or s.get("label")
            if name:
                out.append(str(name))
    return out


def _picture(pictures, wanted: int = 480) -> str:
    """Depop sends each photo in several sizes; take the one closest to a card's width."""
    if not pictures:
        return ""
    first = pictures[0]
    formats = first if isinstance(first, list) else [first]
    formats = [f for f in formats if isinstance(f, dict) and f.get("url")]
    if not formats:
        return ""
    return min(formats, key=lambda f: abs((f.get("width") or 0) - wanted))["url"]


def selling_item(raw: dict) -> dict:
    price = raw.get("price") or {}
    full = _money(price.get("priceAmount"))
    discounted = price.get("discountedPriceAmount")
    now = _money(discounted) if discounted not in (None, "") else full
    slug = str(raw.get("slug") or "")
    return {
        "id": raw.get("id"),
        "title": _title(raw.get("description") or "") or "(no description)",
        "url": f"https://www.depop.com/products/{slug}/" if slug else "",
        "price": now,
        "full_price": full if now != full else None,
        "currency": str(price.get("currencyName") or ""),
        "shipping": _money(price.get("nationalShippingCost")) if price.get("nationalShippingCost") else None,
        "sizes": _size_names(raw.get("sizes")),
        "likes": int(raw.get("likeCount") or 0),
        "picture": _picture(raw.get("pictures")),
        "listed": str(raw.get("dateCreated") or "")[:10],
        "updated": str(raw.get("dateUpdated") or "")[:10],
    }


def sold_item(raw: dict) -> dict:
    lines = raw.get("line_items") or []
    status = str(raw.get("status") or "")
    return {
        "id": raw.get("purchase_id"),
        "sold_at": str(raw.get("sold_timestamp") or ""),
        "date": str(raw.get("sold_timestamp") or "")[:10],
        "status": status,
        "status_label": STATUS_LABELS.get(status, status.replace("_", " ").capitalize() or "Sold"),
        "to_ship": status == "shipping_pending",
        "bundle": bool(raw.get("is_bundle")) or len(lines) > 1,
        "currency": str(raw.get("currency") or ""),
        "price": _money(raw.get("items_amount")),
        "earned": _money(raw.get("seller_amount")),
        "items": [{"title": _title(li.get("description") or "") or "(no description)",
                   "picture": str(li.get("picture_url") or ""),
                   "product_id": li.get("product_id")} for li in lines if isinstance(li, dict)],
    }


def _main_currency(rows: list[dict]) -> str:
    counts = Counter(r["currency"] for r in rows if r.get("currency"))
    return counts.most_common(1)[0][0] if counts else ""


def selling_totals(items: list[dict]) -> dict:
    by = defaultdict(lambda: {"count": 0, "value": 0.0})
    for it in items:
        by[it["currency"]]["count"] += 1
        by[it["currency"]]["value"] = round(by[it["currency"]]["value"] + it["price"], 2)
    main = _main_currency(items)
    value = by[main]["value"] if main else 0.0
    count = by[main]["count"] if main else 0
    return {
        "count": len(items),
        "currency": main,
        "value": value,
        "average": round(value / count, 2) if count else 0.0,
        "likes": sum(it["likes"] for it in items),
        "other_currencies": {c: v for c, v in by.items() if c != main},
    }


NOT_INCOME = ("refunded", "cancelled")            # listed with their label, never counted as sales


def sold_totals(sales: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now()
    month = now.strftime("%Y-%m")
    counted = [s for s in sales if s["status"] not in NOT_INCOME]
    main = _main_currency(counted)
    mine = [s for s in counted if s["currency"] == main]
    this_month = [s for s in mine if _local_month(s["sold_at"]) == month]
    return {
        "sales": len(counted),
        "refunded": len(sales) - len(counted),
        "items": sum(max(1, len(s["items"])) for s in counted),
        "currency": main,
        "gross": round(sum(s["price"] for s in mine), 2),
        "earned": round(sum(s["earned"] for s in mine), 2),
        "this_month": {"sales": len(this_month), "earned": round(sum(s["earned"] for s in this_month), 2)},
        "to_ship": sum(1 for s in counted if s["to_ship"]),
        "other_currencies": sorted({s["currency"] for s in counted if s["currency"] and s["currency"] != main}),
    }


def _when(stamp) -> datetime | None:
    """A Depop (UTC, `Z`) or app (this computer's clock) time stamp as an aware datetime."""
    try:
        when = datetime.fromisoformat(str(stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.astimezone()


def _utc(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sold_since(now: datetime | None = None) -> str | None:
    """Where a Refresh of the sold list may stop reading, or None to read every sale."""
    snap = load().get("sold")
    if not snap or not snap.get("items"):
        return None                               # nothing kept to fill in the older sales
    now = now or datetime.now(timezone.utc)
    full_at = _when(snap.get("full_at"))
    if full_at is None or now - full_at > timedelta(days=FULL_EVERY_DAYS):
        return None
    newest = max((w for w in (_when(s.get("sold_at")) for s in snap["items"]) if w), default=None)
    if newest is None:
        return None
    # never later than the newest sale kept: anything sold after the last refresh is always read
    return _utc(min(now - timedelta(days=RECHECK_DAYS), newest))


def _local_month(stamp: str) -> str:
    """The calendar month a sale fell in on this computer's clock (Depop sends UTC)."""
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp[:7]
    return (when.astimezone() if when.tzinfo else when).strftime("%Y-%m")


# ---- the refresh hand-off ---------------------------------------------------------------

class Requests:
    """A Refresh hands the helper a one-time pass; `/shop/import` only accepts lists that carry
    an unexpired one. Any page open on depop.com can reach the server, so without it any script
    there could fill the Shop tab with whatever it liked."""

    def __init__(self) -> None:
        self.pending: dict[str, dict] = {}

    def start(self, what: str) -> dict:
        if what not in ("selling", "sold", "both"):
            raise ValueError(f"unknown list {what!r}")
        token = secrets.token_urlsafe(18)
        since = sold_since() if what != "selling" else None
        self.pending = {k: v for k, v in self.pending.items() if time.monotonic() - v["at"] < REQUEST_TTL_S}
        self.pending[token] = {"what": what, "at": time.monotonic(), "since": since}
        return {"token": token, "what": what, "since": since}

    def take(self, token: str) -> dict:
        job = self.pending.pop(str(token or ""), None)
        if job is None or time.monotonic() - job["at"] > REQUEST_TTL_S:
            raise PermissionError("this refresh was not asked for by the app, or it took too long - press Refresh again")
        return job

    def running(self) -> bool:
        return any(time.monotonic() - v["at"] < REQUEST_TTL_S for v in self.pending.values())


def save(kind: str, data: dict, conn=None) -> None:
    own = conn is None
    conn = conn or db.connect()
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO shop_snapshot (kind, synced_at, data) VALUES (?, ?, ?)",
                         (kind, datetime.now().isoformat(timespec="seconds"), json.dumps(data)))
    finally:
        if own:
            conn.close()


def load(conn=None) -> dict:
    own = conn is None
    conn = conn or db.connect()
    try:
        rows = {r["kind"]: r for r in conn.execute("SELECT kind, synced_at, data FROM shop_snapshot")}
    finally:
        if own:
            conn.close()
    out = {}
    for kind in KINDS:
        r = rows.get(kind)
        out[kind] = {"synced_at": r["synced_at"], **json.loads(r["data"])} if r else None
    return out


def import_lists(job: dict, body: dict, now: datetime | None = None) -> dict:
    """Store what the helper read. An `error` from the helper is kept with the old list, so the
    tab can say what went wrong without losing what it showed before. A sold list read only back
    to the pass's `since` (the helper says so with `sold_since`) is completed with the older sales
    from the last refresh."""
    what = job["what"]
    kinds = KINDS if what == "both" else (what,)
    error = str(body.get("error") or "").strip()[:300]
    counts = body.get("counts") if isinstance(body.get("counts"), dict) else {}
    stored = {}
    old = load()
    for kind in kinds:
        if error:
            prev = old.get(kind) or {"items": []}
            kept = {k: v for k, v in prev.items() if k not in ("synced_at", "totals")}
            # the list shown is still the one from the last good refresh - say when that was
            kept["items_from"] = prev.get("items_from") or prev.get("synced_at")
            save(kind, {**kept, "error": error})
            continue
        raw = body.get(kind)
        if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
            raise ValueError(f"the helper sent no {kind} list")
        if kind == "selling":
            rows = [selling_item(r) for r in raw if isinstance(r, dict)]
            rows.sort(key=lambda r: r["listed"], reverse=True)
            data = {"items": rows, "expected": counts.get("selling") if isinstance(counts.get("selling"), int) else None}
        else:
            rows = [sold_item(r) for r in raw if isinstance(r, dict)]
            since = job.get("since")
            prev = old.get("sold") or {}
            if since and body.get("sold_since") == since:
                cut, seen = _when(since), {r["id"] for r in rows}
                for r in prev.get("items") or []:
                    when = _when(r.get("sold_at"))
                    if r.get("id") not in seen and (when is None or when < cut):
                        rows.append(r)
                full_at = prev.get("full_at")
            else:                                 # every sale was read (or an older helper read them all)
                since, full_at = None, _utc(now or datetime.now(timezone.utc))
            rows.sort(key=lambda r: r["sold_at"], reverse=True)
            data = {"items": rows, "full_at": full_at, "checked_from": since}
        save(kind, {**data, "error": None, "items_from": None})
        stored[kind] = len(rows)
    return {"stored": stored, "error": error or None}


def state(now: datetime | None = None) -> dict:
    """Both lists with their totals, worked out now - "this month" must not go stale."""
    out = {}
    for kind, snap in load().items():
        if snap is None:
            out[kind] = None
            continue
        items = snap.get("items") or []
        totals = selling_totals(items) if kind == "selling" else sold_totals(items, now)
        out[kind] = {**snap, "totals": totals}
    return out


# ---- spreadsheet export -------------------------------------------------------------------

def _cell(value) -> str:
    """Text as a spreadsheet will take it literally: a cell starting with = + @ would be read as
    a formula by Excel or Sheets."""
    text = str(value if value is not None else "")
    return "'" + text if text[:1] in ("=", "+", "@", chr(9), chr(13)) else text


def _amount(value) -> str:
    return "" if value is None else f"{value:.2f}"


def _local_time(stamp: str) -> str:
    when = _when(stamp)
    return when.astimezone().strftime("%Y-%m-%d %H:%M") if when else str(stamp or "")


def export_csv(kind: str, today: datetime | None = None) -> tuple[str, bytes]:
    """The list as last refreshed, one row per listing or per sale, as a CSV file name and its
    bytes. UTF-8 with a byte-order mark, so Excel shows accents and emoji instead of mojibake."""
    if kind not in KINDS:
        raise ValueError(f"unknown list {kind!r}")
    snap = load().get(kind)
    items = (snap or {}).get("items") or []
    if not items:
        raise ValueError("there is nothing to export yet - press Refresh first")
    out = io.StringIO()
    w = csv.writer(out)
    if kind == "selling":
        w.writerow(["Title", "Price", "Original price", "Currency", "Shipping", "Sizes", "Likes",
                    "Listed", "Last updated", "Link", "Depop ID"])
        for it in items:
            w.writerow([_cell(it.get("title")), _amount(it.get("price")), _amount(it.get("full_price")),
                        it.get("currency") or "", _amount(it.get("shipping")), _cell(", ".join(it.get("sizes") or [])),
                        it.get("likes", 0), it.get("listed") or "", it.get("updated") or "", it.get("url") or "",
                        it.get("id") or ""])
    else:
        w.writerow(["Sold on", "Status", "Counted in totals", "Items", "Number of items", "Bundle",
                    "Sale price", "You received", "Currency", "Sale ID"])
        for s in items:
            lines = s.get("items") or []
            w.writerow([_local_time(s.get("sold_at") or s.get("date")), s.get("status_label") or "",
                        "No" if s.get("status") in NOT_INCOME else "Yes",
                        _cell(" + ".join(i.get("title") or "" for i in lines)), max(1, len(lines)),
                        "Yes" if s.get("bundle") else "No", _amount(s.get("price")), _amount(s.get("earned")),
                        s.get("currency") or "", s.get("id") or ""])
    day = (today or datetime.now()).strftime("%Y-%m-%d")
    return f"Depop {kind} {day}.csv", out.getvalue().encode("utf-8-sig")
