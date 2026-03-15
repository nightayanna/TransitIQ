"""
synthetic/seed_synthetic.py
Seeds the database with realistic Jamaica transport data.
Run this if live scrapers fail on hackathon day — the app will
still work perfectly with this pre-loaded data.

Usage:
    python synthetic/seed_synthetic.py
    python synthetic/seed_synthetic.py --clear   # wipe & re-seed
"""

import sys
import os
import json
import logging
import argparse
import sqlite3
from datetime import datetime, timedelta
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from storage.db import init_db, upsert_route, upsert_fare, insert_traffic_event, insert_weather_alert, log_scrape
from config import SQLITE_DB_PATH

logger = logging.getLogger("transiq.synthetic")

# ─── Route Taxi Routes ────────────────────────────────────────────────────────
TAXI_ROUTES = [
    {"route_id": "RT-HWT-PORT-01", "name": "Half Way Tree to Portmore (Washington Blvd)", "origin": "Half Way Tree", "destination": "Portmore", "hubs": ["Half Way Tree", "Three Miles", "Portmore"]},
    {"route_id": "RT-HWT-DT-01",   "name": "Half Way Tree to Downtown Kingston",          "origin": "Half Way Tree", "destination": "Downtown Kingston", "hubs": ["Half Way Tree", "Cross Roads", "Downtown Kingston"]},
    {"route_id": "RT-DT-ST-01",    "name": "Downtown Kingston to Spanish Town",           "origin": "Downtown Kingston", "destination": "Spanish Town", "hubs": ["Downtown Kingston", "Three Miles", "Spanish Town"]},
    {"route_id": "RT-HWT-PAP-01",  "name": "Half Way Tree to Papine",                     "origin": "Half Way Tree", "destination": "Papine", "hubs": ["Half Way Tree", "Liguanea", "Papine"]},
    {"route_id": "RT-NK-CS-01",    "name": "New Kingston to Constant Spring",             "origin": "New Kingston", "destination": "Constant Spring", "hubs": ["New Kingston", "Barbican", "Constant Spring"]},
    {"route_id": "RT-DT-MAT-01",   "name": "Downtown Kingston to Matilda's Corner",       "origin": "Downtown Kingston", "destination": "Matilda's Corner", "hubs": ["Downtown Kingston", "Cross Roads", "Matilda's Corner"]},
    {"route_id": "RT-HWT-MBK-01",  "name": "Half Way Tree to Meadowbrook",                "origin": "Half Way Tree", "destination": "Meadowbrook", "hubs": ["Half Way Tree", "Meadowbrook"]},
    {"route_id": "RT-DT-SH-01",    "name": "Downtown Kingston to Stony Hill",             "origin": "Downtown Kingston", "destination": "Stony Hill", "hubs": ["Downtown Kingston", "Constant Spring", "Stony Hill"]},
    {"route_id": "RT-GP-DT-01",    "name": "Gregory Park to Downtown Kingston",           "origin": "Gregory Park", "destination": "Downtown Kingston", "hubs": ["Gregory Park", "Portmore", "Three Miles", "Downtown Kingston"]},
    {"route_id": "RT-OH-DT-01",    "name": "Old Harbour to Downtown Kingston",            "origin": "Old Harbour", "destination": "Downtown Kingston", "hubs": ["Old Harbour", "Spanish Town", "Three Miles", "Downtown Kingston"]},
    {"route_id": "RT-LIN-DT-01",   "name": "Linstead to Downtown Kingston",               "origin": "Linstead", "destination": "Downtown Kingston", "hubs": ["Linstead", "Bog Walk", "Spanish Town", "Downtown Kingston"]},
    {"route_id": "RT-HWT-NK-01",   "name": "Half Way Tree to New Kingston",               "origin": "Half Way Tree", "destination": "New Kingston", "hubs": ["Half Way Tree", "New Kingston"]},
    {"route_id": "RT-DT-WG-01",    "name": "Downtown Kingston to Washington Gardens",     "origin": "Downtown Kingston", "destination": "Washington Gardens", "hubs": ["Downtown Kingston", "Three Miles", "Washington Gardens"]},
    {"route_id": "RT-HWT-BAR-01",  "name": "Half Way Tree to Barbican",                   "origin": "Half Way Tree", "destination": "Barbican", "hubs": ["Half Way Tree", "New Kingston", "Barbican"]},
    {"route_id": "RT-HWT-LIG-01",  "name": "Half Way Tree to Liguanea",                   "origin": "Half Way Tree", "destination": "Liguanea", "hubs": ["Half Way Tree", "Liguanea"]},
]

