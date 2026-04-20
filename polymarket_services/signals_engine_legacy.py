#!/usr/bin/env python3
"""
signals_engine_legacy.py — Core Polymarket momentum/contrarian/arbitrage signals.
=================================================================================
Generates the 3 original signal types:
  1. MOMENTUM — extreme price + high volume
  2. CONTRARIAN — Polymarket odds diverge from external baselines
  3. ARBITRAGE  — YES/NO spread anomalies (risk-free)
"""
import sys, json, logging, time
from datetime import datetime
sys.path.insert(0, '/opt/polymarket')
from signals_db import (
    init_db, insert_signal, insert_contrarian, insert_arbitrage,
    mark_expired
)
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
REFERRAL  = "Predict221"


def get_markets(limit: int = 200) -> list:
    try:
        resp = requests.get(f"{GAMMA_API}/markets", params={"limit": limit, "closed": "false"}, timeout=15)
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        logger.error(f"Market fetch error: {e}")
        return []


def parse_price(m):
    prices = m.get("outcomePrices", [])
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except:
            prices = []
    if isinstance(prices, list):
        return float(prices[0]) if len(prices) > 0 else 0.50, float(prices[1]) if len(prices) > 1 else 0.50
    return 0.50, 0.50


def detect_signals(markets: list) -> list:
    signals = []
    for m in markets:
        try:
            slug = m.get("slug", "")
            question = m.get("question", "")
            volume = float(m.get("volume", 0) or 0)
            liquidity = float(m.get("liquidity", 0) or 0)
            if volume < 5000 or liquidity < 1000:
                continue
            yes, no = parse_price(m)
            if yes <= 0.01 or yes >= 0.99:
                continue
            if len(question) < 10:
                continue

            # MOMENTUM
            if (yes > 0.70 or yes < 0.30) and volume > 50000:
                direction = "YES" if yes > 0.70 else "NO"
                entry = yes + 0.01 if direction == "YES" else no + 0.01
                target = min(yes + 0.12, 0.95) if direction == "YES" else min(no + 0.12, 0.95)
                stop = yes - 0.08 if direction == "YES" else no - 0.08
                conf = min(0.70 + min(volume / 1_000_000, 1.0) * 0.15, 0.88)
                rationale = (
                    f"Momentum: {direction} at {entry:.0%} with ${volume:,.0f} volume. "
                    f"{'Overbought' if yes > 0.70 else 'Oversold'} extreme. "
                    f"Entry ~{entry:.0%}, target {target:.0%}, stop {stop:.0%}."
                )
                signals.append({
                    "type": "momentum", "slug": slug, "question": question,
                    "side": direction, "confidence": round(conf, 3),
                    "current_price": yes if direction == "YES" else no,
                    "entry_price": round(entry + 0.01, 4),
                    "target_price": round(target, 4),
                    "stop_loss": round(max(stop, 0.01), 4),
                    "rationale": rationale, "volume_usd": volume,
                    "market_url": f"https://polymarket.com/?r={REFERRAL}&slug={slug}",
                })

            # MEAN REVERSION
            elif 0.35 <= yes <= 0.65 and volume > 30000:
                q_lower = question.lower()
                bullish = any(k in q_lower for k in ["bitcoin", "btc", " eth ", "solana", "trump", "yes", "pass", "approve", "hike"])
                bearish = any(k in q_lower for k in ["crash", "default", "fail", "reject", "cut", "recession", "decline"])
                bias = "YES" if bullish or (not bearish and yes > 0.50) else "NO"
                entry = yes if bias == "YES" else no
                target = min(entry + 0.20, 0.90)
                stop = entry - 0.10
                conf = min(0.60 + min(volume / 200_000, 1.0) * 0.15, 0.80)
                rationale = (
                    f"Mean reversion: consolidating at {yes:.0%} with ${volume:,.0f} volume. "
                    f"Bias toward {bias}. Entry ~{entry:.0%}, target {target:.0%}, stop {stop:.0%}."
                )
                signals.append({
                    "type": "mean_reversion", "slug": slug, "question": question,
                    "side": bias, "confidence": round(conf, 3),
                    "current_price": yes if bias == "YES" else no,
                    "entry_price": round(entry + 0.01, 4),
                    "target_price": round(target, 4),
                    "stop_loss": round(max(stop, 0.02), 4),
                    "rationale": rationale, "volume_usd": volume,
                    "market_url": f"https://polymarket.com/?r={REFERRAL}&slug={slug}",
                })
        except Exception:
            continue
    return signals


