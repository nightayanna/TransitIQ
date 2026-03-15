"""
scrapers/ta_routes_scraper.py
Scrapes https://ta.org.jm/available-routes
Extracts all licensed taxi/transport authority routes including:
  - Route IDs, names, origin/destination, hubs served
"""

import sys
import os
import time
import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TA_ROUTES_URL, REQUEST_TIMEOUT, REQUEST_DELAY_SECONDS
from storage.db import upsert_route, log_scrape

logger = logging.getLogger("transiq.scraper.ta_routes")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Known major Kingston/Jamaica transport hubs for fuzzy matching
KNOWN_HUBS = [
    "Half Way Tree", "New Kingston", "Downtown Kingston", "Papine",
    "Constant Spring", "Portmore", "Spanish Town", "Montego Bay",
    "Ocho Rios", "Mandeville", "May Pen", "Negril", "Port Antonio",
    "Cross Roads", "Liguanea", "Matilda's Corner", "Sovereign Centre",
    "Three Miles", "Washington Gardens", "Maxfield Avenue", "Arnold Road",
    "Barbican", "Stony Hill", "Shortwood", "Meadowbrook", "Waterford",
    "Gregory Park", "Angels", "Old Harbour", "Linstead", "Bog Walk",
    "Ewarton", "Chapelton", "Christiana", "Falmouth", "Lucea",
    "Savanna-la-Mar", "Black River", "Santa Cruz", "Treasure Beach"
]


def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def infer_hubs_from_name(name: str) -> list:
    """Extract known hub names mentioned in the route name."""
    found = []
    name_lower = name.lower()
    for hub in KNOWN_HUBS:
        if hub.lower() in name_lower:
            found.append(hub)
    return found


def parse_routes_from_html(html: str) -> list[dict]:
    """Parse route data from TA website HTML."""
    soup = BeautifulSoup(html, "lxml")
    routes = []

    # Try table-based layout (most common on TA site)
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        headers = []
        for i, row in enumerate(rows):
            cells = [clean_text(c.get_text()) for c in row.find_all(["th", "td"])]
            if not any(cells):
                continue
            if i == 0 or all(c.isupper() or "route" in c.lower() for c in cells[:2]):
                headers = [c.lower() for c in cells]
                continue
            if len(cells) < 2:
                continue
            route = _parse_row(cells, headers)
            if route:
                routes.append(route)

    # If no tables, try list/div layout
    if not routes:
        items = soup.find_all(["li", "div"], class_=re.compile(r"route|item|entry", re.I))
        for idx, item in enumerate(items):
            text = clean_text(item.get_text())
            if len(text) < 5:
                continue
            route = _parse_freetext(text, idx)
            if route:
                routes.append(route)

    logger.info(f"Parsed {len(routes)} routes from TA routes page")
    return routes


def _parse_row(cells: list, headers: list) -> dict | None:
    """Build a route dict from a table row."""
    try:
        # Try header-guided extraction
        data = {}
        for i, h in enumerate(headers):
            if i < len(cells):
                data[h] = cells[i]

        name = (
            data.get("route name") or data.get("name") or
            data.get("route") or cells[0]
        )
        route_id = (
            data.get("route id") or data.get("id") or
            data.get("code") or f"TA-{len(name[:6].upper().replace(' ','-'))}-{hash(name) % 9999:04d}"
        )
        origin = data.get("origin") or data.get("from") or ""
        destination = data.get("destination") or data.get("to") or ""

        if not name or len(name) < 3:
            return None

        hubs = infer_hubs_from_name(name)
        if origin and origin not in hubs:
            hubs.insert(0, origin)
        if destination and destination not in hubs:
            hubs.append(destination)

        return {
            "route_id": clean_text(str(route_id))[:64],
            "name": clean_text(name),
            "type": "taxi",
            "origin": clean_text(origin),
            "destination": clean_text(destination),
            "hubs": hubs,
        }
    except Exception as e:
        logger.debug(f"Row parse error: {e}")
        return None


def _parse_freetext(text: str, idx: int) -> dict | None:
    """Parse a route from free-form text."""
    # Look for "X to Y" or "X - Y" pattern
    m = re.search(r"(.+?)\s+(?:to|-|–)\s+(.+)", text, re.I)
    if m:
        origin, destination = m.group(1).strip(), m.group(2).strip()
        name = f"{origin} to {destination}"
    else:
        name = text[:80]
        origin, destination = "", ""

    if len(name) < 4:
        return None

    return {
        "route_id": f"TA-FT-{idx:04d}",
        "name": name,
        "type": "taxi",
        "origin": origin[:80],
        "destination": destination[:80],
        "hubs": infer_hubs_from_name(name),
    }


def scrape_ta_routes() -> int:
    """
    Main scrape function.
    Returns number of routes upserted.
    """
    start = time.time()
    logger.info(f"Scraping TA routes from {TA_ROUTES_URL}")

    try:
        resp = requests.get(TA_ROUTES_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        routes = parse_routes_from_html(resp.text)

        if not routes:
            logger.warning("No routes parsed from live site — check HTML structure")

        count = 0
        for route in routes:
            upsert_route(route)
            count += 1
            time.sleep(0.05)  # minimal delay for DB

        duration_ms = int((time.time() - start) * 1000)
        log_scrape("ta_routes", "success", count, duration_ms=duration_ms)
        logger.info(f"✅ TA routes: {count} routes upserted in {duration_ms}ms")
        return count

    except requests.RequestException as e:
        duration_ms = int((time.time() - start) * 1000)
        log_scrape("ta_routes", "failed", 0, str(e), duration_ms)
        logger.error(f"❌ TA routes scrape failed: {e}")
        return 0


if __name__ == "__main__":
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s"
    )
    from storage.db import init_db
    init_db()
    n = scrape_ta_routes()
    print(f"Done. {n} routes upserted.")
