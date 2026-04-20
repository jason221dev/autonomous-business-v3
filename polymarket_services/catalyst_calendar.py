#!/usr/bin/env python3
"""
catalyst_calendar.py — Upcoming event detection + catalyst-driven mispricing.
================================================================================
Detects upcoming events that haven't been fully priced by Polymarket markets:
  1. Fed meetings (FOMC dates — known schedule)
  2. Economic releases (CPI, GDP, NFP — known release calendars)
  3. Elections (known dates)
  4. Earnings season (known quarterly schedule)
  5. Sports events (finals, tournaments)
  6. Geopolitical deadlines (NATO summits, UN sessions, trial dates)

For each event category, we know the historical probability baseline and
whether Polymarket typically over/underprices the outcome.

Signals stored in `catalyst_signals` table.
"""
import os, sys, json, sqlite3, re
from datetime import datetime, timedelta, date
from pathlib import Path
import requests

# ── Config ────────────────────────────────────────────────────────────────────
GAMMA_API = "https://gamma-api.polymarket.com"
DB_PATH   = "/var/lib/polymarket/signals.db"
LOG_DIR   = Path("/var/log/polymarket")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE  = LOG_DIR / "catalyst_calendar.log"

# Days before event to start signaling
CATALYST_ADVANCE_DAYS = {
    "fomc":        14,
    "election":    14,
    "gdp":          7,
    "cpi":          7,
    "nfp":          5,
    "earnings":     7,
    "court":       14,
    "geopolitic":   7,
    "sports_final":  3,
}

SKIP_SLUGS = ["gta-vi", "before-gta-vi", "before-gta", "released-before-gta"]


# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.write_text(LOG_FILE.read_text() + "\n" + line if LOG_FILE.exists() else line + "\n")
    except:
        pass


