"""
scheduler/auto_refresh.py
15-minute auto-refresh scheduler for all scrapers.
Runs continuously and refreshes route, fare, traffic, and weather data.

Usage:
    python scheduler/auto_refresh.py          # start scheduler (blocks)
    python scheduler/auto_refresh.py --once   # run all scrapers once and exit
"""

import sys
import os
import time
import logging
import argparse
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_INTERVAL_MINUTES
from storage.db import init_db

logger = logging.getLogger("transiq.scheduler")


def run_scraper(name: str, fn):
    """Run a single scraper with error isolation."""
    try:
        logger.info(f"[{name}] Starting scrape...")
        count = fn()
        logger.info(f"[{name}] Done — {count} records")
        return count
    except Exception as e:
        logger.error(f"[{name}] Scraper crashed: {e}", exc_info=True)
        return 0


def run_all_scrapers():
    """Run every scraper in sequence, then push results through ML."""
    # Import here to allow DB init before import
    from scrapers.ta_routes_scraper import scrape_ta_routes
    from scrapers.ta_fares_scraper   import scrape_ta_fares
    from scrapers.jutc_scraper       import scrape_jutc
    from scrapers.weather_scraper    import scrape_weather
    from scrapers.traffic_scraper    import scrape_traffic

    start = datetime.utcnow()
    logger.info(f"=== Refresh cycle started at {start.isoformat()} ===")

    results = {
        "ta_routes": run_scraper("ta_routes", scrape_ta_routes),
        "ta_fares":  run_scraper("ta_fares",  scrape_ta_fares),
        "jutc":      run_scraper("jutc",       scrape_jutc),
        "weather":   run_scraper("weather",    scrape_weather),
        "traffic":   run_scraper("traffic",    scrape_traffic),
    }

    # Push all routes through Ayanna's ML API and persist predictions
    try:
        from api.ml_client import push_routes_through_ml
        results["ml_predictions"] = run_scraper("ml_predictions", push_routes_through_ml)
    except Exception as e:
        logger.warning(f"ML prediction push skipped: {e}")
        results["ml_predictions"] = 0

    total = sum(results.values())
    elapsed = (datetime.utcnow() - start).total_seconds()
    logger.info(
        f"=== Refresh cycle complete — {total} records in {elapsed:.1f}s | "
        + " | ".join(f"{k}:{v}" for k, v in results.items())
        + " ==="
    )
    return results


def start_scheduler(interval_minutes: int = SCRAPE_INTERVAL_MINUTES):
    """Start the background refresh loop. Blocks until interrupted."""
    logger.info(f"Scheduler starting — refresh every {interval_minutes} minutes")

    # Run immediately on startup
    run_all_scrapers()

    interval_seconds = interval_minutes * 60
    while True:
        logger.info(f"Next refresh in {interval_minutes} minutes...")
        time.sleep(interval_seconds)
        run_all_scrapers()


def start_scheduler_thread(interval_minutes: int = SCRAPE_INTERVAL_MINUTES) -> threading.Thread:
    """
    Start the scheduler in a background daemon thread.
    Returns the thread so the caller can join or check it.
    Used by run_all.py to run scheduler + API server together.
    """
    t = threading.Thread(
        target=start_scheduler,
        args=(interval_minutes,),
        daemon=True,
        name="scraper-scheduler"
    )
    t.start()
    logger.info("Scheduler thread started")
    return t


if __name__ == "__main__":
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s"
    )
    parser = argparse.ArgumentParser(description="TransIQ auto-refresh scheduler")
    parser.add_argument("--once",     action="store_true", help="Run all scrapers once and exit")
    parser.add_argument("--interval", type=int, default=SCRAPE_INTERVAL_MINUTES,
                        help=f"Refresh interval in minutes (default: {SCRAPE_INTERVAL_MINUTES})")
    args = parser.parse_args()

    init_db()

    if args.once:
        results = run_all_scrapers()
        print("\nScrape results:")
        for k, v in results.items():
            print(f"  {k:15s}: {v} records")
    else:
        try:
            start_scheduler(args.interval)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user.")