def detect_contrarian(markets: list) -> list:
    BASELINES = {
        "bitcoin": 0.55, "btc": 0.55, "crypto": 0.52,
        "trump": 0.52, "biden": 0.40, "fed": 0.40,
        "rate cut": 0.38, "rate hike": 0.30, "recession": 0.32,
        "inflation": 0.45, "china": 0.38, "taiwan": 0.32,
        "russia": 0.40, "ukraine": 0.45, "etf": 0.40,
        "default": 0.15, "shutdown": 0.40,
    }
    signals = []
    for m in markets:
        try:
            slug = m.get("slug", "")
            question = m.get("question", "")
            volume = float(m.get("volume", 0) or 0)
            if volume < 10000:
                continue
            yes, _ = parse_price(m)
            if yes < 0.05 or yes > 0.95:
                continue
            combined = (slug + " " + question).lower()
            matched = None
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
            rationale = (
                f"Contrarian: Polymarket at {yes:.0%} vs ~{matched[1]:.0%} baseline for '{matched[0]}'. "
                f"Divergence of {abs(divergence):.0%}."
            )
            signals.append({
                "type": "contrarian", "slug": slug, "question": question,
                "polymarket_odds": yes, "external_odds": matched[1],
                "direction": direction, "confidence": round(conf, 3),
                "rationale": rationale,
                "market_url": f"https://polymarket.com/?r={REFERRAL}&slug={slug}",
            })
        except Exception:
            continue
    return signals


def detect_arbitrage(markets: list) -> list:
    opps = []
    for m in markets:
        try:
            slug = m.get("slug", "")
            question = m.get("question", "")
            volume = float(m.get("volume", 0) or 0)
            if volume < 5000:
                continue
            yes, no = parse_price(m)
            if yes <= 0 or no <= 0:
                continue
            spread = yes + no
            if spread > 1.025:
                net = (1.0 - spread) - (spread * 0.02 * 2)
                if net > 0.005:
                    opps.append({
                        "slug": slug, "question": question,
                        "direction": "BUY_YES_AND_NO",
                        "yes_price": yes, "no_price": no,
                        "spread": spread, "net_edge": round(net, 4),
                        "volume_usd": volume,
                        "rationale": f"Spread arb: YES({yes:.4f}) + NO({no:.4f}) = {spread:.4f}. Net edge: {net:.4f}.",
                    })
        except Exception:
            continue
    return opps


def run():
    logger.info("Starting legacy signal generation...")
    init_db()
    mark_expired()
    markets = get_markets(limit=200)
    logger.info(f"Fetched {len(markets)} markets")

    trade_sig   = detect_signals(markets)
    contrarian  = detect_contrarian(markets)
    arbitrage   = detect_arbitrage(markets)

    stored = 0
    for s in trade_sig:
        try:
            insert_signal(
                signal_type=s["type"], market_slug=s["slug"], question=s["question"],
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
                market_slug=s["slug"], question=s["question"],
                polymarket_odds=s["polymarket_odds"], external_odds=s["external_odds"],
                direction=s["direction"], rationale=s["rationale"],
            )
            stored += 1
        except Exception as e:
            logger.error(f"Contrarian error: {e}")

    for a in arbitrage:
        try:
            insert_arbitrage(
                market_slug=a["slug"], question=a["question"],
                polymarket_price=a["yes_price"], kalshi_price=1.0,
                spread=a["spread"], direction=a["direction"],
                volume_usd=a["volume_usd"], rationale=a["rationale"], expires_hours=4,
            )
            stored += 1
        except Exception as e:
            logger.error(f"Arb error: {e}")

    logger.info(f"Stored {stored} legacy signals ({len(trade_sig)} trade, {len(contrarian)} contrarian, {len(arbitrage)} arb)")
    return {"trade": len(trade_sig), "contrarian": len(contrarian), "arbitrage": len(arbitrage), "stored": stored}


if __name__ == "__main__":
    print(run())
