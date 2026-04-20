#!/usr/bin/env python3
"""
orderflow_monitor.py — CLOB orderbook analysis using pmxt helpers.
================================================================
Uses /tmp/pmxt_orderbook.py and /tmp/pmxt_markets.py for real-time order book.

Detects:
  - SPREAD_WIDENING:    bid-ask spread > 4% = informed flow or uncertainty
  - BOOK_IMBALANCE:     >70% of book depth on one side = directional smart money
  - LIQUIDITY_VACUUM:   one side nearly empty = easy price move
"""
import json, time, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH          = "/var/lib/polymarket/signals.db"
LOG_DIR          = Path("/var/log/polymarket")
LOG_DIR.mkdir(parents=True, exist_ok=True)
SPREAD_ALERT         = 0.005   # 0.5%+ (Polymarket AMM spreads are tight; catch outliers)
BOOK_IMBALANCE_THRESH = 0.70   # One side ≥70% of book depth
LIQUIDITY_VACUUM_PCT  = 0.04   # Thin side <4% of total
MIN_LIQUIDITY_USD     = 2000   # Minimum total book depth ($2K — Polymarket is liquid enough)
DIVERGENCE_ALERT      = 0.03   # 3%+ implied-vs-API divergence
MAX_MARKETS           = 10
MAX_RUNTIME_SEC       = 60
PMXT_MARKETS   = "/usr/bin/python3 /tmp/pmxt_markets.py 100"
PMXT_BOOK       = "/usr/bin/python3 /tmp/pmxt_orderbook.py"

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


def insert_signal(
    market_slug, question, signal_type,
    spread_pct, bid_depth_pct, ask_depth_pct,
    direction, confidence,
    entry_price, target_price, stop_loss, rationale,
) -> int:
    conn = get_db()
    expires_at = datetime.now() + timedelta(hours=48)
    cur = conn.execute("""
        INSERT INTO orderflow_signals (
            market_slug, question, signal_type, spread, imbalance_pct,
            direction, confidence, entry_price, target_price, stop_loss,
            rationale, expires_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, [market_slug, question, signal_type, spread_pct, max(bid_depth_pct, ask_depth_pct),
          direction, confidence, entry_price, target_price, stop_loss, rationale, expires_at])
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def recent_signal(market_slug: str, signal_type: str, lookback_hours: int = 6) -> bool:
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM orderflow_signals
        WHERE market_slug=? AND signal_type=?
          AND datetime(generated_at) > datetime('now', ?)
        LIMIT 1
    """, [market_slug, signal_type, f"-{lookback_hours} hours"]).fetchone()
    conn.close()
    return row is not None


# ── pmxt data fetchers ─────────────────────────────────────────────────────────
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


def get_orderbook(outcome_id: str) -> dict | None:
    """Fetch order book for an outcome via /tmp/pmxt_orderbook.py."""
    try:
        r = __import__("subprocess").run(
            f"{PMXT_BOOK} {outcome_id}",
            shell=True, capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout.strip())
    except Exception:
        return None


