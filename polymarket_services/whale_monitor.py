#!/usr/bin/env python3
"""
whale_monitor.py — Smart-money / whale detection using pmxt helpers.
======================================================================
Uses /tmp/pmxt_trades.py and /tmp/pmxt_markets.py for real Polymarket data.

Detects:
  - LARGE_TRADE:     $5K+ single trade from trade stream
  - MEGA_WHALE:      $25K+ single institutional trade
  - VOLUME_SPIKE:     24hr volume > 3x 7-day daily average
  - PRICE_MOMENTUM:   >5% price move in recent trades
"""
import json, time, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH          = "/var/lib/polymarket/signals.db"
LOG_DIR          = Path("/var/log/polymarket")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE         = LOG_DIR / "whale_monitor.log"
MEGA_WHALE_USD   = 5000     # $5K+ institutional
VOL_SPIKE_MULT   = 3.0
PRICE_MOVE_PCT   = 0.03     # 3%+ move (lowered from 5%)
MAX_MARKETS      = 10
MAX_RUNTIME_SEC  = 50
MIN_TRADE_USD    = 200       # Minimum trade value to consider ($200)
MIN_CONF         = 0.52      # Minimum confidence to store a signal
MIN_RR           = 1.0       # Minimum reward/risk ratio
PMXT_MARKETS     = "/usr/bin/python3 /tmp/pmxt_markets.py 200"
PMXT_TRADES      = "/usr/bin/python3 /tmp/pmxt_trades.py"

SKIP_SLUGS = ["gta-vi", "before-gta", "released-before-gta", "grand-theft-auto"]


# ── Logging ────────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.write_text(LOG_FILE.read_text() + "\n" + line if LOG_FILE.exists() else line + "\n")
    except Exception:
        pass


# ── DB ─────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def insert_whale_signal(
    market_slug, question, trigger_type, trader_address, side,
    size_usd, price, direction, confidence,
    entry_price, target_price, stop_loss, rationale,
) -> int:
    conn = get_db()
    expires_at = datetime.now() + timedelta(hours=72)
    cur = conn.execute("""
        INSERT INTO whale_signals (
            market_slug, question, trigger_type, trader_address, side,
            size_usd, price, direction, confidence,
            entry_price, target_price, stop_loss, rationale, expires_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [market_slug, question, trigger_type, trader_address, side,
          size_usd, price, direction, confidence,
          entry_price, target_price, stop_loss, rationale, expires_at])
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def recent_whale(market_slug: str, trigger_type: str, lookback_hours: int = 1) -> bool:
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM whale_signals
        WHERE market_slug=? AND trigger_type=?
          AND datetime(generated_at) > datetime('now', ?)
        LIMIT 1
    """, [market_slug, trigger_type, f"-{lookback_hours} hours"]).fetchone()
    conn.close()
    return row is not None


# ── pmxt data fetchers ──────────────────────────────────────────────────────────
def get_target_markets() -> list:
    """Fetch Polymarket markets via /tmp/pmxt_markets.py."""
    try:
        r = __import__("subprocess").run(
            PMXT_MARKETS, shell=True,
            capture_output=True, text=True, timeout=25,
        )
        if r.returncode != 0:
            log(f"  pmxt_markets error: {r.stderr.strip()[:100]}")
            return []
        return json.loads(r.stdout.strip())
    except Exception as e:
        log(f"  pmxt_markets exception: {e}")
        return []


