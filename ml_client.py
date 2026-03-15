"""
api/ml_client.py
Client for Ayanna's live ML API.
Translates scraped route/traffic/weather data into ML predictions
and stores results back in the database.

ML API base: https://splenial-kareem-manically.ngrok-free.dev
"""

import sys
import os
import json
import logging
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_TIMEOUT
from storage.db import get_all_routes, get_traffic_events, get_weather_alerts, insert_ml_prediction, log_scrape

logger = logging.getLogger("transiq.ml_client")

ML_BASE_URL = "https://splenial-kareem-manically.ngrok-free.dev"
ML_HEADERS  = {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "true",
}

# Map internal route type → ML API transport_type label
TRANSPORT_TYPE_MAP = {
    "taxi":    "Route Taxi",
    "bus":     "JUTC Bus",
    "express": "Knutsford Express",
    "juta":    "JUTA",
    "uber":    "Uber",
}

# Hour buckets that represent peak vs off-peak
def _current_hour() -> int:
    return datetime.now().hour

def _current_day() -> str:
    return datetime.now().strftime("%a")  # Mon, Tue, …

def _is_weekend() -> int:
    return 1 if datetime.now().weekday() >= 5 else 0


# ─── Low-level API calls ──────────────────────────────────────────────────────

def ml_health() -> bool:
    """Ping the ML API health endpoint. Returns True if all 6 models are loaded."""
    try:
        resp = requests.get(f"{ML_BASE_URL}/health", headers=ML_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"ML API health: {data}")
        return True
    except Exception as e:
        logger.error(f"ML API health check failed: {e}")
        return False