# ── Analysis ────────────────────────────────────────────────────────────────────
def analyze_book(m: dict, book: dict) -> list:
    """
    Analyze order book for a single market.
    book = {"bids": [[price, size], ...], "asks": [[price, size], ...]}
    Returns list of signal dicts.
    """
    signals = []
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    if not bids or not asks:
        return signals

    best_bid = bids[0][0] if bids else 0
    best_ask = asks[0][0] if asks else 1.0
    if best_bid <= 0 or best_ask <= 0:
        return signals

    mid_price  = (best_bid + best_ask) / 2
    spread_pct = (best_ask - best_bid) / mid_price

    bid_depth_usd = sum(b[0] * b[1] for b in bids[:10])
    ask_depth_usd = sum(a[0] * a[1] for a in asks[:10])
    total_depth   = bid_depth_usd + ask_depth_usd

    if total_depth < MIN_LIQUIDITY_USD:
        return signals

    bid_pct = bid_depth_usd / total_depth
    ask_pct = ask_depth_usd / total_depth
    slug    = m["slug"]
    yes_p   = m["yes"]

    # ── SPREAD_WIDENING ─────────────────────────────────────────────────────
    if spread_pct >= SPREAD_ALERT and not recent_signal(slug, "SPREAD_WIDENING"):
        direction = "YES" if best_bid > yes_p else "NO"
        conf = min(0.65 + spread_pct * 2, 0.80)
        entry  = yes_p + 0.01 if direction == "YES" else (1 - yes_p) + 0.01
        target = min(yes_p + 0.15, 0.92) if direction == "YES" else max((1 - yes_p) - 0.12, 0.08)
        stop   = max(yes_p - 0.08, 0.25) if direction == "YES" else min((1 - yes_p) + 0.08, 0.75)
        rationale = (
            f"Wide spread: {spread_pct:.1%} (bid={best_bid:.3f} ask={best_ask:.3f}). "
            f"Book mid={mid_price:.0%} vs market {yes_p:.0%}. "
            f"Wide spreads signal uncertainty or smart-money positioning."
        )
        signals.append({
            "type": "SPREAD_WIDENING", "spread_pct": spread_pct,
            "bid_pct": bid_pct, "ask_pct": ask_pct,
            "direction": direction, "conf": conf,
            "entry": entry, "target": target, "stop": stop,
            "rationale": rationale,
        })

    # ── BOOK_IMBALANCE ──────────────────────────────────────────────────────
    dominant_pct = max(bid_pct, ask_pct)
    if dominant_pct >= BOOK_IMBALANCE_THRESH and not recent_signal(slug, "BOOK_IMBALANCE"):
        direction = "YES" if bid_pct > ask_pct else "NO"
        conf = min(0.62 + (dominant_pct - BOOK_IMBALANCE_THRESH) * 0.8, 0.82)
        entry  = yes_p + 0.01 if direction == "YES" else (1 - yes_p) + 0.01
        target = min(yes_p + 0.15, 0.92) if direction == "YES" else max((1 - yes_p) - 0.12, 0.08)
        stop   = max(yes_p - 0.08, 0.25) if direction == "YES" else min((1 - yes_p) + 0.08, 0.75)
        emoji  = "📈" if direction == "YES" else "📉"
        rationale = (
            f"Book imbalance {dominant_pct:.0%}: "
            f"BUY=${bid_depth_usd:,.0f} vs SELL=${ask_depth_usd:,.0f}. "
            f"{emoji} Smart money {'accumulating YES' if direction=='YES' else 'positioning NO'}."
        )
        signals.append({
            "type": "BOOK_IMBALANCE",
            "spread_pct": spread_pct,
            "bid_pct": bid_pct, "ask_pct": ask_pct,
            "direction": direction, "conf": conf,
            "entry": entry, "target": target, "stop": stop,
            "rationale": rationale,
        })

    # ── DIVERGENCE (book implied vs market price) ───────────────────────────
    implied_prob = 1 - best_bid  # YES price implied by best bid
    divergence   = abs(implied_prob - yes_p)
    if divergence >= DIVERGENCE_ALERT and not recent_signal(slug, "DIVERGENCE"):
        direction = "YES" if implied_prob > yes_p else "NO"
        conf = min(0.60 + (divergence / DIVERGENCE_ALERT) * 0.10, 0.78)
        entry  = yes_p + 0.01 if direction == "YES" else (1 - yes_p) + 0.01
        target = round(min(yes_p * 1.25, 0.92), 2) if direction == "YES" \
                 else round(max((1 - yes_p) * 0.75, 0.08), 2)
        stop   = round(max(yes_p * 0.70, 0.20), 2) if direction == "YES" \
                 else round(min((1 - yes_p) * 1.30, 0.80), 2)
        rationale = (
            f"Book vs market divergence: implied {implied_prob:.0%} vs API {yes_p:.0%} "
            f"(diff={divergence:.1%}). Smart money may be moving price ahead of consensus."
        )
        signals.append({
            "type": "DIVERGENCE",
            "spread_pct": spread_pct,
            "bid_pct": bid_pct, "ask_pct": ask_pct,
            "direction": direction, "conf": conf,
            "entry": entry, "target": target, "stop": stop,
            "rationale": rationale,
        })

    # ── LIQUIDITY_VACUUM ────────────────────────────────────────────────────
    if (bid_depth_usd < total_depth * LIQUIDITY_VACUUM_PCT or ask_depth_usd < total_depth * LIQUIDITY_VACUUM_PCT) \
       and not recent_signal(slug, "LIQUIDITY_VACUUM"):
        thin_side = "BUY" if bid_depth_usd < ask_depth_usd else "SELL"
        direction = "YES" if thin_side == "BUY" else "NO"
        conf = 0.60
        entry  = yes_p + 0.01 if direction == "YES" else (1 - yes_p) + 0.01
        target = min(yes_p + 0.20, 0.95) if direction == "YES" else max((1 - yes_p) - 0.15, 0.05)
        stop   = max(yes_p - 0.10, 0.20) if direction == "YES" else min((1 - yes_p) + 0.10, 0.80)
        rationale = (
            f"Liquidity vacuum on {thin_side}: only ${min(bid_depth_usd, ask_depth_usd):,.0f} "
            f"vs ${max(bid_depth_usd, ask_depth_usd):,.0f} opposite. "
            f"Price can move fast through thin book."
        )
        signals.append({
            "type": "LIQUIDITY_VACUUM",
            "spread_pct": spread_pct,
            "bid_pct": bid_pct, "ask_pct": ask_pct,
            "direction": direction, "conf": conf,
            "entry": entry, "target": target, "stop": stop,
            "rationale": rationale,
        })

    return signals


# ── Main ───────────────────────────────────────────────────────────────────────
def run():
    log("=== Orderflow Monitor Run Starting ===")
    start = time.time()
    total = 0

    markets = get_target_markets()
    log(f"  Got {len(markets)} target markets")

    for m in markets[:MAX_MARKETS]:
        if time.time() - start > MAX_RUNTIME_SEC:
            log("  Runtime budget exceeded")
            break

        oid = m.get("outcome_id")
        if not oid:
            continue

        book = get_orderbook(oid)
        if not book:
            continue

        sigs = analyze_book(m, book)
        for sig in sigs:
            sid = insert_signal(
                market_slug=m["slug"],
                question=m["title"],
                signal_type=sig["type"],
                spread_pct=sig["spread_pct"],
                bid_depth_pct=sig["bid_pct"],
                ask_depth_pct=sig["ask_pct"],
                direction=sig["direction"],
                confidence=sig["conf"],
                entry_price=sig["entry"],
                target_price=sig["target"],
                stop_loss=sig["stop"],
                rationale=sig["rationale"],
            )
            emoji = "📊" if sig["type"] == "BOOK_IMBALANCE" else \
                    "⚠️"  if sig["type"] == "SPREAD_WIDENING" else "🎯"
            log(f"  {emoji} {sig['type']} [{sid}]: {m['title'][:50]} "
                f"| {sig['direction']} conf={sig['conf']:.0%}")
            total += 1
            time.sleep(0.3)

    log(f"=== Orderflow Monitor Complete: {total} signals in {time.time()-start:.1f}s ===")
    return total


if __name__ == "__main__":
    run()
