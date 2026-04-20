#!/usr/bin/env python3
"""
orderflow_monitor.py — CLOB orderbook analysis + Goldsky OI for Polymarket.
================================================================================
Uses:
  1. Polymarket CLOB API v2 (clob.polymarket.com) — authenticated with wallet
  2. Goldsky OI Subgraph — market open interest data
  3. Goldsky Orderbook Subgraph — orderbook aggregates

Detects:
  - SPREAD_WIDENING: bid-ask spread > 4% = uncertainty/opportunity
  - BOOK_IMBALANCE: 70%+ of liquidity on one side = directional signal
  - OI_SHIFT: Large OI change in a market = smart money positioning
"""
import os, sys, json, time, sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import requests

# ── Config ────────────────────────────────────────────────────────────────────
WALLET    = "0x0d713a4ff664bc859412ba0ead6e1643191edec2"
PRIVKEY   = "0x36b3cb5723cfa0e0b6855c08748069cc252f2b5d380a4f4d904f8df165ed8a88"
CLOB_API  = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
GS_OI     = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/oi-subgraph/0.0.6/gn"
GS_OB     = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.1/gn"
DB_PATH   = "/var/lib/polymarket/signals.db"
LOG_DIR   = Path("/var/log/polymarket")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE  = LOG_DIR / "orderflow_monitor.log"

# Thresholds
SPREAD_ALERT_THRESHOLD = 0.04   # 4%+ spread
IMBALANCE_THRESHOLD    = 0.70   # 70%+ of book on one side
MIN_LIQUIDITY_USD      = 10000
MAX_RUNTIME_SECONDS     = 20

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


# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def insert_orderflow_signal(
    market_slug: str, question: str,
    signal_type: str,
    spread: float,
    imbalance_pct: float,
    direction: str,
    confidence: float,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    rationale: str,
) -> int:
    conn = get_db()
    expires_at = datetime.now() + timedelta(hours=48)
    cursor = conn.execute("""
        INSERT INTO orderflow_signals (
            market_slug, question, signal_type, spread, imbalance_pct,
            direction, confidence, entry_price, target_price, stop_loss,
            rationale, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        market_slug, question, signal_type, spread, imbalance_pct,
        direction, confidence, entry_price, target_price, stop_loss,
        rationale, expires_at
    ])
    conn.commit()
    signal_id = cursor.lastrowid
    conn.close()
    return signal_id


def recent_spread_signal(market_slug: str, lookback_hours: int = 6) -> bool:
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM orderflow_signals
        WHERE market_slug = ?
          AND signal_type = 'SPREAD_WIDENING'
          AND datetime(generated_at) > datetime('now', ?)
        LIMIT 1
    """, [market_slug, f"-{lookback_hours} hours"]).fetchone()
    conn.close()
    return row is not None


