"""
api/data_api.py
Lightweight REST API server that exposes TransIQ scraped data
to Richard's Spring Boot backend (and Ayanna's ML models).

Runs on port 5050 by default.

Endpoints:
    GET /api/health          — health check + last scrape timestamps
    GET /api/routes          — all routes (optional ?type=taxi|bus|express|juta)
    GET /api/fares           — all fares  (optional ?route_id=...)
    GET /api/hubs            — transport hubs
    GET /api/traffic         — current traffic events
    GET /api/weather         — current weather alerts
    GET /api/plan            — compute 3 travel plans (fastest/cheapest/balanced)
                               POST body: {origin, destination, budget_jmd, departure_time}
"""

import sys
import os
import json
import logging
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import API_HOST, API_PORT
from storage.db import (
    get_all_routes, get_fares, get_traffic_events,
    get_weather_alerts, get_scrape_status,
    get_all_ml_predictions, get_latest_ml_prediction,
)

logger = logging.getLogger("transiq.api")

# Import ML client — graceful if unavailable
try:
    from api.ml_client import get_ml_plan_enriched
    ML_CLIENT_AVAILABLE = True
except Exception:
    ML_CLIENT_AVAILABLE = False
    logger.warning("ml_client not available — /api/plan will use local fallback only")


# ─── Route Planner ────────────────────────────────────────────────────────────

def find_routes_between(origin: str, destination: str) -> list[dict]:
    """Find routes connecting origin to destination."""
    all_routes = get_all_routes()
    origin_l = origin.lower().strip()
    dest_l   = destination.lower().strip()

    direct = []
    via_hub = []

    for r in all_routes:
        hubs = [h.lower() for h in (r.get("hubs") or [])]
        r_origin = (r.get("origin") or "").lower()
        r_dest   = (r.get("destination") or "").lower()

        origin_match = origin_l in r_origin or any(origin_l in h for h in hubs)
        dest_match   = dest_l in r_dest   or any(dest_l   in h for h in hubs)

        if origin_match and dest_match:
            direct.append(r)
        elif origin_match or dest_match:
            via_hub.append(r)

    return direct[:5] or via_hub[:5]


def get_fare_for_route(route_id: str) -> float:
    fares = get_fares(route_id)
    if fares:
        return fares[0]["fare_jmd"]
    return 200.0  # default


def estimate_duration(route: dict, traffic_events: list) -> int:
    """Estimate trip duration in minutes, factoring in traffic."""
    # Base duration estimate from route type
    base = {
        "taxi":    25,
        "bus":     40,
        "express": 120,
        "juta":    90,
        "uber":    30,
    }.get(route.get("type", "taxi"), 30)

    # Check traffic on route hubs
    route_hubs = [h.lower() for h in (route.get("hubs") or [])]
    for event in traffic_events:
        road = (event.get("road") or "").lower()
        area = (event.get("area") or "").lower()
        if any(road in hub or area in hub for hub in route_hubs):
            severity = event.get("severity", "low")
            delay = {"low": 5, "medium": 12, "high": 22, "critical": 40}.get(severity, 0)
            base += delay
            break

    return base


