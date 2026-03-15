"""
scrapers/traffic_scraper.py
Fetches live traffic data from Google Maps Distance Matrix API
for key Kingston/Jamaica corridors.
Publishes events to Kafka topic 'traffic-events'.
"""

import sys
import os
import time
import logging
import json
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import GOOGLE_MAPS_API_KEY, GMAPS_TRAFFIC_URL, GMAPS_GEOCODE_URL, REQUEST_TIMEOUT
from storage.db import insert_traffic_event, log_scrape

logger = logging.getLogger("transiq.scraper.traffic")

# Cache geocoded locations to avoid repeat API calls
_geocode_cache = {}

def geocode(place: str) -> tuple[float, float] | tuple[None, None]:
    """Return (lat, lng) for a place string using Google Geocoding API."""
    if place in _geocode_cache:
        return _geocode_cache[place]
    try:
        resp = requests.get(
            GMAPS_GEOCODE_URL,
            params={"address": f"{place}, Jamaica", "key": GOOGLE_MAPS_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            result = (loc["lat"], loc["lng"])
            _geocode_cache[place] = result
            return result
    except Exception as e:
        logger.debug(f"Geocode failed for {place}: {e}")
    return (None, None)

# Key corridors to monitor (origin → destination pairs)
KEY_CORRIDORS = [
    {"name": "Washington Blvd (HWT to Portmore)", "origin": "Half Way Tree, Kingston, Jamaica",
     "destination": "Portmore, Saint Catherine, Jamaica"},
    {"name": "Constant Spring Road", "origin": "Half Way Tree, Kingston, Jamaica",
     "destination": "Constant Spring, Kingston, Jamaica"},
    {"name": "Spanish Town Road", "origin": "Downtown Kingston, Jamaica",
     "destination": "Spanish Town, Saint Catherine, Jamaica"},
    {"name": "Dunrobin Ave / Maxfield Ave", "origin": "Downtown Kingston, Jamaica",
     "destination": "Half Way Tree, Kingston, Jamaica"},
    {"name": "Old Hope Road", "origin": "Half Way Tree, Kingston, Jamaica",
     "destination": "Papine, Kingston, Jamaica"},
    {"name": "Barbican Road", "origin": "New Kingston, Jamaica",
     "destination": "Barbican, Kingston, Jamaica"},
    {"name": "Portmore to Downtown Kingston", "origin": "Portmore, Saint Catherine, Jamaica",
     "destination": "Downtown Kingston, Jamaica"},
    {"name": "Gregory Park (Portmore)", "origin": "Gregory Park, Saint Catherine, Jamaica",
     "destination": "Downtown Kingston, Jamaica"},
    {"name": "Stony Hill to Downtown", "origin": "Stony Hill, Kingston, Jamaica",
     "destination": "Downtown Kingston, Jamaica"},
    {"name": "Manor Park Corridor", "origin": "Manor Park, Kingston, Jamaica",
     "destination": "New Kingston, Jamaica"},
]


def classify_severity(duration_in_traffic: int, duration_normal: int) -> str:
    """
    Classify congestion severity based on delay ratio.
    Returns: low | medium | high | critical
    """
    if duration_normal == 0:
        return "medium"
    ratio = duration_in_traffic / duration_normal
    if ratio < 1.2:
        return "low"
    elif ratio < 1.5:
        return "medium"
    elif ratio < 2.0:
        return "high"
    else:
        return "critical"


def fetch_traffic_for_corridor(corridor: dict) -> dict | None:
    """Call Google Maps Distance Matrix API for one corridor."""
    try:
        params = {
            "origins": corridor["origin"],
            "destinations": corridor["destination"],
            "key": GOOGLE_MAPS_API_KEY,
            "departure_time": "now",
            "traffic_model": "best_guess",
        }
        resp = requests.get(GMAPS_TRAFFIC_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK":
            logger.warning(f"Maps API status: {data.get('status')} for {corridor['name']}")
            return None

        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            return None

        duration_normal  = element["duration"]["value"]
        duration_traffic = element.get("duration_in_traffic", {}).get("value", duration_normal)
        distance_m       = element["distance"]["value"]

        severity      = classify_severity(duration_traffic, duration_normal)
        delay_minutes = max(0, (duration_traffic - duration_normal) // 60)

        # Get real lat/lng for origin hub
        origin_name = corridor["origin"].split(",")[0]
        lat, lng = geocode(origin_name)

        return {
            "event_type":  "congestion",
            "road":        corridor["name"],
            "area":        origin_name,
            "severity":    severity,
            "lat":         lat,
            "lng":         lng,
            "description": (
                f"{corridor['name']}: {duration_traffic // 60} min travel time "
                f"(+{delay_minutes} min delay, {distance_m / 1000:.1f} km)"
            ),
            "source":      "google_maps",
            "distance_m":  distance_m,
            "duration_normal_s":  duration_normal,
            "duration_traffic_s": duration_traffic,
            "expires_at":  (datetime.utcnow() + timedelta(minutes=20)).isoformat(),
        }
    except Exception as e:
        logger.error(f"Traffic fetch error for {corridor['name']}: {e}")
        return None


def scrape_traffic() -> int:
    """Fetch traffic for all key corridors and store events."""
    start = time.time()
    logger.info("Scraping live traffic from Google Maps")
    count = 0

    for corridor in KEY_CORRIDORS:
        event = fetch_traffic_for_corridor(corridor)
        if event:
            insert_traffic_event(event)
            count += 1
            # Publish to Kafka if available
            _try_kafka_publish(event)
        time.sleep(0.2)  # respect API rate limits

    duration_ms = int((time.time() - start) * 1000)
    status = "success" if count > 0 else "partial"
    log_scrape("traffic", status, count, duration_ms=duration_ms)
    logger.info(f"✅ Traffic: {count} events stored in {duration_ms}ms")
    return count


def _try_kafka_publish(event: dict):
    """Publish to Kafka if kafka-python is installed."""
    try:
        from kafka import KafkaProducer
        from config import KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_TRAFFIC
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        producer.send(KAFKA_TOPIC_TRAFFIC, event)
        producer.flush()
        logger.debug(f"Kafka: published traffic event for {event['road']}")
    except ImportError:
        pass  # kafka-python not installed, skip
    except Exception as e:
        logger.debug(f"Kafka publish skipped: {e}")


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
    from storage.db import init_db
    init_db()
    n = scrape_traffic()
    print(f"Done. {n} traffic events stored.")