def ml_get_hubs() -> list[str]:
    """Fetch the list of hubs the ML model knows about."""
    try:
        resp = requests.get(f"{ML_BASE_URL}/hubs", headers=ML_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("hubs", [])
    except Exception as e:
        logger.error(f"ML hubs fetch failed: {e}")
        return []


def ml_plan(start_hub: str, end_hub: str, budget_jmd: float,
            hour_of_day: int = None, day_of_week: str = None,
            is_weekend: int = None) -> dict | None:
    """
    Call POST /plan on Ayanna's ML API.
    Returns the full plans dict or None on failure.
    """
    payload = {
        "start_hub":    start_hub,
        "end_hub":      end_hub,
        "budget_jmd":   budget_jmd,
        "hour_of_day":  hour_of_day  if hour_of_day  is not None else _current_hour(),
        "day_of_week":  day_of_week  if day_of_week  is not None else _current_day(),
        "is_weekend":   is_weekend   if is_weekend   is not None else _is_weekend(),
    }
    try:
        resp = requests.post(
            f"{ML_BASE_URL}/plan",
            headers=ML_HEADERS,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"ML /plan failed ({start_hub}→{end_hub}): {e}")
        return None


def ml_predict(start_hub: str, end_hub: str, transport_type: str,
               distance_km: float, hour_of_day: int = None,
               day_of_week: str = None, is_weekend: int = None) -> dict | None:
    """
    Call POST /predict on Ayanna's ML API for a single route.
    Returns predictions dict or None on failure.
    """
    payload = {
        "start_hub":      start_hub,
        "end_hub":        end_hub,
        "transport_type": transport_type,
        "distance_km":    distance_km,
        "hour_of_day":    hour_of_day  if hour_of_day  is not None else _current_hour(),
        "day_of_week":    day_of_week  if day_of_week  is not None else _current_day(),
        "is_weekend":     is_weekend   if is_weekend   is not None else _is_weekend(),
    }
    try:
        resp = requests.post(
            f"{ML_BASE_URL}/predict",
            headers=ML_HEADERS,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"ML /predict failed ({start_hub}→{end_hub} via {transport_type}): {e}")
        return None


# ─── High-level: push all routes through ML and persist ──────────────────────

# Distance cache — populated by Google Maps on first call, falls back to approximations
_distance_cache = {}

# Approximate distance_km for known hub pairs (fallback if Maps API fails)
APPROX_DISTANCES = {
    ("Half Way Tree",     "Portmore"):           18.0,
    ("Half Way Tree",     "Downtown Kingston"):   5.5,
    ("Downtown Kingston", "Spanish Town"):       20.0,
    ("Half Way Tree",     "Papine"):              6.0,
    ("New Kingston",      "Constant Spring"):     8.5,
    ("Downtown Kingston", "Matilda's Corner"):    5.0,
    ("Half Way Tree",     "Meadowbrook"):         4.0,
    ("Downtown Kingston", "Stony Hill"):         14.0,
    ("Gregory Park",      "Downtown Kingston"):  22.0,
    ("Old Harbour",       "Downtown Kingston"):  45.0,
    ("Linstead",          "Downtown Kingston"):  38.0,
    ("Spanish Town",      "Half Way Tree"):      16.0,
    ("Montego Bay",       "Kingston"):          190.0,
    ("Kingston",          "Ocho Rios"):          85.0,
    ("Kingston",          "Negril"):            210.0,
}


def _fetch_distance_km(origin: str, destination: str) -> float:
    """
    Get real driving distance via Google Maps Distance Matrix API.
    Falls back to hardcoded approximation if API call fails.
    """
    key = (origin, destination)
    if key in _distance_cache:
        return _distance_cache[key]

    try:
        from config import GOOGLE_MAPS_API_KEY, GMAPS_TRAFFIC_URL
        resp = requests.get(
            GMAPS_TRAFFIC_URL,
            params={
                "origins":      f"{origin}, Jamaica",
                "destinations": f"{destination}, Jamaica",
                "key":          GOOGLE_MAPS_API_KEY,
            },
            headers={"ngrok-skip-browser-warning": "true"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "OK":
            dist_m = data["rows"][0]["elements"][0]["distance"]["value"]
            dist_km = round(dist_m / 1000, 2)
            _distance_cache[key] = dist_km
            logger.debug(f"Maps distance {origin}→{destination}: {dist_km} km")
            return dist_km
    except Exception as e:
        logger.debug(f"Maps distance fetch failed ({origin}→{destination}): {e}")

    # Fallback
    return APPROX_DISTANCES.get(key) or APPROX_DISTANCES.get((destination, origin)) or 15.0


def _get_distance(origin: str, destination: str) -> float:
    return _fetch_distance_km(origin, destination)


def push_routes_through_ml(hour_of_day: int = None,
                            day_of_week: str = None,
                            is_weekend:  int = None) -> int:
    """
    For every active route in the DB, call the ML API /predict
    and store the prediction back in ml_predictions table.
    Returns number of predictions stored.
    """
    start = time.time()
    routes = get_all_routes()
    hour    = hour_of_day if hour_of_day is not None else _current_hour()
    day     = day_of_week if day_of_week is not None else _current_day()
    weekend = is_weekend  if is_weekend  is not None else _is_weekend()

    logger.info(f"Pushing {len(routes)} routes through ML API (hour={hour}, day={day})")

    count = 0
    for route in routes:
        origin      = route.get("origin") or ""
        destination = route.get("destination") or ""
        if not origin or not destination:
            continue

        transport_type = TRANSPORT_TYPE_MAP.get(route.get("type", "taxi"), "Route Taxi")
        distance_km    = _get_distance(origin, destination)

        preds = ml_predict(
            start_hub=origin,
            end_hub=destination,
            transport_type=transport_type,
            distance_km=distance_km,
            hour_of_day=hour,
            day_of_week=day,
            is_weekend=weekend,
        )

        if preds:
            insert_ml_prediction({
                "route_id":          route["route_id"],
                "origin":            origin,
                "destination":       destination,
                "departure_time":    datetime.utcnow().isoformat(),
                "eta_minutes":       preds.get("eta_minutes"),
                "fare_jmd":          preds.get("fare_jmd"),
                "congestion_level":  preds.get("traffic_label"),
                "best_departure":    str(preds.get("best_departure_hour")),
                "reliability_score": preds.get("reliability_score"),
                "safety_score":      preds.get("safety_score"),
                "model_version":     "ayanna-v1",
            })
            count += 1

        time.sleep(0.1)  # be polite to the API

    duration_ms = int((time.time() - start) * 1000)
    log_scrape("ml_predictions", "success" if count > 0 else "partial", count, duration_ms=duration_ms)
    logger.info(f"✅ ML predictions: {count}/{len(routes)} routes processed in {duration_ms}ms")
    return count


def get_ml_plan_enriched(origin: str, destination: str,
                          budget_jmd: float = 9999,
                          hour_of_day: int = None,
                          day_of_week: str = None,
                          is_weekend:  int = None) -> dict | None:
    """
    Call ML /plan and enrich with scraped context (traffic + weather).
    This is what data_api.py's POST /api/plan calls.
    Returns None if ML API is unreachable (caller falls back to local planner).
    """
    result = ml_plan(
        start_hub=origin,
        end_hub=destination,
        budget_jmd=budget_jmd,
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        is_weekend=is_weekend,
    )

    if not result or result.get("status") != "success":
        return None

    # Enrich with live scraped context
    traffic = get_traffic_events()
    weather = get_weather_alerts()

    # Find traffic events relevant to this trip
    origin_l = origin.lower()
    dest_l   = destination.lower()
    relevant_traffic = [
        e for e in traffic
        if origin_l in (e.get("area") or "").lower()
        or dest_l   in (e.get("area") or "").lower()
        or origin_l in (e.get("road") or "").lower()
        or dest_l   in (e.get("road") or "").lower()
    ][:3]

    # Current weather note
    weather_note = ""
    if weather:
        w = weather[0]
        if w.get("severity") in ("high", "critical"):
            weather_note = f"⚠️ {w.get('description', '')[:100]}"

    # Annotate each plan with step-by-step and weather
    plans_out = []
    for plan_type in ["fastest", "cheapest", "balanced"]:
        plan = result["plans"].get(plan_type)
        if not plan:
            continue

        route_info = plan.get("route", {})
        preds      = plan.get("predictions", {})

        plans_out.append({
            "plan_type":              plan_type,
            "label":                  plan_type.capitalize(),
            "icon":                   {"fastest": "⚡", "cheapest": "💰", "balanced": "⚖️"}[plan_type],
            "transport_type":         route_info.get("transport_type"),
            "within_budget":          plan.get("within_budget", True),
            "total_fare_jmd":         preds.get("fare_jmd"),
            "total_fare_usd":         round((preds.get("fare_jmd") or 0) * 0.0064, 2),
            "estimated_duration_min": preds.get("eta_minutes"),
            "congestion":             preds.get("traffic_label"),
            "congestion_multiplier":  preds.get("traffic_multiplier"),
            "best_departure_hour":    preds.get("best_departure_hour"),
            "reliability_score":      preds.get("reliability_score"),
            "safety_score":           preds.get("safety_score"),
            "weather_note":           weather_note,
            "steps":                  _build_steps(route_info, origin, destination),
            "ml_source":              "ayanna-v1",
        })

    return {
        "origin":          origin,
        "destination":     destination,
        "budget_jmd":      budget_jmd,
        "generated_at":    datetime.utcnow().isoformat(),
        "plans":           plans_out,
        "traffic_events":  relevant_traffic,
        "weather_alerts":  weather[:2],
        "data_source":     "live_ml",
    }


def _build_steps(route_info: dict, origin: str, destination: str) -> list[dict]:
    """Build step-by-step journey from ML route info."""
    transport = route_info.get("transport_type", "Route Taxi")
    icon = {
        "Route Taxi":        "🚕",
        "JUTC Bus":          "🚌",
        "Knutsford Express": "🚍",
        "JUTA":              "🚐",
        "Uber":              "🚗",
    }.get(transport, "🚕")

    return [
        {"step": 1, "action": "walk_to_stop",  "icon": "🚶",
         "label": f"Walk to {origin} stop",       "location": origin,      "duration_min": 3},
        {"step": 2, "action": "board",          "icon": icon,
         "label": f"Board {transport}: {origin} → {destination}",
         "location": origin, "alight_at": destination,                      "duration_min": None},
        {"step": 3, "action": "arrive",         "icon": "📍",
         "label": f"Arrive at {destination}",     "location": destination, "duration_min": 0},
    ]


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    print("Testing ML API connection...")
    if ml_health():
        print("✅ ML API is live\n")

        print("Fetching ML hubs...")
        hubs = ml_get_hubs()
        print(f"  {len(hubs)} hubs: {hubs[:5]}...\n")

        print("Testing /plan: Spanish Town → Half Way Tree @ 7am Monday...")
        result = ml_plan("Spanish Town", "Half Way Tree", 500, hour_of_day=7, day_of_week="Mon", is_weekend=0)
        if result:
            print(json.dumps(result, indent=2))
    else:
        print("❌ ML API unreachable")
