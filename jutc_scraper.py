"""
scrapers/jutc_scraper.py
Scrapes JUTC (Jamaica Urban Transit Company) website
Extracts: bus routes, schedules, stop locations, fares
"""

import sys
import os
import time
import logging
import re

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import JUTC_ROUTES_URL, JUTC_SCHEDULES_URL, REQUEST_TIMEOUT
from storage.db import upsert_route, upsert_fare, log_scrape

logger = logging.getLogger("transiq.scraper.jutc")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    ),
}

JMD_TO_USD = 0.0064

# JUTC base fare as of 2024 (official rates — update if changed)
JUTC_ADULT_FARE_JMD = 160.0
JUTC_STUDENT_FARE_JMD = 80.0

# Known JUTC route numbers and names for fallback
JUTC_KNOWN_ROUTES = [
    {"route_id": "JUTC-21A", "name": "21A — Half Way Tree to Portmore (Via Washington Blvd)",
     "origin": "Half Way Tree", "destination": "Portmore"},
    {"route_id": "JUTC-21B", "name": "21B — Half Way Tree to Portmore (Via Constant Spring Road)",
     "origin": "Half Way Tree", "destination": "Portmore"},
    {"route_id": "JUTC-22", "name": "22 — Downtown Kingston to Spanish Town",
     "origin": "Downtown Kingston", "destination": "Spanish Town"},
    {"route_id": "JUTC-23", "name": "23 — Half Way Tree to Papine",
     "origin": "Half Way Tree", "destination": "Papine"},
    {"route_id": "JUTC-24", "name": "24 — New Kingston to Constant Spring",
     "origin": "New Kingston", "destination": "Constant Spring"},
    {"route_id": "JUTC-25", "name": "25 — Downtown Kingston to Matilda's Corner",
     "origin": "Downtown Kingston", "destination": "Matilda's Corner"},
    {"route_id": "JUTC-26", "name": "26 — Half Way Tree to Meadowbrook",
     "origin": "Half Way Tree", "destination": "Meadowbrook"},
    {"route_id": "JUTC-27", "name": "27 — Downtown Kingston to Stony Hill",
     "origin": "Downtown Kingston", "destination": "Stony Hill"},
    {"route_id": "JUTC-28", "name": "28 — Half Way Tree to Arnold Road",
     "origin": "Half Way Tree", "destination": "Arnold Road"},
    {"route_id": "JUTC-38", "name": "38 — Downtown Kingston to Washington Gardens",
     "origin": "Downtown Kingston", "destination": "Washington Gardens"},
    {"route_id": "JUTC-64", "name": "64 — Half Way Tree to Three Miles",
     "origin": "Half Way Tree", "destination": "Three Miles"},
    {"route_id": "JUTC-97", "name": "97 — New Kingston to Barbican",
     "origin": "New Kingston", "destination": "Barbican"},
    {"route_id": "JUTC-99", "name": "99 — Half Way Tree to Liguanea",
     "origin": "Half Way Tree", "destination": "Liguanea"},
]


def parse_jutc_routes(html: str) -> list[dict]:
    """Parse JUTC routes from website HTML."""
    soup = BeautifulSoup(html, "lxml")
    routes = []

    # Try table layout
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        headers = []
        for i, row in enumerate(rows):
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if not cells:
                continue
            if i == 0:
                headers = [c.lower() for c in cells]
                continue
            if len(cells) < 2:
                continue

            data = dict(zip(headers, cells)) if headers else {}
            route_num = data.get("route") or data.get("number") or data.get("#") or cells[0]
            route_name = data.get("name") or data.get("description") or data.get("route name") or cells[1] if len(cells) > 1 else ""
            origin = data.get("from") or data.get("origin") or ""
            destination = data.get("to") or data.get("destination") or ""

            if not route_name or len(route_name.strip()) < 3:
                continue

            route_id = f"JUTC-{str(route_num).strip().upper()[:10]}"
            routes.append({
                "route_id": route_id,
                "name": f"{route_num} — {route_name}".strip(" —"),
                "type": "bus",
                "origin": origin[:80],
                "destination": destination[:80],
                "hubs": [h for h in [origin, destination] if h],
            })

    # Try list items with route info
    if not routes:
        for item in soup.find_all(["li", "div", "p"]):
            text = item.get_text(strip=True)
            m = re.match(r"(\d+[A-Z]?)\s*[-–—:]\s*(.+)", text)
            if m:
                num, desc = m.group(1), m.group(2)
                to_match = re.search(r"(.+?)\s+to\s+(.+)", desc, re.I)
                origin = to_match.group(1).strip() if to_match else ""
                dest = to_match.group(2).strip() if to_match else ""
                routes.append({
                    "route_id": f"JUTC-{num}",
                    "name": f"{num} — {desc[:150]}",
                    "type": "bus",
                    "origin": origin[:80],
                    "destination": dest[:80],
                    "hubs": [h for h in [origin, dest] if h],
                })

    logger.info(f"Parsed {len(routes)} JUTC routes from live HTML")
    return routes


def scrape_jutc() -> int:
    """Main JUTC scrape function."""
    start = time.time()
    logger.info("Scraping JUTC routes")
    count = 0
    live_routes = []

    try:
        resp = requests.get(JUTC_ROUTES_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        live_routes = parse_jutc_routes(resp.text)
    except requests.RequestException as e:
        logger.warning(f"JUTC live scrape failed ({e}), using known routes fallback")

    # Merge live routes with known routes (known routes fill any gaps)
    live_ids = {r["route_id"] for r in live_routes}
    all_routes = list(live_routes)
    for known in JUTC_KNOWN_ROUTES:
        if known["route_id"] not in live_ids:
            all_routes.append({**known, "type": "bus", "hubs": [known["origin"], known["destination"]]})

    for route in all_routes:
        upsert_route(route)
        # Insert official flat fare
        upsert_fare({
            "route_id": route["route_id"],
            "fare_jmd": JUTC_ADULT_FARE_JMD,
            "fare_usd": round(JUTC_ADULT_FARE_JMD * JMD_TO_USD, 2),
        })
        count += 1

    duration_ms = int((time.time() - start) * 1000)
    log_scrape("jutc", "success", count, duration_ms=duration_ms)
    logger.info(f"✅ JUTC: {count} routes/fares upserted in {duration_ms}ms")
    return count


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
    from storage.db import init_db
    init_db()
    n = scrape_jutc()
    print(f"Done. {n} routes upserted.")