def build_travel_plans(origin: str, destination: str,
                       budget_jmd: float = 9999,
                       departure_time: str = None) -> dict:
    """
    Build three travel plans: fastest, cheapest, balanced.
    Returns a dict compatible with Ayanna's ML endpoint contract.
    """
    matched_routes = find_routes_between(origin, destination)
    traffic = get_traffic_events()
    weather = get_weather_alerts()

    weather_note = ""
    if weather:
        w = weather[0]
        if w.get("severity") in ("high", "critical"):
            weather_note = f"⚠️ Weather alert: {w.get('description','')[:80]}"

    if not matched_routes:
        # Fallback: generic direct route
        matched_routes = [{
            "route_id": "FALLBACK-01",
            "name": f"{origin} to {destination}",
            "type": "taxi",
            "origin": origin,
            "destination": destination,
            "hubs": [origin, destination],
        }]

    plans = {}
    fares_cache = {}

    for route in matched_routes:
        rid = route["route_id"]
        if rid not in fares_cache:
            fares_cache[rid] = get_fare_for_route(rid)

    # ── FASTEST ─────────────────────────────────────────────────────────────
    # Pick route with lowest estimated duration
    sorted_by_time = sorted(
        matched_routes,
        key=lambda r: estimate_duration(r, traffic)
    )
    fastest_route = sorted_by_time[0]
    fastest_duration = estimate_duration(fastest_route, traffic)
    fastest_fare = fares_cache.get(fastest_route["route_id"], 200)

    plans["fastest"] = {
        "plan_type": "fastest",
        "label": "Fastest",
        "icon": "⚡",
        "routes": [fastest_route],
        "total_fare_jmd": fastest_fare,
        "total_fare_usd": round(fastest_fare * 0.0064, 2),
        "estimated_duration_min": fastest_duration,
        "steps": _build_steps(fastest_route, origin, destination),
        "weather_note": weather_note,
        "ml_inputs": {
            "route_id": fastest_route["route_id"],
            "origin": origin,
            "destination": destination,
            "departure_time": departure_time or datetime.utcnow().isoformat(),
            "transport_type": fastest_route.get("type"),
        }
    }

    # ── CHEAPEST ─────────────────────────────────────────────────────────────
    affordable = [r for r in matched_routes if fares_cache.get(r["route_id"], 9999) <= budget_jmd]
    if not affordable:
        affordable = matched_routes

    sorted_by_fare = sorted(affordable, key=lambda r: fares_cache.get(r["route_id"], 9999))
    cheapest_route = sorted_by_fare[0]
    cheapest_fare = fares_cache.get(cheapest_route["route_id"], 200)
    cheapest_duration = estimate_duration(cheapest_route, traffic)

    plans["cheapest"] = {
        "plan_type": "cheapest",
        "label": "Cheapest",
        "icon": "💰",
        "routes": [cheapest_route],
        "total_fare_jmd": cheapest_fare,
        "total_fare_usd": round(cheapest_fare * 0.0064, 2),
        "estimated_duration_min": cheapest_duration,
        "steps": _build_steps(cheapest_route, origin, destination),
        "weather_note": weather_note,
        "ml_inputs": {
            "route_id": cheapest_route["route_id"],
            "origin": origin,
            "destination": destination,
            "departure_time": departure_time or datetime.utcnow().isoformat(),
            "transport_type": cheapest_route.get("type"),
        }
    }

    # ── BALANCED ─────────────────────────────────────────────────────────────
    def balance_score(r):
        fare = fares_cache.get(r["route_id"], 500)
        dur  = estimate_duration(r, traffic)
        # Normalise: lower is better for both; weight 60% time, 40% cost
        fare_norm = fare / 500
        dur_norm  = dur  / 60
        return 0.4 * fare_norm + 0.6 * dur_norm

    sorted_balanced = sorted(matched_routes, key=balance_score)
    balanced_route  = sorted_balanced[0]
    balanced_fare   = fares_cache.get(balanced_route["route_id"], 200)
    balanced_duration = estimate_duration(balanced_route, traffic)

    plans["balanced"] = {
        "plan_type": "balanced",
        "label": "Balanced",
        "icon": "⚖️",
        "routes": [balanced_route],
        "total_fare_jmd": balanced_fare,
        "total_fare_usd": round(balanced_fare * 0.0064, 2),
        "estimated_duration_min": balanced_duration,
        "steps": _build_steps(balanced_route, origin, destination),
        "weather_note": weather_note,
        "ml_inputs": {
            "route_id": balanced_route["route_id"],
            "origin": origin,
            "destination": destination,
            "departure_time": departure_time or datetime.utcnow().isoformat(),
            "transport_type": balanced_route.get("type"),
        }
    }

    return {
        "origin": origin,
        "destination": destination,
        "budget_jmd": budget_jmd,
        "generated_at": datetime.utcnow().isoformat(),
        "plans": [plans["fastest"], plans["cheapest"], plans["balanced"]],
        "traffic_events": traffic[:3],
        "weather_alerts": weather[:2],
    }