def get_trades(outcome_id: str, limit: int = 200) -> list:
    """Fetch trades for an outcome via /tmp/pmxt_trades.py."""
    try:
        r = __import__("subprocess").run(
            f"{PMXT_TRADES} {outcome_id} {limit}",
            shell=True, capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return []
        return json.loads(r.stdout.strip())
    except Exception:
        return []


# ── Signal generation ───────────────────────────────────────────────────────────
def detect_large_trades(trades: list, yes_price: float, slug: str) -> list:
    signals = []
    checked = flagged = 0
    for t in trades:
        price  = t["p"]
        amount = t["a"]
        side   = t["s"]
        vol_usd = price * amount
        checked += 1
        if vol_usd < MIN_TRADE_USD:
            continue
        flagged += 1
        trigger = "MEGA_WHALE" if vol_usd >= MEGA_WHALE_USD else "LARGE_TRADE"
        if recent_whale(slug, trigger):
            continue
        direction = "YES" if side in ("buy", "BUY", "yes", "YES") else "NO"
        # Confidence for LARGE_TRADE: base 0.60, capped at 0.75
        # MEGA_WHALE: conf 0.60–0.75. LARGE_TRADE: conf 0.52–0.62.
        conf = min(0.60 + (vol_usd / MEGA_WHALE_USD) * 0.15, 0.75) \
            if trigger == "MEGA_WHALE" else min(0.52 + (vol_usd / MIN_TRADE_USD) * 0.02, 0.62)
        entry  = yes_price + 0.01
        # Dynamic target: slightly above current price, max 0.92
        target = round(min(yes_price * 1.25, 0.92), 2)
        stop   = round(max(yes_price * 0.70, 0.20), 2)
        risk   = abs(entry - stop)
        reward = abs(target - entry)
        rr     = reward / risk if risk > 0 else 0
        if rr < MIN_RR:
            continue
        if conf < MIN_CONF:
            continue
        signals.append({
            "type": trigger, "vol": vol_usd,
            "direction": direction, "conf": conf,
            "rr": rr,
        })
    if checked > 0:
        log(f"  DEBUG {slug[:40]}: {checked} trades, {flagged} ≥${MIN_TRADE_USD}, {len(signals)} passed filters")
    return signals


def detect_price_momentum(trades: list, yes_price: float, slug: str) -> list:
    if len(trades) < 5:
        return []
    sorted_trades = sorted(trades, key=lambda x: x["ts"], reverse=True)
    recent = sorted_trades[:10]
    oldest = sorted_trades[-5:]
    avg_recent = sum(t["p"] for t in recent) / len(recent)
    avg_old    = sum(t["p"] for t in oldest) / len(oldest)
    if avg_old <= 0:
        return []
    pct_move = abs(avg_recent - avg_old) / avg_old
    if pct_move < PRICE_MOVE_PCT:
        return []
    direction = "YES" if avg_recent > avg_old else "NO"
    if recent_whale(slug, "PRICE_MOMENTUM"):
        return []
    conf = min(0.62 + pct_move * 2, 0.82)
    entry  = yes_price + 0.01
    target = min(yes_price + 0.15, 0.92) if direction == "YES" else max(yes_price - 0.15, 0.08)
    stop   = max(yes_price - 0.08, 0.25) if direction == "YES" else min(yes_price + 0.08, 0.75)
    rationale = (
        f"Price momentum: {pct_move:.1%} move in recent trades. "
        f"Old avg={avg_old:.3f}, recent avg={avg_recent:.3f}."
    )
    return [{
        "type": "PRICE_MOMENTUM", "pct_move": pct_move,
        "direction": direction, "conf": conf,
        "entry": entry, "target": target, "stop": stop,
        "rationale": rationale,
    }]


def detect_volume_spikes(markets: list) -> list:
    signals = []
    for m in markets:
        vol_24h = m.get("volume_24h", 0)
        vol_7d  = m.get("volume", 0)
        if vol_24h < 10000 or vol_7d < 50000:
            continue
        avg_daily = vol_7d / 7
        if avg_daily <= 0:
            continue
        ratio = vol_24h / avg_daily
        if ratio < VOL_SPIKE_MULT:
            continue
        if recent_whale(m["slug"], "VOLUME_SPIKE"):
            continue
        yes_p = m["yes"]
        direction = "YES" if yes_p < 0.70 else "NO"
        conf = min(0.60 + min(ratio - VOL_SPIKE_MULT, 2.0) * 0.05, 0.80)
        entry  = yes_p + 0.01
        target = min(yes_p + 0.15, 0.92)
        stop   = max(yes_p - 0.08, 0.25)
        rationale = (
            f"Volume spike: ${vol_24h:,.0f} in 24hr ({ratio:.1f}x 7-day avg). "
            f"Market at {yes_p:.0%}."
        )
        signals.append({
            "market": m, "ratio": ratio, "vol_24h": vol_24h,
            "direction": direction, "conf": conf,
            "entry": entry, "target": target, "stop": stop,
            "rationale": rationale,
        })
    return signals


# ── Main ───────────────────────────────────────────────────────────────────────
def run():
    log("=== Whale Monitor Run Starting ===")
    start = time.time()
    markets = get_target_markets()
    log(f"  Target markets: {len(markets)}")
    if not markets:
        log("  No markets found, exiting")
        return 0
    total = 0

    # Volume spikes (no per-market API calls needed)
    for sig in detect_volume_spikes(markets):
        m = sig["market"]
        sid = insert_whale_signal(
            market_slug=m["slug"], question=m["title"],
            trigger_type="VOLUME_SPIKE",
            trader_address="volume_detector",
            side=sig["direction"], size_usd=sig["vol_24h"],
            price=m["yes"], direction=sig["direction"],
            confidence=sig["conf"],
            entry_price=sig["entry"], target_price=sig["target"],
            stop_loss=sig["stop"], rationale=sig["rationale"],
        )
        log(f"  📈 VOLUME_SPIKE [{sid}]: {m['title'][:50]}")
        total += 1

    # Per-market trade analysis
    for m in markets[:MAX_MARKETS]:
        if time.time() - start > MAX_RUNTIME_SEC:
            log("  Runtime budget exceeded")
            break
        slug      = m["slug"]
        title     = m["title"]
        yes_price = m["yes"]
        oid       = m.get("outcome_id")
        if not oid:
            continue
        trades = get_trades(oid, limit=500)
        if not trades:
            continue

        for sig in detect_large_trades(trades, yes_price, slug):
            entry  = yes_price + 0.01
            target = min(yes_price + 0.15, 0.92)
            stop   = max(yes_price - 0.08, 0.25)
            risk   = abs(entry - stop)
            reward = abs(target - entry)
            rr     = reward / risk if risk > 0 else 0
            rationale = (
                f"{'Institutional' if sig['type']=='MEGA_WHALE' else 'Whale'} trade: "
                f"${sig['vol']:,.0f} at {yes_price:.0%}. "
                f"{sig['rr']:.1f}:1 R/R."
            )
            sid = insert_whale_signal(
                market_slug=slug, question=title,
                trigger_type=sig["type"],
                trader_address="pmxt_trade_feed",
                side=sig["direction"], size_usd=sig["vol"],
                price=yes_price, direction=sig["direction"],
                confidence=sig["conf"],
                entry_price=entry, target_price=target,
                stop_loss=stop, rationale=rationale,
            )
            emoji = "🐋" if sig["type"] == "MEGA_WHALE" else "🐳"
            log(f"  {emoji} {sig['type']} [{sid}]: {title[:50]}")
            total += 1
            time.sleep(0.2)

        for sig in detect_price_momentum(trades, yes_price, slug):
            sid = insert_whale_signal(
                market_slug=slug, question=title,
                trigger_type="PRICE_MOMENTUM",
                trader_address="price_momentum_detector",
                side=sig["direction"], size_usd=0,
                price=yes_price, direction=sig["direction"],
                confidence=sig["conf"],
                entry_price=sig["entry"], target_price=sig["target"],
                stop_loss=sig["stop"], rationale=sig["rationale"],
            )
            log(f"  ⚡ PRICE_MOMENTUM [{sid}]: {title[:50]}")
            total += 1
            time.sleep(0.2)

    log(f"=== Whale Monitor Complete: {total} signals in {time.time()-start:.1f}s ===")
    return total


if __name__ == "__main__":
    run()
