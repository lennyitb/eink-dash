"""Birthdays from iCloud Contacts over CardDAV (app-specific password).

iCloud's Birthdays calendar can't be shared as an iCal link, so read the contacts'
BDAY fields directly. Discovery: current-user-principal -> addressbook-home-set ->
every addressbook under it -> addressbook-query for cards (FN + BDAY only).
"""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import urljoin

import httpx

from .config import settings

log = logging.getLogger(__name__)

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:carddav"}
ROOT = "https://contacts.icloud.com/"

_PROPFIND_PRINCIPAL = """<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>"""
_PROPFIND_HOME = """<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:prop><c:addressbook-home-set/></d:prop></d:propfind>"""
_PROPFIND_BOOKS = """<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>"""
_REPORT_CARDS = """<?xml version="1.0"?>
<c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
  <d:prop><c:address-data><c:prop name="FN"/><c:prop name="N"/><c:prop name="BDAY"/></c:address-data></d:prop>
</c:addressbook-query>"""


def _href(xml: bytes, path: str) -> str | None:
    el = ET.fromstring(xml).find(path, NS)
    return el.text.strip() if el is not None and el.text else None


def fetch_contacts() -> list[dict]:
    """Return [{'name', 'month', 'day', 'year'|None}] for contacts with a birthday."""
    auth = (settings.icloud_username, settings.icloud_app_password)
    with httpx.Client(auth=auth, timeout=30, follow_redirects=True,
                      headers={"Content-Type": "application/xml; charset=utf-8"}) as c:
        r = c.request("PROPFIND", ROOT, headers={"Depth": "0"}, content=_PROPFIND_PRINCIPAL)
        r.raise_for_status()
        principal = urljoin(str(r.url), _href(r.content, ".//d:current-user-principal/d:href"))
        r = c.request("PROPFIND", principal, headers={"Depth": "0"}, content=_PROPFIND_HOME)
        r.raise_for_status()
        home = urljoin(str(r.url), _href(r.content, ".//c:addressbook-home-set/d:href"))
        r = c.request("PROPFIND", home, headers={"Depth": "1"}, content=_PROPFIND_BOOKS)
        r.raise_for_status()
        books = []
        for resp in ET.fromstring(r.content).findall("d:response", NS):
            if resp.find(".//d:resourcetype/c:addressbook", NS) is not None:
                books.append(urljoin(str(r.url), resp.find("d:href", NS).text.strip()))
        out: list[dict] = []
        for book in books:
            r = c.request("REPORT", book, headers={"Depth": "1"}, content=_REPORT_CARDS)
            r.raise_for_status()
            for el in ET.fromstring(r.content).iterfind(".//c:address-data", NS):
                b = parse_vcard(el.text or "")
                if b:
                    out.append(b)
    return out


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def parse_vcard(text: str) -> dict | None:
    name = bday = None
    n_field = None
    for line in _unfold(text):
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        prop = key.split(";")[0].split(".")[-1].upper()  # strip item1. group prefixes
        if prop == "FN":
            name = val.strip().replace("\\,", ",")
        elif prop == "N":
            n_field = val
        elif prop == "BDAY":
            bday = (key, val.strip())
    if not bday:
        return None
    if not name and n_field:
        parts = n_field.split(";")
        name = " ".join(p for p in (parts[1:2] + parts[0:1]) if p).strip()
    if not name:
        return None
    key, val = bday
    m = re.match(r"^(\d{4}|--)-?(\d{2})-?(\d{2})", val)
    if not m:
        return None
    year = None if m.group(1) == "--" else int(m.group(1))
    # Apple stores year-less birthdays as 1604 with X-APPLE-OMIT-YEAR
    if year is not None and ("X-APPLE-OMIT-YEAR" in key.upper() or year <= 1604):
        year = None
    return {"name": name, "month": int(m.group(2)), "day": int(m.group(3)), "year": year}


def _on(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:  # Feb 29 in a non-leap year
        return date(year, 2, 28)


def upcoming(contacts: list[dict], start: date, days: int) -> list[dict]:
    end = start + timedelta(days=days)
    items = []
    for c in contacts:
        for y in (start.year, start.year + 1):
            d = _on(y, c["month"], c["day"])
            if start <= d < end:
                first = c["name"].split()[0] if settings.birthday_first_names else c["name"]
                title = f"{first}'s birthday"
                if c["year"] and settings.birthday_show_age:
                    title += f" ({d.year - c['year']})"
                items.append({"id": "bday-" + hashlib.sha1(f"{c['name']}|{d}".encode()).hexdigest()[:8],
                              "source": "birthdays", "kind": "event", "date": d.isoformat(),
                              "time": None, "title": title, "course": None})
    return items