def _build_steps(route: dict, origin: str, destination: str) -> list[dict]:
    """Build step-by-step journey breakdown for the Travel Detail screen."""
    hubs = route.get("hubs") or [origin, destination]
    steps = []
    type_label = {
        "taxi": "Route Taxi", "bus": "JUTC Bus",
        "express": "Knutsford Express", "juta": "JUTA",
        "uber": "Uber"
    }.get(route.get("type", "taxi"), "Transport")

    steps.append({
        "step": 1,
        "action": "walk_to_stop",
        "label": f"Walk to {hubs[0]} stop",
        "location": hubs[0],
        "duration_min": 3,
        "icon": "🚶",
    })
    for i in range(len(hubs) - 1):
        steps.append({
            "step": len(steps) + 1,
            "action": "board",
            "label": f"Board {type_label}: {hubs[i]} → {hubs[i+1]}",
            "route_id": route["route_id"],
            "route_name": route["name"],
            "location": hubs[i],
            "alight_at": hubs[i+1],
            "duration_min": 20,
            "icon": {"taxi": "🚕", "bus": "🚌", "express": "🚍", "juta": "🚐", "uber": "🚗"}.get(route.get("type"), "🚕"),
        })
    steps.append({
        "step": len(steps) + 1,
        "action": "arrive",
        "label": f"Arrive at {destination}",
        "location": destination,
        "duration_min": 0,
        "icon": "📍",
    })
    return steps


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class TransIQAPIHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} — {format % args}")

    def send_json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path.rstrip("/")

        if path == "/api/health":
            self.send_json({
                "status": "ok",
                "timestamp": datetime.utcnow().isoformat(),
                "ml_client_available": ML_CLIENT_AVAILABLE,
                "scrape_status": get_scrape_status(),
            })

        elif path == "/api/routes":
            route_type = params.get("type", [None])[0]
            routes = get_all_routes(route_type)
            self.send_json({"count": len(routes), "routes": routes})

        elif path == "/api/fares":
            route_id = params.get("route_id", [None])[0]
            fares = get_fares(route_id)
            self.send_json({"count": len(fares), "fares": fares})

        elif path == "/api/traffic":
            events = get_traffic_events()
            self.send_json({"count": len(events), "events": events})

        elif path == "/api/weather":
            alerts = get_weather_alerts()
            self.send_json({"count": len(alerts), "alerts": alerts})

        elif path == "/api/hubs":
            all_routes = get_all_routes()
            hub_set = set()
            for r in all_routes:
                for h in (r.get("hubs") or []):
                    hub_set.add(h)
            hubs = sorted(hub_set)
            self.send_json({"count": len(hubs), "hubs": hubs})

        elif path == "/api/predictions":
            # Return cached ML predictions stored in DB
            origin = params.get("origin", [None])[0]
            dest   = params.get("destination", [None])[0]
            if origin and dest:
                pred = get_latest_ml_prediction(origin, dest)
                self.send_json(pred or {"error": "No prediction found for this route"})
            else:
                preds = get_all_ml_predictions(limit=100)
                self.send_json({"count": len(preds), "predictions": preds})

        else:
            self.send_json({"error": "Not found", "path": path}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        if path == "/api/plan":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length) or b"{}")
            origin  = body.get("origin", "")
            dest    = body.get("destination", "")
            budget  = float(body.get("budget_jmd", 9999))
            hour    = body.get("hour_of_day")
            day     = body.get("day_of_week")
            weekend = body.get("is_weekend")

            if not origin or not dest:
                self.send_json({"error": "origin and destination are required"}, 400)
                return

            # ── ML-first strategy ────────────────────────────────────────────
            # 1. Try Ayanna's live ML API
            if ML_CLIENT_AVAILABLE:
                ml_result = get_ml_plan_enriched(
                    origin, dest, budget,
                    hour_of_day=hour,
                    day_of_week=day,
                    is_weekend=weekend,
                )
                if ml_result:
                    logger.info(f"Plan served from ML API: {origin} → {dest}")
                    self.send_json(ml_result)
                    return
                else:
                    logger.warning(f"ML API returned no result for {origin}→{dest}, using local fallback")

            # 2. Fallback: local planner using scraped DB data
            logger.info(f"Using local fallback planner: {origin} → {dest}")
            plans = build_travel_plans(origin, dest, budget)
            plans["data_source"] = "local_fallback"
            self.send_json(plans)

        else:
            self.send_json({"error": "Not found"}, 404)


def run_server(host: str = API_HOST, port: int = API_PORT):
    server = HTTPServer((host, port), TransIQAPIHandler)
    logger.info(f"TransIQ Data API running at http://{host}:{port}")
    logger.info(
        "Endpoints: /api/health  /api/routes  /api/fares  /api/traffic  "
        "/api/weather  /api/hubs  /api/predictions  POST /api/plan"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("API server stopped.")
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
    from storage.db import init_db
    init_db()
    run_server()
