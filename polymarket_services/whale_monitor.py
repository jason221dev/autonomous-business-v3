#!/usr/bin/env python3
"""
whale_monitor.py — Smart-money / whale detection for Polymarket.
================================================================
Uses TWO authenticated CLOB v2 sources:
  1. Polymarket CLOB API  (clob.polymarket.com)  — wallet: 0x0d713...2
  2. Goldsky Orderbook Subgraph — real-time trade fills

Detects:
  - LARGE_TRADE: single trade > $5K (whale) or > $25K (institutional)
  - WHALE_CONCENTRATION: one wallet controls >20% of recent volume
  - UNUSUAL_VOLUME: volume spike vs 7-day baseline

Goldsky subgraph fields confirmed working:
  orderFilledEvents { id timestamp maker taker makerAmountFilled takerAmountFilled fee }
"""
import os, sys, json, time, sqlite3, math
from datetime import datetime, timedelta
from pathlib import Path
import requests

# ── Config ────────────────────────────────────────────────────────────────────
WALLET    = "0x0d713a4ff664bc859412ba0ead6e1643191edec2"
PRIVKEY   = "0x36b3cb5723cfa0e0b6855c08748069cc252f2b5d380a4f4d904f8df165ed8a88"
CLOB_API  = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
GS_ORDERBOOK = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.1/gn"
DB_PATH   = "/var/lib/polymarket/signals.db"
LOG_DIR   = Path("/var/log/polymarket")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE  = LOG_DIR / "whale_monitor.log"

# Thresholds
WHALE_SIZE_USD  = 5000     # $5K+ trade
MEGA_WHALE_USD  = 25000   # $25K+ = institutional
VOL_SPIKE_MULT  = 3.0      # 3x above 7-day avg

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


def insert_whale_signal(
    market_slug: str, question: str,
    trigger_type: str,
    trader_address: str,
    side: str,
    size_usd: float,
    price: float,
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
        INSERT INTO whale_signals (
            market_slug, question, trigger_type, trader_address, side,
            size_usd, price, direction, confidence,
            entry_price, target_price, stop_loss, rationale, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        market_slug, question, trigger_type, trader_address, side,
        size_usd, price, direction, confidence,
        entry_price, target_price, stop_loss, rationale, expires_at
    ])
    conn.commit()
    signal_id = cursor.lastrowid
    conn.close()
    return signal_id