# ─── JUTC Bus Routes ──────────────────────────────────────────────────────────
BUS_ROUTES = [
    {"route_id": "JUTC-21A", "name": "21A — Half Way Tree to Portmore (Washington Blvd)",  "origin": "Half Way Tree", "destination": "Portmore",           "hubs": ["Half Way Tree", "Three Miles", "Waterford", "Portmore"]},
    {"route_id": "JUTC-21B", "name": "21B — Half Way Tree to Portmore (Dunrobin Ave)",     "origin": "Half Way Tree", "destination": "Portmore",           "hubs": ["Half Way Tree", "Dunrobin Ave", "Angels", "Portmore"]},
    {"route_id": "JUTC-22",  "name": "22 — Downtown Kingston to Spanish Town",             "origin": "Downtown Kingston", "destination": "Spanish Town",   "hubs": ["Downtown Kingston", "Three Miles", "Spanish Town"]},
    {"route_id": "JUTC-23",  "name": "23 — Half Way Tree to Papine",                       "origin": "Half Way Tree", "destination": "Papine",             "hubs": ["Half Way Tree", "Liguanea", "Papine"]},
    {"route_id": "JUTC-24",  "name": "24 — New Kingston to Constant Spring",               "origin": "New Kingston", "destination": "Constant Spring",     "hubs": ["New Kingston", "Barbican", "Constant Spring"]},
    {"route_id": "JUTC-25",  "name": "25 — Downtown Kingston to Matilda's Corner",         "origin": "Downtown Kingston", "destination": "Matilda's Corner","hubs": ["Downtown Kingston", "Cross Roads", "Matilda's Corner"]},
    {"route_id": "JUTC-38",  "name": "38 — Downtown Kingston to Washington Gardens",       "origin": "Downtown Kingston", "destination": "Washington Gardens","hubs": ["Downtown Kingston", "Three Miles", "Washington Gardens"]},
    {"route_id": "JUTC-64",  "name": "64 — Half Way Tree to Three Miles",                  "origin": "Half Way Tree", "destination": "Three Miles",        "hubs": ["Half Way Tree", "Three Miles"]},
    {"route_id": "JUTC-97",  "name": "97 — New Kingston to Barbican",                      "origin": "New Kingston", "destination": "Barbican",            "hubs": ["New Kingston", "Barbican"]},
    {"route_id": "JUTC-99",  "name": "99 — Half Way Tree to Liguanea",                     "origin": "Half Way Tree", "destination": "Liguanea",           "hubs": ["Half Way Tree", "Liguanea"]},
]

# ─── Knutsford Express Routes ─────────────────────────────────────────────────
EXPRESS_ROUTES = [
    {"route_id": "KE-KIN-MBJ-01", "name": "Knutsford Express — Kingston to Montego Bay",   "origin": "New Kingston", "destination": "Montego Bay",   "hubs": ["New Kingston", "Spanish Town", "May Pen", "Mandeville", "Montego Bay"]},
    {"route_id": "KE-KIN-OC-01",  "name": "Knutsford Express — Kingston to Ocho Rios",     "origin": "New Kingston", "destination": "Ocho Rios",     "hubs": ["New Kingston", "Ocho Rios"]},
    {"route_id": "KE-KIN-NEG-01", "name": "Knutsford Express — Kingston to Negril",        "origin": "New Kingston", "destination": "Negril",        "hubs": ["New Kingston", "Mandeville", "Savanna-la-Mar", "Negril"]},
    {"route_id": "KE-KIN-PA-01",  "name": "Knutsford Express — Kingston to Port Antonio",  "origin": "New Kingston", "destination": "Port Antonio",  "hubs": ["New Kingston", "Port Antonio"]},
    {"route_id": "KE-MBJ-KIN-01", "name": "Knutsford Express — Montego Bay to Kingston",   "origin": "Montego Bay", "destination": "New Kingston",   "hubs": ["Montego Bay", "Mandeville", "Spanish Town", "New Kingston"]},
]

# ─── JUTA Routes ──────────────────────────────────────────────────────────────
JUTA_ROUTES = [
    {"route_id": "JUTA-MBJ-OC-01", "name": "JUTA — Montego Bay to Ocho Rios (Tourism)",   "origin": "Montego Bay", "destination": "Ocho Rios",   "hubs": ["Montego Bay", "Falmouth", "Ocho Rios"]},
    {"route_id": "JUTA-MBJ-NEG-01","name": "JUTA — Montego Bay to Negril (Tourism)",      "origin": "Montego Bay", "destination": "Negril",      "hubs": ["Montego Bay", "Negril"]},
    {"route_id": "JUTA-KIN-OC-01", "name": "JUTA — Kingston to Ocho Rios (Tourism)",      "origin": "New Kingston", "destination": "Ocho Rios",  "hubs": ["New Kingston", "Ocho Rios"]},
]