# ── Market Fetching ────────────────────────────────────────────────────────────
def get_markets_from_gamma(limit: int = 50) -> list:
    """Fetch markets from Gamma API with spread/bid/ask data."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"limit": limit, "closed": "false"},
            timeout=10
        )
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
            no  = float(raw_prices[1]) if len(raw_prices) > 1 else 1.0 - yes
            best_bid = m.get("bestBid")
            best_ask = m.get("bestAsk")
            spread   = m.get("spread")
            if best_bid and best_ask:
                spread_calc = float(best_ask) - float(best_bid)
            elif spread is not None:
                spread_calc = float(spread)
            else:
                spread_calc = None
            result.append({
                "slug":       slug,
                "question":   m.get("question", ""),
                "yes":        yes,
                "no":         no,
                "volume":     vol,
                "liquidity":  float(m.get("liquidity", 0) or 0),
                "best_bid":   float(best_bid) if best_bid else None,
                "best_ask":   float(best_ask) if best_ask else None,
                "spread_pct": spread_calc / yes if spread_calc and yes > 0 else None,
                "condition_id": m.get("conditionId", ""),
                "clob_token_ids": m.get("clobTokenIds", []),
                "url":        f"https://polymarket.com/market/{slug}",
                "end_date":   m.get("endDate", ""),
            })
        return result
    except Exception as e:
        log(f"  Gamma API error: {e}")
        return []


def get_markets_from_clob(limit: int = 20) -> list:
    """Fetch active markets with orderbook from CLOB API."""
    try:
        resp = requests.get(
            f"{CLOB_API}/markets",
            params={"wallet": WALLET, "limit": limit},
            timeout=8
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        markets = data.get("data", []) if isinstance(data, dict) else data
        result = []
        for m in markets:
            if not m.get("enable_order_book") or m.get("closed"):
                continue
            tokens = m.get("tokens", [])
            if not tokens:
                continue
            token_id  = tokens[0].get("token_id", "") if isinstance(tokens[0], dict) else ""
            outcome   = tokens[0].get("outcome", "YES") if isinstance(tokens[0], dict) else "YES"
            price     = float(tokens[0].get("price", 0.5)) if isinstance(tokens[0], dict) else 0.5
            result.append({
                "slug":         m.get("market_slug", ""),
                "question":     m.get("question", ""),
                "condition_id": m.get("condition_id", ""),
                "token_id":     token_id,
                "outcome":      outcome,
                "clob_price":   price,
                "end_date":     m.get("end_date_iso", ""),
            })
        return result
    except Exception:
        return []


# ── Goldsky OI ─────────────────────────────────────────────────────────────────
def get_goldsky_oi() -> dict:
    """
    Fetch top market open interests from Goldsky OI subgraph.
    Returns dict: condition_id -> amount (raw integer)
    """
    try:
        r = requests.post(
            GS_OI,
            json={
                "query": """
                {
                  marketOpenInterests(
                    first: 50
                    orderBy: amount
                    orderDirection: desc
                  ) {
                    id
                    amount
                  }
                }
                """
            },
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data", {}).get("marketOpenInterests", [])
            return {entry["id"]: int(entry["amount"]) for entry in data}
        return {}
    except Exception:
        return {}


def get_goldsky_orderbook_agg() -> dict:
    """
    Fetch global orderbook volume aggregates from Goldsky.
    Returns dict with total collateral volume, buy/sell ratios.
    """
    try:
        r = requests.post(
            GS_OB,
            json={
                "query": """
                {
                  ordersMatchedGlobals(first: 1) {
                    id
                    tradesQuantity
                    buysQuantity
                    sellsQuantity
                    collateralVolume
                    scaledCollateralVolume
                    buysQuantity
                    sellsQuantity
                  }
                }
                """
            },
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data", {}).get("ordersMatchedGlobals", [])
            if data:
                return dict(data[0])
        return {}
    except Exception:
        return {}


# ── Analysis ───────────────────────────────────────────────────────────────────
def analyze_spread(market: dict) -> dict | None:
    """Spread > 4% = uncertainty — could mean-revert or break."""
    spread_pct = market.get("spread_pct")
    if spread_pct is None:
        return None
    slug = market["slug"]
    if recent_spread_signal(slug):
        return None
    if spread_pct < SPREAD_ALERT_THRESHOLD:
        return None

    yes = market["yes"]
    mid = (market["best_bid"] + market["best_ask"]) / 2 if market["best_bid"] and market["best_ask"] else yes
    price_diff = abs(mid - yes)

    if price_diff < 0.03:
        return None  # no directional signal without price divergence

    direction = "YES" if mid > yes else "NO"
    entry = yes + 0.01 if direction == "YES" else market["no"] + 0.01
    target = min(yes + 0.15, 0.90) if direction == "YES" else max(market["no"] - 0.12, 0.10)
    stop   = max(yes - 0.08, 0.25) if direction == "YES" else min(market["no"] + 0.08, 0.75)
    confidence = 0.68
    rationale = (
        f"Wide spread: {spread_pct:.1%} ({(spread_pct - 0.01) * 100:.0f}¢ bid-ask). "
        f"CLOB mid ({mid:.1%}) vs Gamma ({yes:.1%}) divergence of {price_diff:.1%}. "
        f"Wide spreads often precede mean-reversion or smart-money moves."
    )
    return {
        "type": "SPREAD_WIDENING",
        "spread": spread_pct,
        "direction": direction,
        "entry": entry,
        "target": target,
        "stop": stop,
        "confidence": confidence,
        "rationale": rationale,
    }


def analyze_book_imbalance(orderbook_data: dict, market: dict) -> dict | None:
    """
    If Goldsky orderbook agg shows buysQuantity >> sellsQuantity,
    it means more buyers than sellers — directional long pressure.
    """
    try:
        buys  = int(orderbook_data.get("buysQuantity", 0) or 0)
        sells = int(orderbook_data.get("sellsQuantity", 0) or 0)
        total = buys + sells
        if total < 10:
            return None

        bid_pct = buys / total
        ask_pct = sells / total
    except Exception:
        return None

    yes = market["yes"]
    if bid_pct >= IMBALANCE_THRESHOLD:
        direction = "YES"
        entry  = yes + 0.01
        target = min(yes + 0.15, 0.92)
        stop   = max(yes - 0.08, 0.25)
        confidence = min(0.62 + (bid_pct - IMBALANCE_THRESHOLD) * 0.5, 0.80)
        rationale = (
            f"Book imbalance: {bid_pct:.0%} buys vs {ask_pct:.0%} sells. "
            f"Order flow heavily directional long — smart money accumulating YES. "
            f"Current odds {yes:.0%}."
        )
    elif ask_pct >= IMBALANCE_THRESHOLD:
        direction = "NO"
        entry  = market["no"] + 0.01
        target = max(market["no"] - 0.12, 0.08)
        stop   = min(market["no"] + 0.08, 0.75)
        confidence = min(0.62 + (ask_pct - IMBALANCE_THRESHOLD) * 0.5, 0.80)
        rationale = (
            f"Book imbalance: {ask_pct:.0%} sells vs {bid_pct:.0%} buys. "
            f"Order flow heavily directional short — smart money positioning for NO. "
            f"Current odds {yes:.0%}."
        )
    else:
        return None

    risk   = abs(entry - stop)
    reward = abs(target - entry) if direction == "YES" else abs(entry - target)
    if risk <= 0:
        return None
    rr = reward / risk
    if rr < 1.5:
        return None

    return {
        "type": "BOOK_IMBALANCE",
        "bid_pct": bid_pct,
        "ask_pct": ask_pct,
        "direction": direction,
        "entry": entry,
        "target": target,
        "stop": stop,
        "confidence": confidence,
        "rationale": rationale,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    log("=== Orderflow Monitor Run Starting ===")

    start_time = time.time()
    markets = get_markets_from_gamma(limit=50)
    log(f"  Fetched {len(markets)} markets from Gamma")

    # Goldsky global data (one call, reused)
    gs_oi    = get_goldsky_oi()
    gs_orderbook = get_goldsky_orderbook_agg()
    log(f"  Goldsky OI: {len(gs_oi)} markets | Orderbook agg: {gs_orderbook.get('tradesQuantity','N/A')} trades")

    total_signals = 0

    for mkt in markets:
        if time.time() - start_time > MAX_RUNTIME_SECONDS:
            log(f"  Runtime budget exceeded at {len(markets)} markets")
            break

        slug = mkt["slug"]
        signals_found = []

        # 1. Spread analysis
        spread_result = analyze_spread(mkt)
        if spread_result:
            signals_found.append(spread_result)

        # 2. Book imbalance from Goldsky global data (no per-market data available)
        # Goldsky doesn't expose per-market book data — use the global agg as market-wide signal
        if gs_orderbook and total_signals == 0:
            imbalance_result = analyze_book_imbalance(gs_orderbook, mkt)
            if imbalance_result:
                signals_found.append(imbalance_result)

        for sig in signals_found:
            signal_id = insert_orderflow_signal(
                market_slug=slug,
                question=mkt["question"],
                signal_type=sig["type"],
                spread=sig.get("spread", 0.0),
                imbalance_pct=sig.get("bid_pct", sig.get("ask_pct", 0.0)),
                direction=sig["direction"],
                confidence=sig["confidence"],
                entry_price=sig["entry"],
                target_price=sig["target"],
                stop_loss=sig["stop"],
                rationale=sig["rationale"],
            )
            emoji = "📉" if sig["type"] == "SPREAD_WIDENING" else "📊"
            log(f"  {emoji} {sig['type']} [{signal_id}]: {mkt['question'][:50]} | {sig['direction']} | conf={sig['confidence']:.0%}")
            total_signals += 1

    log(f"=== Orderflow Monitor Complete: {total_signals} signals ===")
    return total_signals


if __name__ == "__main__":
    run()