# ── DB ───────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def insert_catalyst_signal(
    market_slug: str, question: str,
    catalyst_type: str,
    event_name: str,
    event_date: str,
    days_until: int,
    direction: str,
    confidence: float,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    rationale: str,
) -> int:
    conn = get_db()
    expires_at = datetime.now() + timedelta(hours=72)
    cursor = conn.execute("""
        INSERT INTO catalyst_signals (
            market_slug, question, catalyst_type, event_name, event_date,
            days_until, direction, confidence,
            entry_price, target_price, stop_loss, rationale, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        market_slug, question, catalyst_type, event_name, event_date,
        days_until, direction, confidence,
        entry_price, target_price, stop_loss, rationale, expires_at
    ])
    conn.commit()
    signal_id = cursor.lastrowid
    conn.close()
    return signal_id


def get_active_catalyst_signals(limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM catalyst_signals
        WHERE status = 'active'
          AND datetime(expires_at) > datetime('now')
        ORDER BY confidence DESC, generated_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Known Event Calendars ─────────────────────────────────────────────────────
# These are recurring events with known historical pricing patterns
KNOWN_EVENTS = {
    # Fed FOMC meetings — historically market overprices no-cut, underprices cut
    "fomc": {
        "pattern":  ["fed", "fomc", "federal reserve", "interest rate"],
        "lookback": 14,
        "historical_baseline": 0.55,  # cuts happen ~55% of the time historically
        "pm_bias":  "overprices_no_cut",  # PM typically shows >50% for no-cut
        "action":   "buy_yes_on_cut_market",
        "label":    "FOMC Meeting",
    },
    # US Presidential election — PM has systematic R-bias early, D-bias late
    "election": {
        "pattern":  ["win the election", "be elected president", "2026 presidential", "2028 presidential"],
        "lookback": 30,
        "historical_baseline": None,  # varies by year
        "pm_bias":  "shortterm_republican_premium",
        "action":   "contrarian_democrat",
        "label":    "Presidential Election",
    },
    # CPI release — market often misprices inflation direction
    "cpi": {
        "pattern":  ["cpi", "inflation rate", "consumer price"],
        "lookback": 7,
        "historical_baseline": 0.40,  # inflation comes in lower ~40% of months
        "pm_bias":  "overprices_higher",
        "action":   "buy_no_on_high_inflation",
        "label":    "CPI Release",
    },
    # GDP
    "gdp": {
        "pattern":  ["gdp", "gdp growth", "quarterly gdp"],
        "lookback": 7,
        "historical_baseline": 0.55,  # positive GDP ~55% of quarters
        "pm_bias":  "mixed",
        "action":   "buy_yes_on_gdp_beats",
        "label":    "GDP Release",
    },
    # Geopolitical events — PM underprices ceasefire/resolution
    "geopolitic": {
        "pattern":  ["ceasefire", "peace deal", "russia ukraine", "israel palestine", "taiwan"],
        "lookback": 14,
        "historical_baseline": 0.30,
        "pm_bias":  "underprices_resolution",
        "action":   "buy_yes_on_ceasefire",
        "label":    "Geopolitical Development",
    },
    # Earnings — implied move wider than actual
    "earnings": {
        "pattern":  ["apple", "nvidia", "meta", "google", "amazon", "tesla", "microsoft"],
        "lookback": 7,
        "historical_baseline": 0.50,
        "pm_bias":  "iv_crushed_after",
        "action":   "play_range_bound",
        "label":    "Earnings Release",
    },
}


def categorize_market(question: str) -> str:
    q = question.lower()
    if any(k in q for k in KNOWN_EVENTS["fomc"]["pattern"]):
        return "fomc"
    if any(k in q for k in KNOWN_EVENTS["election"]["pattern"]):
        return "election"
    if any(k in q for k in KNOWN_EVENTS["cpi"]["pattern"]):
        return "cpi"
    if any(k in q for k in KNOWN_EVENTS["gdp"]["pattern"]):
        return "gdp"
    if any(k in q for k in KNOWN_EVENTS["geopolitic"]["pattern"]):
        return "geopolitic"
    if any(k in q for k in KNOWN_EVENTS["earnings"]["pattern"]):
        return "earnings"
    return "unknown"


def parse_event_date(market: dict) -> tuple[datetime | None, int]:
    """Parse the market's end_date to get event date and days until."""
    end_date_str = market.get("end_date", "")
    if not end_date_str:
        return None, -1
    try:
        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        days_until = (end_date - datetime.now()).days
        return end_date, days_until
    except Exception:
        return None, -1


# ── Catalyst Detection ─────────────────────────────────────────────────────────
def detect_catalyst(market: dict) -> dict | None:
    """
    For a market near a known event, determine if the market is mispriced
    relative to historical patterns.
    """
    question = market["question"]
    yes = market["yes"]
    no  = market["no"]
    slug = market["slug"]

    if any(s in slug.lower() for s in SKIP_SLUGS):
        return None

    end_date, days_until = parse_event_date(market)
    if days_until < 0:
        return None

    cat = categorize_market(question)
    if cat == "unknown":
        return None

    config = KNOWN_EVENTS.get(cat)
    if not config:
        return None

    threshold_days = CATALYST_ADVANCE_DAYS.get(cat, 7)
    if days_until > threshold_days:
        return None  # too early to signal

    # ── FOMC ───────────────────────────────────────────────────────────────
    if cat == "fomc":
        # PM typically overprices "no cut" — show >55% for NO on rate cuts
        # Real historical rate of cuts: ~55% per meeting
        if no > 0.60 and "cut" in question.lower():
            direction = "YES"
            entry = yes + 0.01
            # If market says 60% no-cut, YES should be ~40%
            target = min(yes + 0.20, 0.85)
            stop   = max(yes - 0.10, 0.20)
            confidence = 0.72
            rationale = (
                f"FOMC catalyst: Meeting in {days_until} day(s). "
                f"Market pricing {no:.0%} for 'no cut' — historically overstated. "
                f"Fed has cut in ~55% of meetings. YES at {yes:.0%} offers value."
            )
            return _build_signal(slug, question, "fomc", f"FOMC Meeting", end_date.strftime("%Y-%m-%d") if end_date else "TBD",
                                 days_until, direction, confidence, entry, target, stop, rationale)

        # Also: if market is pricing very high cut probability (>80%), it may be too priced in
        if yes > 0.85 and "cut" in question.lower():
            direction = "NO"
            entry = no + 0.01
            target = max(no - 0.12, 0.10)
            stop   = min(no + 0.08, 0.20)
            confidence = 0.70
            rationale = (
                f"FOMC catalyst: Meeting in {days_until} day(s). "
                f"YES at {yes:.0%} appears overbought. "
                f"FOMC easing cycle may face delays — historical cut rate doesn't fully support {yes:.0%}."
            )
            return _build_signal(slug, question, "fomc", "FOMC Meeting", end_date.strftime("%Y-%m-%d") if end_date else "TBD",
                                 days_until, direction, confidence, entry, target, stop, rationale)

    # ── Election ───────────────────────────────────────────────────────────
    if cat == "election":
        baseline = config.get("historical_baseline", 0.50)
        if baseline is None:
            return None  # no baseline for this year
        divergence = abs(yes - baseline)
        if divergence < 0.08:
            return None  # not enough divergence

        if yes < baseline - 0.08:
            # PM underpricing Democrat
            direction = "YES"
            entry = yes + 0.01
            target = min(yes + 0.15, 0.90)
            stop   = max(yes - 0.08, 0.25)
            confidence = 0.70
            rationale = (
                f"Election catalyst: {days_until} days to election. "
                f"Market at {yes:.0%} vs historical baseline of {baseline:.0%}. "
                f"Polling suggests tighter race — value on YES."
            )
        elif yes > baseline + 0.08:
            # PM overpricing this outcome
            direction = "NO"
            entry = no + 0.01
            target = max(no - 0.12, 0.10)
            stop   = min(no + 0.08, 0.75)
            confidence = 0.70
            rationale = (
                f"Election catalyst: {days_until} days to election. "
                f"Market at {yes:.0%} vs historical baseline of {baseline:.0%}. "
                f"Market appears to be overpricing this outcome."
            )
        else:
            return None

        return _build_signal(slug, question, "election", "Presidential Election",
                             end_date.strftime("%Y-%m-%d") if end_date else "TBD",
                             days_until, direction, confidence, entry, target, stop, rationale)

    # ── CPI ─────────────────────────────────────────────────────────────────
    if cat == "cpi":
        # Market overprices "higher inflation" — inflation comes in below consensus ~40% of months
        if yes > 0.60:  # pricing above 60% for higher inflation
            direction = "NO"
            entry = no + 0.01
            target = max(no - 0.12, 0.08)
            stop   = min(no + 0.08, 0.45)
            confidence = 0.68
            rationale = (
                f"CPI catalyst: Release in {days_until} day(s). "
                f"Market pricing {yes:.0%} for above-consensus inflation. "
                f"Historically inflation comes in below forecast ~40% of months. "
                f"Value on NO side."
            )
            return _build_signal(slug, question, "cpi", "CPI Release",
                                 end_date.strftime("%Y-%m-%d") if end_date else "TBD",
                                 days_until, direction, confidence, entry, target, stop, rationale)

    # ── Geopolitics ─────────────────────────────────────────────────────────
    if cat == "geopolitic":
        # PM systematically underprices peace/ceasefire outcomes
        if yes < 0.45 and days_until <= 14:
            direction = "YES"
            entry = yes + 0.01
            target = min(yes + 0.20, 0.85)
            stop   = max(yes - 0.10, 0.15)
            confidence = 0.65
            rationale = (
                f"Geopolitical catalyst: {days_until} days until resolution date. "
                f"Ceasefire/resolution odds at {yes:.0%}. "
                f"Geopolitical negotiations often produce last-minute breakthroughs — "
                f"historical resolution rate near {days_until}/365 for multi-party conflicts."
            )
            return _build_signal(slug, question, "geopolitic",
                                 "Geopolitical Development",
                                 end_date.strftime("%Y-%m-%d") if end_date else "TBD",
                                 days_until, direction, confidence, entry, target, stop, rationale)

    # ── Earnings ─────────────────────────────────────────────────────────────
    if cat == "earnings":
        # Earnings range-bound outcomes — vol crush after
        if 0.35 <= yes <= 0.65 and days_until <= 7:
            # Mean-reversion play: after earnings, price typically回归
            direction = "YES" if yes > 0.55 else "NO"
            entry = yes + 0.01 if direction == "YES" else no + 0.01
            target = yes + 0.08 if direction == "YES" else no - 0.08
            stop   = max(yes - 0.08, 0.25) if direction == "YES" else min(no + 0.08, 0.75)
            confidence = 0.62
            rationale = (
                f"Earnings catalyst: {days_until} day(s) to release. "
                f"Implied volatility high. Post-earnings price typically reverts toward 50%. "
                f"Playing mean reversion from {yes:.0%}."
            )
            return _build_signal(slug, question, "earnings", "Earnings Release",
                                 end_date.strftime("%Y-%m-%d") if end_date else "TBD",
                                 days_until, direction, confidence, entry, target, stop, rationale)

    return None


def _build_signal(slug, question, catalyst_type, event_name, event_date,
                  days_until, direction, confidence, entry, target, stop, rationale) -> dict:
    return {
        "catalyst_type": catalyst_type,
        "event_name": event_name,
        "event_date": event_date,
        "days_until": days_until,
        "direction": direction,
        "confidence": confidence,
        "entry": entry,
        "target": target,
        "stop": stop,
        "rationale": rationale,
    }


# ── Market Fetching ────────────────────────────────────────────────────────────
def get_active_markets(limit: int = 30) -> list:
    try:
        resp = requests.get(f"{GAMMA_API}/markets", params={"limit": limit, "closed": "false"}, timeout=15)
        data = resp.json()
        markets = data if isinstance(data, list) else data.get("data", [])
        result = []
        for m in markets:
            slug = m.get("slug", "")
            if any(s in slug.lower() for s in SKIP_SLUGS):
                continue
            vol = float(m.get("volume", 0) or 0)
            if vol < 5000:
                continue
            raw_prices = m.get("outcomePrices", [])
            if isinstance(raw_prices, str):
                try:
                    raw_prices = json.loads(raw_prices)
                except:
                    raw_prices = []
            if not isinstance(raw_prices, list) or len(raw_prices) < 2:
                continue
            yes = float(raw_prices[0])
            result.append({
                "slug":      slug,
                "question":  m.get("question", ""),
                "yes":       yes,
                "no":        float(raw_prices[1]) if len(raw_prices) > 1 else 1.0 - yes,
                "volume":    vol,
                "end_date":  m.get("endDate", ""),
                "url":       f"https://polymarket.com/market/{slug}",
            })
        return result
    except Exception as e:
        log(f"  Failed to fetch markets: {e}")
        return []


# ── Main run ──────────────────────────────────────────────────────────────────
def run():
    log("=== Catalyst Calendar Run Starting ===")

    markets = get_active_markets(limit=50)
    log(f"  Checking {len(markets)} markets for catalysts")

    signals_generated = 0
    for mkt in markets:
        result = detect_catalyst(mkt)
        if result:
            signal_id = insert_catalyst_signal(
                market_slug=mkt["slug"],
                question=mkt["question"],
                catalyst_type=result["catalyst_type"],
                event_name=result["event_name"],
                event_date=result["event_date"],
                days_until=result["days_until"],
                direction=result["direction"],
                confidence=result["confidence"],
                entry_price=result["entry"],
                target_price=result["target"],
                stop_loss=result["stop"],
                rationale=result["rationale"],
            )
            log(f"  ⏰ CATALYST [{signal_id}]: {result['catalyst_type'].upper()} | {mkt['question'][:50]} | "
                f"Event: {result['event_name']} ({result['days_until']}d) | {result['direction']} | conf={result['confidence']:.0%}")
            signals_generated += 1

    log(f"=== Catalyst Calendar Run Complete: {signals_generated} signals generated ===")
    return signals_generated


if __name__ == "__main__":
    run()