# ─── Fares (JMD) ─────────────────────────────────────────────────────────────
FARE_MAP = {
    # Taxi fares
    "RT-HWT-PORT-01": 200, "RT-HWT-DT-01": 150, "RT-DT-ST-01": 220,
    "RT-HWT-PAP-01": 150,  "RT-NK-CS-01": 180,  "RT-DT-MAT-01": 160,
    "RT-HWT-MBK-01": 160,  "RT-DT-SH-01": 250,  "RT-GP-DT-01": 250,
    "RT-OH-DT-01": 350,    "RT-LIN-DT-01": 400,  "RT-HWT-NK-01": 120,
    "RT-DT-WG-01": 200,    "RT-HWT-BAR-01": 180, "RT-HWT-LIG-01": 140,
    # JUTC flat fare
    "JUTC-21A": 160, "JUTC-21B": 160, "JUTC-22": 160, "JUTC-23": 160,
    "JUTC-24": 160,  "JUTC-25": 160,  "JUTC-38": 160, "JUTC-64": 160,
    "JUTC-97": 160,  "JUTC-99": 160,
    # Knutsford Express
    "KE-KIN-MBJ-01": 3500, "KE-KIN-OC-01": 2200, "KE-KIN-NEG-01": 4000,
    "KE-KIN-PA-01": 2500,  "KE-MBJ-KIN-01": 3500,
    # JUTA
    "JUTA-MBJ-OC-01": 5000, "JUTA-MBJ-NEG-01": 4500, "JUTA-KIN-OC-01": 6000,
}

JMD_TO_USD = 0.0064

TRAFFIC_SAMPLES = [
    {"event_type": "congestion", "road": "Washington Blvd", "area": "Three Miles",       "severity": "high",   "lat": 17.9982, "lng": -76.8397, "description": "Heavy congestion on Washington Blvd approaching Three Miles — add 25 min", "source": "google_maps"},
    {"event_type": "congestion", "road": "Constant Spring Road", "area": "Liguanea",     "severity": "medium", "lat": 18.0145, "lng": -76.7735, "description": "Moderate traffic on Constant Spring Rd near Liguanea — add 10 min",        "source": "google_maps"},
    {"event_type": "congestion", "road": "Spanish Town Road",    "area": "Three Miles",  "severity": "high",   "lat": 17.9878, "lng": -76.8520, "description": "Slow-moving traffic on Spanish Town Road — add 20 min",                   "source": "google_maps"},
    {"event_type": "incident",   "road": "Old Hope Road",        "area": "Papine",       "severity": "medium", "lat": 18.0230, "lng": -76.7540, "description": "Minor accident on Old Hope Road near Papine — use alternate route",       "source": "google_maps"},
    {"event_type": "congestion", "road": "Half Way Tree",        "area": "Half Way Tree","severity": "medium", "lat": 18.0100, "lng": -76.7980, "description": "Busy conditions at Half Way Tree transport hub — normal peak traffic",     "source": "google_maps"},
]

WEATHER_SAMPLES = [
    {"alert_type": "clear", "severity": "low", "parish": "All Parishes", "description": "Fair weather expected island wide. Good conditions for travel."},
    {"alert_type": "rain",  "severity": "medium", "parish": "Kingston", "description": "Scattered afternoon showers expected in Kingston and Saint Andrew. Carry umbrella."},
]


def seed_all(clear_first: bool = False):
    """Seed all synthetic data into the database."""
    init_db()

    if clear_first:
        logger.info("Clearing existing data...")
        conn = sqlite3.connect(SQLITE_DB_PATH)
        for table in ["routes", "fares", "traffic_events", "weather_alerts", "scrape_log"]:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()
        logger.info("Tables cleared.")

    total_routes = 0
    total_fares = 0

    all_routes = (
        [(r, "taxi")    for r in TAXI_ROUTES] +
        [(r, "bus")     for r in BUS_ROUTES] +
        [(r, "express") for r in EXPRESS_ROUTES] +
        [(r, "juta")    for r in JUTA_ROUTES]
    )

    for route_data, route_type in all_routes:
        route = {**route_data, "type": route_type}
        upsert_route(route)
        total_routes += 1

        fare_jmd = FARE_MAP.get(route["route_id"], 200)
        upsert_fare({
            "route_id": route["route_id"],
            "fare_jmd": fare_jmd,
            "fare_usd": round(fare_jmd * JMD_TO_USD, 2),
        })
        total_fares += 1

    for event in TRAFFIC_SAMPLES:
        event["expires_at"] = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
        insert_traffic_event(event)

    for alert in WEATHER_SAMPLES:
        alert["valid_until"] = (datetime.utcnow() + timedelta(hours=6)).isoformat()
        insert_weather_alert(alert)

    log_scrape("synthetic_seed", "success", total_routes)
    logger.info(f"✅ Seeded {total_routes} routes, {total_fares} fares, "
                f"{len(TRAFFIC_SAMPLES)} traffic events, {len(WEATHER_SAMPLES)} weather alerts")
    print(f"\n✅ Synthetic seed complete!")
    print(f"   Routes  : {total_routes}")
    print(f"   Fares   : {total_fares}")
    print(f"   Traffic : {len(TRAFFIC_SAMPLES)}")
    print(f"   Weather : {len(WEATHER_SAMPLES)}")
    print(f"   DB path : {SQLITE_DB_PATH}\n")


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
    parser = argparse.ArgumentParser(description="Seed TransIQ synthetic data")
    parser.add_argument("--clear", action="store_true", help="Clear existing data before seeding")
    args = parser.parse_args()
    seed_all(clear_first=args.clear)
