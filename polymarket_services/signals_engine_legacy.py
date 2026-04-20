#!/usr/bin/env python3
"""
signals_engine_legacy.py — Core Polymarket momentum/contrarian/arbitrage signals.
=================================================================================
Uses pmxt (system Python 3.12) for market data:
  - fetch_markets(params) → UnifiedMarket with volume, yes/no outcomes, category

Signal types:
  1. MOMENTUM — extreme price + high volume
  2. CONTRARIAN — Polymarket odds diverge from historical baselines
  3. ARBITRAGE  — YES/NO spread exceeds 2.5% (theoretical edge)
"""
import sys, json, logging, time
from datetime import datetime
sys.path.insert(0, '/opt/polymarket')
from signals_db import (
    init_db, insert_signal, insert_contrarian, insert_arbitrage, mark_expired
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

PMXT_BIN = "/usr/bin/python3"
REFERRAL  = "Predict221"

# Historical baselines for contrarian detection
BASELINES = {
    "bitcoin": 0.55, "btc": 0.55, "crypto": 0.52,
    "trump": 0.52, "biden": 0.40, "harris": 0.42,
    "fed": 0.40, "rate cut": 0.38, "rate hike": 0.30,
    "recession": 0.32, "inflation": 0.45, "china": 0.38,
    "taiwan": 0.32, "russia": 0.40, "ukraine": 0.45,
    "etf": 0.40, "default": 0.15, "shutdown": 0.40,
    "iran": 0.35, "israel": 0.40, "nato": 0.38,
}

SKIP_SLUGS = ["gta-vi", "before-gta", "released-before-gta", "grand-theft-auto"]


PMXT_MARKETS = "/usr/bin/python3 /tmp/pmxt_markets.py 200"


def get_markets_pmxt() -> list:
    """Fetch markets via /tmp/pmxt_markets.py helper."""
    try:
        r = __import__("subprocess").run(
            PMXT_MARKETS, shell=True,
            capture_output=True, text=True, timeout=25,
        )
        if r.returncode != 0:
            logger.error(f"pmxt error: {r.stderr.strip()}")
            return []
        return json.loads(r.stdout.strip())
    except Exception as e:
        logger.error(f"pmxt exception: {e}")
        return []


def detect_momentum(markets: list) -> list:
    signals = []
    for m in markets:
        slug  = m["slug"]
        title = m["title"]
        yes   = m["yes"]
        vol   = m["volume"]

        if vol < 50000:
            continue

        # MOMENTUM: extreme price + volume
        if yes > 0.70:
            direction = "YES"
            entry  = yes + 0.01
            target = min(yes + 0.12, 0.95)
            stop   = max(yes - 0.08, 0.25)
            conf   = min(0.70 + min(vol / 1_000_000, 1.0) * 0.15, 0.88)
            rat    = (f"Momentum: YES at {entry:.0%} with ${vol:,.0f} volume. "
                      f"Overbought extreme. Target {target:.0%}.")
            signals.append({
                "type": "momentum", "slug": slug, "title": title,
                "side": direction, "confidence": round(conf, 3),
                "current_price": yes, "entry_price": round(entry, 4),
                "target_price": round(target, 4), "stop_loss": round(max(stop, 0.01), 4),
                "rationale": rat, "volume_usd": vol,
                "market_url": f"https://polymarket.com/?r={REFERRAL}&slug={slug}",
            })
        elif yes < 0.30:
            direction = "NO"
            entry  = m["no"] + 0.01
            target = min(m["no"] + 0.12, 0.95)
            stop   = max(m["no"] - 0.08, 0.05)
            conf   = min(0.70 + min(vol / 1_000_000, 1.0) * 0.15, 0.88)
            rat    = (f"Momentum: NO signal at {m['no']:.0%} with ${vol:,.0f} volume. "
                      f"Oversold extreme. Target {target:.0%}.")
            signals.append({
                "type": "momentum", "slug": slug, "title": title,
                "side": direction, "confidence": round(conf, 3),
                "current_price": m["no"], "entry_price": round(entry, 4),
                "target_price": round(target, 4), "stop_loss": round(max(stop, 0.01), 4),
                "rationale": rat, "volume_usd": vol,
                "market_url": f"https://polymarket.com/?r={REFERRAL}&slug={slug}",
            })

        # MEAN REVERSION: consolidating in 35-65% range with high volume
        elif 0.35 <= yes <= 0.65 and vol > 30000:
            bullish = any(k in title.lower() for k in ["bitcoin", "btc", " eth ", "trump", "pass", "approve", "hike", "yes"])
            bearish = any(k in title.lower() for k in ["crash", "default", "fail", "reject", "cut", "recession"])
            bias    = "YES" if bullish or (not bearish and yes > 0.50) else "NO"
            entry   = yes if bias == "YES" else m["no"]
            target  = min(entry + 0.20, 0.90)
            stop    = entry - 0.10
            conf    = min(0.60 + min(vol / 200_000, 1.0) * 0.15, 0.80)
            rat     = (f"Mean reversion: consolidating at {yes:.0%} with ${vol:,.0f}. "
                       f"Bias {bias}. Entry ~{entry:.0%}.")
            signals.append({
                "type": "mean_reversion", "slug": slug, "title": title,
                "side": bias, "confidence": round(conf, 3),
                "current_price": yes, "entry_price": round(entry + 0.01, 4),
                "target_price": round(target, 4), "stop_loss": round(max(stop, 0.02), 4),
                "rationale": rat, "volume_usd": vol,
                "market_url": f"https://polymarket.com/?r={REFERRAL}&slug={slug}",
            })
    return signals


def detect_contrarian(markets: list) -> list:
    signals = []
    for m in markets:
        slug   = m["slug"]
        title  = m["title"]
        yes    = m["yes"]
        volume = m["volume"]
        if volume < 10000:
            continue
        if yes < 0.05 or yes > 0.95:
            continue
        combined = (slug + " " + title).lower()
        matched  = None
        for kw, baseline in BASELINES.items():
            if kw in combined:
                if matched is None or len(kw) > len(matched[0]):
                    matched = (kw, baseline)
        if not matched:
            continue
        divergence = yes - matched[1]
        if abs(divergence) < 0.12:
            continue
        direction = "NO" if divergence > 0 else "YES"
        conf = min(0.58 + abs(divergence) * 0.7, 0.82)
        rat  = (f"Contrarian: Polymarket at {yes:.0%} vs ~{matched[1]:.0%} baseline "
                f"for '{matched[0]}'. Divergence of {abs(divergence):.0%}.")
        signals.append({
            "type": "contrarian", "slug": slug, "title": title,
            "polymarket_odds": yes, "external_odds": matched[1],
            "direction": direction, "confidence": round(conf, 3),
            "rationale": rat,
            "market_url": f"https://polymarket.com/?r={REFERRAL}&slug={slug}",
        })
    return signals


def detect_arbitrage(markets: list) -> list:
    """Flag markets where YES + NO price > 1.025 (theoretical edge)."""
    opps = []
    for m in markets:
        slug   = m["slug"]
        title  = m["title"]
        yes    = m["yes"]
        no     = m["no"]
        volume = m["volume"]
        if volume < 5000:
            continue
        spread = yes + no
        if spread > 1.025:
            net = 1.0 - spread - (spread * 0.02 * 2)
            if net > 0.005:
                rat = (f"Spread arb: YES({yes:.4f}) + NO({no:.4f}) = {spread:.4f}. "
                       f"Net edge after fees: {net:.4f}.")
                opps.append({
                    "slug": slug, "title": title,
                    "yes_price": yes, "no_price": no,
                    "spread": spread, "net_edge": round(net, 4),
                    "volume_usd": volume, "rationale": rat,
                })
    return opps


def run():
    logger.info("Starting legacy signal generation...")
    init_db()
    mark_expired()

    markets = get_markets_pmxt()
    logger.info(f"Fetched {len(markets)} markets via pmxt")

    trade_sig  = detect_momentum(markets)
    contrarian = detect_contrarian(markets)
    arbitrage  = detect_arbitrage(markets)

    stored = 0
    for s in trade_sig:
        try:
            insert_signal(
                signal_type=s["type"], market_slug=s["slug"], question=s["title"],
                side=s["side"], confidence=s["confidence"],
                current_price=s["current_price"], entry_price=s["entry_price"],
                target_price=s["target_price"], stop_loss=s["stop_loss"],
                rationale=s["rationale"], market_url=s["market_url"], expires_hours=48,
            )
            stored += 1
        except Exception as e:
            logger.error(f"Store error: {e}")

    for s in contrarian:
        try:
            insert_contrarian(
                market_slug=s["slug"], question=s["title"],
                polymarket_odds=s["polymarket_odds"], external_odds=s["external_odds"],
                direction=s["direction"], rationale=s["rationale"],
            )
            stored += 1
        except Exception as e:
            logger.error(f"Contrarian error: {e}")

    for a in arbitrage:
        try:
            insert_arbitrage(
                market_slug=a["slug"], question=a["title"],
                polymarket_price=a["yes_price"], kalshi_price=1.0,
                spread=a["spread"], direction=a["direction"],
                volume_usd=a["volume_usd"], rationale=a["rationale"], expires_hours=4,
            )
            stored += 1
        except Exception as e:
            logger.error(f"Arb error: {e}")

    logger.info(f"Stored {stored} legacy signals "
                f"({len(trade_sig)} trade, {len(contrarian)} contrarian, {len(arbitrage)} arb)")
    return {"trade": len(trade_sig), "contrarian": len(contrarian),
            "arbitrage": len(arbitrage), "stored": stored}


if __name__ == "__main__":
    print(run())