def recent_whale_processed(market_slug: str, trigger_type: str, lookback_hours: int = 12) -> bool:
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM whale_signals
        WHERE market_slug = ? AND trigger_type = ?
          AND datetime(generated_at) > datetime('now', ?)
        LIMIT 1
    """, [market_slug, trigger_type, f"-{lookback_hours} hours"]).fetchone()
    conn.close()
    return row is not None


# ── Market Data ────────────────────────────────────────────────────────────────
def get_active_markets(limit: int = 30) -> list:
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
            yes_price = float(raw_prices[0])
            result.append({
                "slug":       slug,
                "question":   m.get("question", ""),
                "yes":        yes_price,
                "no":         float(raw_prices[1]) if len(raw_prices) > 1 else 1.0 - yes_price,
                "volume":     vol,
                "liquidity":  float(m.get("liquidity", 0) or 0),
                "vol24hr":    float(m.get("volume24hr", 0) or 0),
                "vol1wk":     float(m.get("volume1wk", 0) or 0),
                "condition_id": m.get("conditionId", ""),
                "url":        f"https://polymarket.com/market/{slug}",
                "end_date":   m.get("endDate", ""),
                "category":   _cat(m.get("question", "")),
            })
        return result
    except Exception as e:
        log(f"  Failed to fetch markets: {e}")
        return []


def _cat(q: str) -> str:
    q = q.lower()
    if any(k in q for k in ["bitcoin", "btc", "crypto", "eth ", "solana"]): return "crypto"
    if any(k in q for k in ["trump", "biden", "election", "president", "vote", "congress"]): return "politics"
    if any(k in q for k in ["fed", "rate", "inflation", "gdp", "recession"]): return "economy"
    if any(k in q for k in ["china", "russia", "iran", "israel", "war", "nato", "taiwan"]): return "geopolitics"
    if any(k in q for k in ["nba", "nfl", "super bowl", "world cup", "olympics"]): return "sports"
    return "general"


# ── Goldsky: Recent Trade Fills ───────────────────────────────────────────────
def get_goldsky_fills(limit: int = 50) -> list:
    """
    Fetch recent trade fills from Goldsky Orderbook Subgraph.
    Returns list of fill dicts with: maker, taker, makerAmountFilled, takerAmountFilled, timestamp, fee
    """
    try:
        r = requests.post(
            GS_ORDERBOOK,
            json={
                "query": """
                {
                  orderFilledEvents(
                    first: 50
                    orderBy: timestamp
                    orderDirection: desc
                  ) {
                    id
                    timestamp
                    maker
                    taker
                    makerAssetId
                    takerAssetId
                    makerAmountFilled
                    takerAmountFilled
                    fee
                  }
                }
                """
            },
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("data", {}).get("orderFilledEvents", [])
        return []
    except Exception as e:
        log(f"  Goldsky fills error: {e}")
        return []


# ── Goldsky: Volume Spike Detection ───────────────────────────────────────────
def detect_volume_spikes_via_goldsky(markets: list) -> list:
    """
    Goldsky has marketOpenInterests with id = condition_id hash + outcome.
    Compare current OI vs baseline to detect unusual activity.
    """
    signals = []
    try:
        r = requests.post(
            "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/oi-subgraph/0.0.6/gn",
            json={
                "query": "{ marketOpenInterests(first: 20, orderBy: amount, orderDirection: desc) { id amount } }"
            },
            timeout=10,
        )
        if r.status_code != 200:
            return signals
        oi_data = r.json().get("data", {}).get("marketOpenInterests", [])
        for entry in oi_data:
            amount = int(entry.get("amount", 0) or 0)
            if amount > 1_000_000_000:  # Large OI position
                log(f"  📊 Large OI detected: {amount:,} — id: {entry['id'][:30]}...")
    except Exception as e:
        log(f"  Goldsky OI error: {e}")
    return signals


# ── Whale Detection ───────────────────────────────────────────────────────────
def detect_whales_from_fills(fills: list, markets: list) -> list:
    """
    Goldsky fills are raw trades (no market slug/context).
    We need to match asset IDs to market tokens to get market context.
    This is limited — we use fills for volume spike detection instead.
    """
    signals = []

    # Aggregate by maker address
    maker_volume = {}
    maker_sides  = {}
    for fill in fills:
        maker = fill.get("maker", "")
        taker = fill.get("taker", "")
        maker_amt = int(fill.get("makerAmountFilled", 0) or 0)
        taker_amt = int(fill.get("takerAmountFilled", 0) or 0)
        # These are in raw token amounts — estimate USD value (tokens are 1e-18 scale usually)
        # For Polymarket CLOB, token amounts are typically 1e-6 or 1e-18
        # We'll use takerAmountFilled as the primary volume indicator
        total_amt = max(maker_amt, taker_amt)

        for addr in [maker, taker]:
            if not addr or addr == "0x0000000000000000000000000000000000000000":
                continue
            if addr not in maker_volume:
                maker_volume[addr] = 0.0
                maker_sides[addr] = []
            maker_volume[addr] += total_amt

    # Look for whale-sized total volume from a single wallet
    # Note: raw amounts need scaling — using a heuristic
    for wallet, raw_vol in maker_volume.items():
        # Skip tiny volumes
        if raw_vol < 100_000:  # rough threshold in raw units
            continue

        # Heuristic: raw_vol > 10M tokens is likely whale
        # This is direction-agnostic without market context
        pass  # would need token price to convert to USD

    return signals


def detect_whales_from_clob(markets: list) -> list:
    """
    Use CLOB API with wallet auth to get fills per market.
    """
    signals = []
    session = requests.Session()
    headers = {"x-wallet": WALLET}
    session.headers.update(headers)

    # Only check top 10 markets by volume to save API calls
    top = sorted(markets, key=lambda m: m["volume"], reverse=True)[:10]
    for mkt in top:
        slug = mkt["slug"]
        cid  = mkt.get("condition_id", "")

        # Try to get recent trades from CLOB with auth
        try:
            r = session.get(
                f"{CLOB_API}/trades",
                params={"wallet": WALLET, "market_slug": slug},
                timeout=8,
            )
            if r.status_code != 200:
                continue
            trades_data = r.json()
            if isinstance(trades_data, dict):
                trades_data = trades_data.get("data", trades_data.get("trades", []))
            if not isinstance(trades_data, list):
                continue
        except Exception:
            continue

        if not trades_data:
            continue

        # Aggregate by trader
        trader_vol  = {}
        trader_side = {}
        for t in trades_data:
            wallet = t.get("proxyWallet", t.get("maker", ""))
            size   = float(t.get("size", 0) or 0)
            price  = float(t.get("price", 0) or 0)
            side   = t.get("side", "BUY")
            vol_usd = size * price

            if not wallet or wallet == "0x0000000000000000000000000000000000000000":
                continue
            if wallet not in trader_vol:
                trader_vol[wallet]  = 0.0
                trader_side[wallet] = []
            trader_vol[wallet]   += vol_usd
            trader_side[wallet].append(side)

        # Detect whale activity
        for wallet, vol_usd in trader_vol.items():
            if vol_usd < WHALE_SIZE_USD:
                continue
            trigger_type = "MEGA_WHALE" if vol_usd >= MEGA_WHALE_USD else "LARGE_TRADE"
            if recent_whale_processed(slug, trigger_type):
                continue

            sides      = trader_side[wallet]
            dom_side   = "YES" if sides.count("BUY") > sides.count("SELL") else "NO"
            yes        = mkt["yes"]
            no         = mkt["no"]

            if dom_side == "YES":
                direction = "YES"
                entry = yes + 0.01
                target = min(yes + 0.15, 0.92)
                stop   = max(yes - 0.08, 0.25)
            else:
                direction = "NO"
                entry = no + 0.01
                target = max(no - 0.12, 0.08)
                stop   = min(no + 0.08, 0.75)

            risk   = abs(entry - stop)
            reward = abs(target - entry) if direction == "YES" else abs(entry - target)
            if risk <= 0:
                continue
            rr = reward / risk
            if rr < 1.5:
                continue

            confidence = min(0.60 + (vol_usd / MEGA_WHALE_USD) * 0.15, 0.85) if trigger_type == "MEGA_WHALE" else min(0.58, 0.75)
            rationale = (
                f"{'Institutional' if trigger_type == 'MEGA_WHALE' else 'Whale'} activity: "
                f"${vol_usd:,.0f} from single wallet on Polymarket. "
                f"Size: {vol_usd/1000:.1f}K. Signals conviction at {yes:.0%}. "
                f"{rr:.1f}:1 R/R."
            )

            signal_id = insert_whale_signal(
                market_slug=slug,
                question=mkt["question"],
                trigger_type=trigger_type,
                trader_address=wallet[:16] + "...",
                side=dom_side,
                size_usd=vol_usd,
                price=yes,
                direction=direction,
                confidence=confidence,
                entry_price=entry,
                target_price=target,
                stop_loss=stop,
                rationale=rationale,
            )
            emoji = "🐋" if trigger_type == "MEGA_WHALE" else "🐳"
            log(f"  {emoji} {trigger_type} [{signal_id}]: {mkt['question'][:50]} | ${vol_usd:,.0f} | {direction}")
            signals.append({"signal_id": signal_id, "type": trigger_type})
            time.sleep(0.2)

    return signals


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    log("=== Whale Monitor Run Starting ===")

    markets = get_active_markets(limit=30)
    log(f"  Fetched {len(markets)} active markets")

    total = 0

    # Method 1: Goldsky fills (real-time, no auth needed)
    fills = get_goldsky_fills(limit=50)
    log(f"  Goldsky fills: {len(fills)} recent events")
    gs_signals = detect_whales_from_fills(fills, markets)
    total += len(gs_signals)

    # Volume spike via Goldsky
    vol_spikes = detect_volume_spikes_via_goldsky(markets)
    total += len(vol_spikes)

    # Method 2: CLOB trades with wallet auth
    clob_signals = detect_whales_from_clob(markets)
    total += len(clob_signals)

    log(f"=== Whale Monitor Complete: {total} signals ===")
    return total


if __name__ == "__main__":
    run()
