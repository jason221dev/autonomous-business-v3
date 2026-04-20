#!/usr/bin/env python3
"""
signals_engine.py — Unified orchestrator for all Polymarket signal generators.
================================================================================
Runs all signal workers, deduplicates, stores to DB.

Workers:
  1. signals_engine_legacy  — Momentum, mean-reversion, contrarian, arbitrage (via pmxt)
  2. news_monitor           — NewsAPI corroboration/contradiction + pmxt market data
  3. whale_monitor          — Large trade detection via pmxt.fetch_trades()
  4. orderflow_monitor      — Orderbook spread analysis via pmxt.fetch_order_book()
  5. catalyst_calendar     — Upcoming event mispricing detection

NOTE: This file IS the orchestrator — it is NOT in the workers list.
"""
import sys, logging, time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/signals-engine.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

sys.path.insert(0, '/opt/polymarket')
from signals_db import init_db, mark_expired


def run_worker(module_name: str, func_name: str = "run") -> dict:
    try:
        logger.info(f"  → Running {module_name}...")
        mod = __import__(module_name, fromlist=[func_name])
        fn  = getattr(mod, func_name, None)
        if fn is None:
            logger.warning(f"  ⚠ {module_name} has no '{func_name}' function")
            return {"worker": module_name, "status": "no_function", "signals": 0}
        result = fn()
        signals = result if isinstance(result, int) else (result or {}).get("signals", 0)
        logger.info(f"  ✓ {module_name}: {signals} signals")
        return {"worker": module_name, "status": "ok", "signals": signals}
    except Exception as e:
        logger.error(f"  ✗ {module_name} failed: {e}")
        return {"worker": module_name, "status": "error", "error": str(e), "signals": 0}


def run():
    logger.info("=" * 60)
    logger.info("Starting unified signals engine...")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")

    init_db()
    mark_expired()
    logger.info("DB initialized, expired signals cleaned")

    # NOTE: Do NOT add this orchestrator (signals_engine) to the workers list
    workers = [
        ("signals_engine_legacy", "run"),
        ("news_monitor",           "run"),
        ("whale_monitor",         "run"),
        ("orderflow_monitor",     "run"),
        ("catalyst_calendar",    "run"),
    ]

    results = []
    for mod_name, fn_name in workers:
        result = run_worker(mod_name, fn_name)
        results.append(result)
        time.sleep(0.5)

    total = sum(
        r.get("signals", 0) if isinstance(r.get("signals"), int)
        else r.get("stored", 0) if isinstance(r.get("stored"), int)
        else 0
        for r in results
    )
    logger.info("=" * 60)
    logger.info(f"All workers complete — {total} total signals generated")
    for r in results:
        icon = "✓" if r["status"] == "ok" else "⚠" if "no_function" in r.get("status","") else "✗"
        n = r.get("signals", 0) if isinstance(r.get("signals"), int) else r.get("stored", 0)
        logger.info(f"  {icon} {r['worker']}: {n} signals ({r['status']})")

    return {"workers": results, "total_signals": total, "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    print(run())
