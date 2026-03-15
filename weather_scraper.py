"""
scrapers/weather_scraper.py
Scrapes Jamaica Meteorological Service for weather and flood alerts.
Relevant to TransIQ for: safety scores, route reliability, best departure time.
"""

import sys
import os
import time
import logging
import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import MET_WEATHER_URL, REQUEST_TIMEOUT
from storage.db import insert_weather_alert, log_scrape

logger = logging.getLogger("transiq.scraper.weather")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    ),
}

JAMAICA_PARISHES = [
    "Kingston", "Saint Andrew", "Saint Thomas", "Portland",
    "Saint Mary", "Saint Ann", "Trelawny", "Saint James",
    "Hanover", "Westmoreland", "Saint Elizabeth", "Manchester",
    "Clarendon", "Saint Catherine",
]

SEVERITY_KEYWORDS = {
    "critical": ["hurricane", "tropical storm", "category", "major flooding", "emergency"],
    "high":     ["flood warning", "heavy rain warning", "watch", "advisory", "severe"],
    "medium":   ["rain", "shower", "thunderstorm", "strong wind", "moderate"],
    "low":      ["partly cloudy", "clear", "fair", "light", "isolated"],
}


def classify_weather_severity(text: str) -> str:
    text_lower = text.lower()
    for level in ["critical", "high", "medium", "low"]:
        for kw in SEVERITY_KEYWORDS[level]:
            if kw in text_lower:
                return level
    return "low"


def classify_alert_type(text: str) -> str:
    text_lower = text.lower()
    if any(w in text_lower for w in ["hurricane", "tropical"]):
        return "hurricane"
    if any(w in text_lower for w in ["flood"]):
        return "flood"
    if any(w in text_lower for w in ["rain", "shower", "thunder"]):
        return "rain"
    return "clear"


def parse_weather_from_html(html: str) -> list[dict]:
    """Parse weather alerts from Jamaica Met Service HTML."""
    soup = BeautifulSoup(html, "lxml")
    alerts = []

    # Try to find alert/forecast sections
    alert_sections = soup.find_all(
        ["div", "section", "article"],
        class_=re.compile(r"alert|warning|forecast|weather", re.I)
    )

    if not alert_sections:
        # Fallback: scan all paragraphs for weather keywords
        alert_sections = soup.find_all(["p", "li"])

    for section in alert_sections:
        text = section.get_text(separator=" ", strip=True)
        if len(text) < 20:
            continue

        severity = classify_weather_severity(text)
        alert_type = classify_alert_type(text)

        # Try to extract parish mentions
        parishes_found = [p for p in JAMAICA_PARISHES if p.lower() in text.lower()]
        target_parishes = parishes_found if parishes_found else ["All Parishes"]

        for parish in target_parishes:
            alerts.append({
                "alert_type": alert_type,
                "severity": severity,
                "parish": parish,
                "description": text[:500],
                "valid_until": (datetime.utcnow() + timedelta(hours=6)).isoformat(),
            })

    # De-duplicate by description prefix
    seen = set()
    unique_alerts = []
    for a in alerts:
        key = a["description"][:80]
        if key not in seen:
            seen.add(key)
            unique_alerts.append(a)

    return unique_alerts[:20]  # cap at 20 alerts


def scrape_weather() -> int:
    """Main weather scrape. Returns number of alerts inserted."""
    start = time.time()
    logger.info(f"Scraping weather from {MET_WEATHER_URL}")
    count = 0

    try:
        resp = requests.get(MET_WEATHER_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        alerts = parse_weather_from_html(resp.text)

        if not alerts:
            # Insert a default "clear" alert if nothing found
            alerts = [{
                "alert_type": "clear",
                "severity": "low",
                "parish": "All Parishes",
                "description": "No active weather alerts. Conditions are favourable for travel.",
                "valid_until": (datetime.utcnow() + timedelta(hours=3)).isoformat(),
            }]

        for alert in alerts:
            insert_weather_alert(alert)
            count += 1

        duration_ms = int((time.time() - start) * 1000)
        log_scrape("weather", "success", count, duration_ms=duration_ms)
        logger.info(f"✅ Weather: {count} alerts stored in {duration_ms}ms")

    except requests.RequestException as e:
        duration_ms = int((time.time() - start) * 1000)
        log_scrape("weather", "failed", 0, str(e), duration_ms)
        logger.error(f"❌ Weather scrape failed: {e}")
        # Insert safe default
        insert_weather_alert({
            "alert_type": "clear",
            "severity": "low",
            "parish": "All Parishes",
            "description": "Weather data unavailable. Assuming normal conditions.",
            "valid_until": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        })
        count = 1

    return count


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
    from storage.db import init_db
    init_db()
    n = scrape_weather()
    print(f"Done. {n} weather alerts stored.")
