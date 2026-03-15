"""
scrapers/ta_fares_scraper.py
Scrapes https://ta.org.jm/routes-and-fares
Extracts official licensed fare prices per route.
"""

import sys
import os
import time
import logging
import re

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TA_FARES_URL, REQUEST_TIMEOUT
from storage.db import upsert_fare, upsert_route, log_scrape

logger = logging.getLogger("transiq.scraper.ta_fares")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Approximate JMD/USD rate (update before hackathon)
JMD_TO_USD = 0.0064


def extract_jmd_amount(text: str) -> float | None:
    """Extract a numeric JMD amount from text like '$150' or 'JMD 200.00'."""
    text = text.replace(",", "").strip()
    # Match patterns like: $150, 150.00, JMD 150, 150 JMD
    m = re.search(r"[\$JMD\s]*([\d]+(?:\.\d{1,2})?)", text, re.I)
    if m:
        val = float(m.group(1))
        # Sanity check: Jamaica bus fares typically 100–3000 JMD
        if 50 <= val <= 10000:
            return val
    return None


def parse_fares_from_html(html: str) -> list[dict]:
    """Parse fare data from TA website."""
    soup = BeautifulSoup(html, "lxml")
    fares = []
    routes_created = []

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        headers = []
        for i, row in enumerate(rows):
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if not any(cells):
                continue

            if i == 0 or any("fare" in c.lower() or "route" in c.lower() for c in cells):
                headers = [c.lower() for c in cells]
                continue

            if len(cells) < 2:
                continue

            data = dict(zip(headers, cells)) if headers else {}

            # Extract route name/ID
            route_name = (
                data.get("route name") or data.get("route") or
                data.get("name") or cells[0]
            ).strip()
            route_id = (
                data.get("route id") or data.get("id") or data.get("code") or
                f"TA-FARE-{abs(hash(route_name)) % 9999:04d}"
            ).strip()[:64]

            # Extract fare
            fare_text = (
                data.get("fare") or data.get("price") or
                data.get("amount") or data.get("cost") or
                (cells[1] if len(cells) > 1 else "")
            )
            fare_jmd = extract_jmd_amount(fare_text)

            if not fare_jmd:
                # Try scanning all cells for a fare
                for cell in cells:
                    fare_jmd = extract_jmd_amount(cell)
                    if fare_jmd:
                        break

            if fare_jmd and route_name and len(route_name) > 2:
                # Ensure route exists
                routes_created.append({
                    "route_id": route_id,
                    "name": route_name,
                    "type": "taxi",
                    "origin": data.get("from", ""),
                    "destination": data.get("to", ""),
                    "hubs": [],
                })
                fares.append({
                    "route_id": route_id,
                    "fare_jmd": fare_jmd,
                    "fare_usd": round(fare_jmd * JMD_TO_USD, 2),
                    "distance_km": None,
                    "duration_min": None,
                })

    # Also try definition lists and paragraph patterns
    if not fares:
        text_blocks = soup.find_all(["p", "li", "div"])
        idx = 0
        for block in text_blocks:
            text = block.get_text(strip=True)
            m = re.search(
                r"(.+?)\s+(?:to|-|–)\s+(.+?)[:\s]+\$?([\d,]+(?:\.\d{1,2})?)",
                text, re.I
            )
            if m:
                origin, dest, amount_str = m.group(1), m.group(2), m.group(3)
                fare_jmd = float(amount_str.replace(",", ""))
                if 50 <= fare_jmd <= 10000:
                    name = f"{origin.strip()} to {dest.strip()}"
                    route_id = f"TA-F-{idx:04d}"
                    routes_created.append({
                        "route_id": route_id,
                        "name": name[:200],
                        "type": "taxi",
                        "origin": origin.strip()[:80],
                        "destination": dest.strip()[:80],
                        "hubs": [],
                    })
                    fares.append({
                        "route_id": route_id,
                        "fare_jmd": fare_jmd,
                        "fare_usd": round(fare_jmd * JMD_TO_USD, 2),
                    })
                    idx += 1

    logger.info(f"Parsed {len(fares)} fares from TA fares page")
    return fares, routes_created


def scrape_ta_fares() -> int:
    """Main scrape function. Returns number of fares upserted."""
    start = time.time()
    logger.info(f"Scraping TA fares from {TA_FARES_URL}")

    try:
        resp = requests.get(TA_FARES_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        fares, routes = parse_fares_from_html(resp.text)

        # Ensure parent routes exist first
        for route in routes:
            upsert_route(route)

        count = 0
        for fare in fares:
            upsert_fare(fare)
            count += 1

        duration_ms = int((time.time() - start) * 1000)
        log_scrape("ta_fares", "success", count, duration_ms=duration_ms)
        logger.info(f"✅ TA fares: {count} fares upserted in {duration_ms}ms")
        return count

    except requests.RequestException as e:
        duration_ms = int((time.time() - start) * 1000)
        log_scrape("ta_fares", "failed", 0, str(e), duration_ms)
        logger.error(f"❌ TA fares scrape failed: {e}")
        return 0


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
    from storage.db import init_db
    init_db()
    n = scrape_ta_fares()
    print(f"Done. {n} fares upserted.")
