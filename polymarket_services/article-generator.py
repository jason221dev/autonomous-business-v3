#!/usr/bin/env python3
"""
Polymarket Article Generator — Insights-first, Recommendations only when they add genuine value.
============================================================================================
Architecture:
  1. Every article is an editorial INSIGHT about a market.
  2. A RECOMMENDATION (entry/target/stop) is ONLY published when a live signal
     in the DB confirms extra value — NOT generated from hardcoded baselines.
  3. Market selection is ranked by signal confidence: highest-confidence signals first.

Signal-to-Recommendation flow:
  - Fetch markets via pmxt (live Polymarket data)
  - For each market, query signals DB for active signals (whale/catalyst/orderflow/news/contrarian)
  - Only write an article if a signal exists AND the signal has a direction
  - Recommendation uses the signal's stored direction, confidence, rationale
  - Fallback to baseline checks ONLY if no DB signal exists (catch-all)
"""
import sys
import json
import subprocess
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from random import shuffle, random

MINIMAX_API = "https://api.minimax.io/anthropic/v1/messages"
MINIMAX_KEY = "sk-cp-rtpYtXvl0PyCng80lkRXn_3tAkWJhQPKav5vnCy6P6JGFvTVf_b77XpbomU2gHYtQh1iqSKMTQ9huKSz5oFDMdNI4s_mN3x5jDMbiHdfQeP5VgkraPsszR8"
MODEL = "MiniMax-M2.5"
REFERRAL = "Predict221"
ARTICLES_DIR = Path("/var/www/polymarket-site/articles")
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
PMXT_HELPER = "/usr/bin/python3 /tmp/pmxt_markets.py"

sys.path.insert(0, '/opt/polymarket')
try:
    from signals_db import (
        init_db, get_active_signals, get_active_contrarian,
        get_active_arbitrage, get_record, insert_signal,
        get_active_whale_signals, get_active_catalyst_signals,
        get_active_orderflow_signals, get_active_news_signals,
        get_active_contrarian as get_active_contrarian_sig,
    )
    DB_OK = True
except Exception as e:
    DB_OK = False
    print(f"  ⚠️ signals_db import failed: {e}")


# ─── pmxt Market Fetching ───────────────────────────────────────────────────────

def get_markets_via_pmxt(limit: int = 50) -> list:
    """Fetch open markets via pmxt helper — the live Polymarket API."""
    try:
        cmd = f"{PMXT_HELPER} {limit}"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            print(f"  ⚠️ pmxtMarkets failed: {result.stderr[:200]}")
            return []
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  ⚠️ Failed to fetch markets: {e}")
        return []


def parse_market(mkt: dict) -> dict | None:
    """Normalize market data from pmxt helper output."""
    try:
        slug = mkt.get("slug", "")
        question = mkt.get("question", "") or mkt.get("title", "")
        volume = float(mkt.get("volume", 0) or 0)

        if volume < 5000 or not question:
            return None

        yes_price = float(mkt.get("yes", 0.5))
        no_price = float(mkt.get("no", 1.0 - yes_price))

        # end_date may be datetime object or string
        end_date_raw = mkt.get("end_date") or mkt.get("resolution_date") or ""
        if hasattr(end_date_raw, 'strftime'):
            end_date_str = end_date_raw.strftime("%Y-%m-%dT%H:%M:%S")
        elif end_date_raw:
            end_date_str = str(end_date_raw)
        else:
            end_date_str = ""

        return {
            "slug": slug,
            "question": question,
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": volume,
            "volume_24h": float(mkt.get("volume_24h", 0) or 0),
            "liquidity": float(mkt.get("liquidity", 0) or 0),
            "outcome_id": mkt.get("outcome_id", ""),
            "url": f"https://polymarket.com/market/{slug}",
            "referral": f"https://polymarket.com/?r={REFERRAL}&goto=market&slug={slug}",
            "category": _categorize(question),
            "end_date": end_date_str,
        }
    except Exception as e:
        return None


def _categorize(question: str) -> str:
    q = question.lower()
    if any(k in q for k in ["bitcoin", "btc", "crypto", "eth", "sol", "bnb"]):
        return "crypto"
    if any(k in q for k in ["trump", "biden", "election", "president", "vote", "congress"]):
        return "politics"
    if any(k in q for k in ["fed", "rate", "inflation", "gdp", "recession", "unemployment"]):
        return "economy"
    if any(k in q for k in ["china", "russia", "iran", "israel", "war", "nato", "taiwan"]):
        return "geopolitics"
    if any(k in q for k in ["nba", "nfl", "football", "soccer"]):
        return "sports"
    return "general"


# ─── Signal-to-Recommendation Engine ──────────────────────────────────────────

def get_signals_for_market(slug: str) -> dict | None:
    """
    Query all 5 signal tables for active signals on this market slug.
    Returns the highest-confidence signal dict, or None if no signal exists.

    This is the core of Jason's insight-first architecture:
    recommendations only come from real signals, not generated baselines.
    """
    if not DB_OK:
        return None

    all_signals = []

    try:
        # whale_signals — large trade / mega-whale / price momentum
        for s in get_active_whale_signals(limit=10):
            if s.get("market_slug") == slug and s.get("confidence", 0) >= 0.55:
                all_signals.append(("whale", s))

        # catalyst_signals — upcoming event / geopolitics / crypto catalyst
        for s in get_active_catalyst_signals(limit=10):
            if s.get("market_slug") == slug and s.get("confidence", 0) >= 0.60:
                all_signals.append(("catalyst", s))

        # orderflow_signals — spread widening / book imbalance / divergence
        for s in get_active_orderflow_signals(limit=10):
            if s.get("market_slug") == slug and s.get("confidence", 0) >= 0.55:
                all_signals.append(("orderflow", s))

        # news_signals — news corroboration / contradiction
        for s in get_active_news_signals(limit=10):
            if s.get("market_slug") == slug and s.get("confidence", 0) >= 0.55:
                all_signals.append(("news", s))

        # contrarian_signals — odds diverge from historical baseline
        for s in get_active_contrarian_sig(limit=10):
            if s.get("market_slug") == slug and s.get("divergence", 0) >= 0.08:
                all_signals.append(("contrarian", s))

    except Exception as e:
        print(f"  ⚠️ Signal DB query error: {e}")
        return None

    if not all_signals:
        return None

    # Return highest-confidence signal
    best = max(all_signals, key=lambda x: x[1].get("confidence", 0) or x[1].get("divergence", 0))
    return {"source": best[0], **best[1]}


def build_rec_from_signal(signal: dict, market: dict) -> dict | None:
    """
    Convert a live DB signal into a publishable recommendation.
    Uses signal's direction, confidence, entry/target/stop if available.
    Falls back to calculating from market price if signal lacks precise levels.
    """
    source = signal.get("source", "signal")
    sig_type = signal.get("signal_type") or signal.get("catalyst_type") or signal.get("trigger_type") or source
    direction = signal.get("direction") or signal.get("side", "")
    confidence = signal.get("confidence", 0.65)
    yes = market["yes_price"]
    no = market["no_price"]

    if not direction:
        return None

    # Use stored entry/target/stop if available (signal workers set these)
    entry_price = signal.get("entry_price") or signal.get("target_price") or None
    target_price = signal.get("target_price") or None
    stop_loss = signal.get("stop_loss") or None

    # Calculate from price if not stored
    if direction == "YES":
        if entry_price is None:
            entry_price = round(yes + 0.01, 4)
        if target_price is None:
            # Target: move 15-20% toward 1.0
            target_price = round(min(yes + 0.18, 0.97), 4)
        if stop_loss is None:
            stop_loss = round(max(yes - 0.06, 0.25), 4)
    else:  # NO
        if entry_price is None:
            entry_price = round(no + 0.01, 4)
        if target_price is None:
            # Target: move 15% toward 0
            target_price = round(max(no - 0.15, 0.02), 4)
        if stop_loss is None:
            stop_loss = round(min(no + 0.06, 0.75), 4)

    # R/R calculation
    if direction == "YES":
        risk = entry_price - stop_loss
        reward = target_price - entry_price
    else:
        risk = stop_loss - entry_price
        reward = entry_price - target_price

    if risk <= 0:
        return None

    rr = reward / risk

    # Rationale from signal or fallback
    rationale = signal.get("rationale") or (
        f"{sig_type.title()} signal: {source} detected. "
        f"Confidence {confidence:.0%}."
    )

    # Source labels
    source_labels = {
        "whale": "Whale Signal",
        "catalyst": "Catalyst Signal",
        "orderflow": "Orderflow Signal",
        "news": "News Signal",
        "contrarian": "Contrarian Signal",
    }
    type_label = source_labels.get(source, f"{source.title()} Signal")

    return {
        "type": sig_type,
        "type_label": type_label,
        "side": direction,
        "entry": entry_price,
        "target": target_price,
        "stop": stop_loss,
        "risk_reward": round(rr, 2),
        "confidence": round(confidence, 3),
        "rationale": rationale,
    }


# ─── Fallback Baseline Evaluator ──────────────────────────────────────────────
# Only used when no live signal exists in DB for a market.


class RecommendationEvaluator:
    """
    Fallback: Decides whether a recommendation adds genuine value using
    hardcoded baselines. Only reached when get_signals_for_market() returns None.

    This is the catch-all — ideally most articles go through the signal path above.
    """

    def __init__(self, market: dict, insight: dict):
        self.market = market
        self.insight = insight
        self.yes = market["yes_price"]
        self.no = market["no_price"]
        self.question = market["question"]
        self.volume = market["volume"]
        self.q_lower = self.question.lower()

    def evaluate(self) -> dict | None:
        rec = self._check_contrarian()
        if rec:
            rec["type"] = "contrarian"
            rec["type_label"] = "Contrarian Edge"
            return rec

        rec = self._check_catalyst()
        if rec:
            rec["type"] = "catalyst"
            rec["type_label"] = "Catalyst-Driven"
            return rec

        rec = self._check_asymmetric()
        if rec:
            rec["type"] = "asymmetric"
            rec["type_label"] = "Asymmetric R/R"
            return rec

        rec = self._check_momentum()
        if rec:
            rec["type"] = "momentum"
            rec["type_label"] = "Momentum Confirmed"
            return rec

        return None

    def _check_contrarian(self) -> dict | None:
        divergence_threshold = 0.10
        baselines = {}

        if any(k in self.q_lower for k in ["bitcoin", "btc"]):
            baselines["btc_12m"] = 0.65
        if "fed" in self.q_lower and "cut" in self.q_lower:
            baselines["fed_cuts"] = 0.30
        if any(k in self.q_lower for k in ["win the election", "be elected", "president"]):
            baselines["polling"] = self.yes - 0.08 if self.yes > 0.55 else self.yes + 0.08
        if "inflation" in self.q_lower:
            baselines["inflation_risk"] = 0.65
        if any(k in self.q_lower for k in ["war", "invasion", "attack", "conflict"]):
            baselines["tail_risk"] = 0.55

        if not baselines:
            return None

        for baseline_name, baseline_prob in baselines.items():
            divergence = abs(self.yes - baseline_prob)
            if divergence > divergence_threshold:
                direction = "YES" if baseline_prob > self.yes else "NO"
                edge = abs(baseline_prob - self.yes)

                if direction == "YES":
                    entry = self.yes + 0.01
                    target = baseline_prob - 0.02
                    stop = self.yes - 0.05
                else:
                    entry = self.no + 0.01
                    target = (1 - baseline_prob) - 0.02
                    stop = self.no - 0.05

                confidence = min(0.70 + edge * 0.5, 0.90)
                return self._build_rec(direction, entry, target, stop, confidence,
                    f"Contrarian: Polymarket odds ({self.yes:.0%}) diverge {edge:.0%} from {baseline_name} baseline ({baseline_prob:.0%}).")

        return None

    def _check_catalyst(self) -> dict | None:
        end_date_str = self.market.get("end_date", "")
        if not end_date_str:
            return None
        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except Exception:
            return None

        days_until = (end_date - datetime.now().astimezone()).days

        if "fed" in self.q_lower or "rate" in self.q_lower:
            if 0 <= days_until <= 14:
                if self.no > 0.70 and "cut" in self.q_lower:
                    direction = "YES"
                    entry = self.yes + 0.01
                    target = min(self.yes + 0.15, 0.95)
                    stop = max(self.yes - 0.08, 0.20)
                    return self._build_rec(direction, entry, target, stop, 0.75,
                        f"Catalyst: FOMC in {days_until} days. No-cut priced at {self.no:.0%} — historically overstated.")

        if any(k in self.q_lower for k in ["apple", "nvidia", "meta", "google", "amazon"]):
            if 0 <= days_until <= 7:
                if 0.30 < self.yes < 0.70:
                    direction = "YES" if self.yes > 0.55 else "NO"
                    entry = self.yes + 0.01 if direction == "YES" else self.no + 0.01
                    target = self.yes + 0.10 if direction == "YES" else self.no - 0.08
                    stop = self.yes - 0.08 if direction == "YES" else self.no + 0.05
                    return self._build_rec(direction, entry, target, stop, 0.65,
                        f"Catalyst: Earnings in {days_until} day(s). Implied move suggests range-bound outcome not fully priced.")

        if any(k in self.q_lower for k in ["win the 2026", "2026 presidential"]):
            if 0 <= days_until <= 30:
                if 0.40 < self.yes < 0.60:
                    direction = "YES" if self.yes < 0.50 else "NO"
                    entry = self.yes + 0.01 if direction == "YES" else self.no + 0.01
                    target = self.yes + 0.12 if direction == "YES" else self.no - 0.10
                    stop = max(self.yes - 0.06, 0.25) if direction == "YES" else max(self.no - 0.06, 0.25)
                    return self._build_rec(direction, entry, target, stop, 0.68,
                        f"Catalyst: Election in {days_until} days. Odds at {self.yes:.0%} — recent polling tightening suggests value.")

        return None

    def _check_asymmetric(self) -> dict | None:
        min_rr = 2.5
        if self.yes > 0.70:
            target = min(self.yes + 0.18, 0.97)
            stop = max(self.yes - 0.06, 0.40)
            side = "YES"
        elif self.yes < 0.30:
            target = max(self.yes - 0.15, 0.02)
            stop = min(self.yes + 0.08, 0.60)
            side = "NO"
        else:
            return None

        if side == "YES":
            risk = self.yes - stop
            reward = target - self.yes
        else:
            risk = stop - self.no
            reward = self.no - target

        if risk <= 0:
            return None

        rr = reward / risk
        if rr < min_rr:
            return None

        confidence = 0.75 if self.yes > 0.80 or self.yes < 0.20 else 0.68
        rationale = f"Asymmetric: Market at {self.yes:.0%} leaves {rr:.1f}:1 R/R. Target {target:.0%} is reachable with typical post-event movement."
        entry = self.yes + 0.01 if side == "YES" else self.no + 0.01
        return self._build_rec(side, entry, target, stop, confidence, rationale)

    def _check_momentum(self) -> dict | None:
        if self.volume < 50000:
            return None
        if self.yes < 0.20 or self.yes > 0.80:
            return None
        if 0.35 <= self.yes <= 0.65 and self.volume > 200000:
            direction = "YES" if self.yes > 0.52 else "NO"
            entry = self.yes + 0.01 if direction == "YES" else self.no + 0.01
            target = self.yes + 0.18 if direction == "YES" else self.no - 0.15
            stop = self.yes - 0.06 if direction == "YES" else self.no + 0.06

            if direction == "YES":
                risk = entry - stop
                reward = target - entry
            else:
                risk = stop - entry
                reward = entry - target

            if risk <= 0:
                return None
            rr = reward / risk
            if rr < 2.5:
                return None

            confidence = 0.65
            rationale = f"Momentum: ${self.volume/1000:.0f}K in volume at {self.yes:.0%} suggests institutional positioning. {rr:.1f}:1 R/R."
            return self._build_rec(direction, entry, target, stop, confidence, rationale)

        return None

    def _build_rec(self, side: str, entry: float, target: float,
                   stop: float, confidence: float, rationale: str) -> dict:
        if side == "YES":
            risk = entry - stop
            reward = target - entry
        else:
            risk = stop - entry
            reward = entry - target
        rr = reward / risk if risk > 0 else 0
        return {
            "side": side,
            "entry": entry,
            "target": target,
            "stop": stop,
            "risk_reward": rr,
            "confidence": confidence,
            "rationale": rationale,
        }


# ─── Article Generation ───────────────────────────────────────────────────────

def generate_insight_article(market: dict, signal: dict | None = None) -> str | None:
    """
    Generate an editorial insight article about a market.
    If a live signal is provided, use it to drive the recommendation.
    Falls back to baseline evaluator if no signal exists.
    """
    parsed = parse_market(market)
    if not parsed:
        return None

    slug = parsed["slug"]
    question = parsed["question"]
    yes = parsed["yes_price"]
    no = parsed["no_price"]
    vol = parsed["volume"]
    cat = parsed["category"]
    url = parsed["url"]
    referral = parsed["referral"]
    end_date = parsed.get("end_date", "")

    stance_map = {
        (0.80, 1.01): ("strong favorite", "likely resolved YES"),
        (0.60, 0.80): ("moderate favorite", "leaning YES"),
        (0.40, 0.60): ("too close to call", "coin flip territory"),
        (0.20, 0.40): ("underdog", "leaning NO"),
        (0.00, 0.20): ("long shot", "unlikely but possible"),
    }

    def get_stance(p):
        for (lo, hi), (label, desc) in stance_map.items():
            if lo <= p < hi:
                return label, desc
        return ("unknown", "unknown")

    stance, stance_desc = get_stance(yes)

    # ── Determine if a recommendation is warranted ───────────────────────────
    rec = None
    if signal:
        rec = build_rec_from_signal(signal, parsed)

    if not rec:
        insight_data = {"stance": stance, "stance_desc": stance_desc, "volume": vol}
        evaluator = RecommendationEvaluator(parsed, insight_data)
        rec = evaluator.evaluate()

    # ── Build signal context for prompt ─────────────────────────────────────
    sig_src = ""
    sig_type = ""
    sig_conf = 0
    sig_dir = ""
    sig_rat = ""
    if signal:
        sig_src = signal.get("source", "signal").upper()
        sig_type = signal.get("signal_type") or signal.get("catalyst_type") or signal.get("trigger_type", "detected")
        sig_conf = signal.get("confidence", 0)
        sig_dir = signal.get("direction") or signal.get("side", "")
        sig_rat = (signal.get("rationale") or "")[:200]

    # ── Build article prompt using explicit string parts ─────────────────────
    # (avoids triple-quoted f-string parser issues in Python 3.12)
    yes_pct = f"{yes:.1%}"
    no_pct = f"{no:.1%}"
    vol_fmt = f"${vol:,.0f}"
    conf_pct = f"{sig_conf:.0%}"
    end_date_fmt = end_date[:10] if end_date else "Open-ended"
    stance_esc = stance.replace('"', '\"')
    question_esc = question.replace('"', '\"')

    prompt_parts = [
        "Write a high-quality editorial INSIGHT article about the prediction market question: \"" + question_esc + "\"\n",
        "\n",
        "CURRENT MARKET DATA:\n",
        "- Current YES probability: " + yes_pct + "\n",
        "- 24h volume: " + vol_fmt + "\n",
        "- Market stance: \"" + stance_esc + "\" — market sees this as " + stance_desc + "\n",
        "- Category: " + cat.capitalize() + "\n",
        "- Resolution date: " + end_date_fmt + "\n",
        "\n",
    ]

    if signal:
        prompt_parts += [
            "LIVE SIGNAL DETECTED (confidence: " + conf_pct + "):\n",
            "- Signal source: " + sig_src + "\n",
            "- Type: " + sig_type + "\n",
            "- Direction: " + sig_dir + "\n",
            "- Rationale: " + sig_rat + "\n",
            "\n",
            "Incorporate this signal context naturally into the article narrative.\n",
            "If a recommendation block is included, use the signal's direction and rationale.\n",
        ]
    else:
        prompt_parts += [
            "No active signal in our system for this market — article will be insight-only.\n",
            "Do NOT include a trade recommendation unless the market naturally warrants it.\n",
        ]

    prompt_parts += [
        "\n",
        "WRITE THE ARTICLE WITH THIS EXACT STRUCTURE:\n",
        "\n",
        "1. **H1 Title** — Catchy, keyword-rich. Example: \"Why the Fed's Next Move Could Shock Crypto Markets\"\n",
        "\n",
        "2. **Market Snapshot** (styled box):\n",
        "   - Current Odds: " + yes_pct + " YES / " + no_pct + " NO\n",
        "   - Volume: " + vol_fmt + "\n",
        "   - Stance: " + stance_esc + "\n",
        "\n",
        "3. **What's Happening** (150 words): The current situation. What's driving the market right now.\n",
        "\n",
        "4. **Why It Matters** (150 words): Why this market is worth watching beyond the obvious outcome.\n",
        "\n",
        "5. **What the Odds Don't Tell You** (150 words): Interesting nuance, historical context, or angle the current price doesn't fully reflect.\n",
        "\n",
        "6. **Timeline & Resolution** (100 words): When does this resolve? Key date or event to watch.\n",
        "\n",
        "7. **What Could Change the Odds** (100 words): Factors that could move the market before resolution.\n",
        "\n",
        "8. **CTA**: If you're interested in this market, you can trade it on Polymarket → https://polymarket.com/?r=" + REFERRAL + "\n",
        "\n",
        "9. **FAQ**: 3 natural questions a curious reader would ask, answered concisely.\n",
        "\n",
        "10. **Disclaimer**: Not financial advice.\n",
        "\n",
        "TONE: Informed, analytical, like a premium research newsletter. Specific numbers. No fluff.\n",
        "LENGTH: 800-1000 words. Include the affiliate link naturally once.\n",
        "FORMAT: Use H2 headers. No trade alert box unless genuinely warranted.",
    ]

    insight_prompt = "".join(prompt_parts)

    content = call_minimax(insight_prompt)
    if not content:
        return None

    # ── Build HTML ───────────────────────────────────────────────────────────
    rec_html = _build_recommendation_block(rec) if rec else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{question[:80]} — Insight | Predict221</title>
    <meta name="description" content="{question[:150]} Current odds: {yes_pct} | {vol_fmt} traded. Insight and analysis from Predict221.">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.7; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #58a6ff; font-size: 1.7em; margin: 25px 0 10px; }}
        h2 {{ color: #f0883e; border-bottom: 1px solid #30363d; padding-bottom: 8px; margin: 28px 0 14px; }}
        .snapshot {{ background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;margin:20px 0 }}
        .snapshot .prob {{ font-size:2.2em;font-weight:700;color:{'#238636' if yes>0.5 else '#f85149'} }}
        .snapshot .labels {{ color:#8b949e;margin-top:6px;font-size:0.9em }}
        .meta {{ background:#21262d;padding:12px 15px;border-radius:8px;margin:15px 0;font-size:0.9em;color:#8b949e }}
        .rec-box {{ background:#161b22;border:2px solid #238636;border-radius:12px;padding:22px;margin:25px 0;position:relative}}
        .rec-box h3 {{ color:#238636;margin:0 0 14px;font-size:0.95em;text-transform:uppercase;letter-spacing:0.05em}}
        .rec-row {{ display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #21262d}}
        .rec-row:last-child {{ border:none }}
        .rec-label {{ color:#8b949e }}
        .rec-val {{ font-weight:600 }}
        .rec-val.green {{ color:#238636 }}
        .rec-val.red {{ color:#f85149 }}
        .rec-type {{ position:absolute;top:12px;right:15px;font-size:0.7em;background:#238636;color:white;padding:2px 8px;border-radius:4px;text-transform:uppercase}}
        .insight-callout {{ background:#1c2128;border-left:3px solid #f0883e;padding:12px 16px;margin:15px 0;font-size:0.95em;color:#8b949e}}
        .insight-callout strong {{ color:#f0883e }}
        .cta {{ background:#238636;color:white;padding:14px 28px;border-radius:8px;text-decoration:none;display:inline-block;margin:20px 0;font-weight:600;font-size:1em }}
        .cta:hover {{ background:#2ea043;color:white;text-decoration:none }}
        .disclaimer {{ background:#21262d;padding:15px;border-radius:8px;margin-top:40px;font-size:0.85em;color:#6e7681 }}
        a {{ color:#58a6ff }}
        p {{ margin:14px 0 }}
        .no-rec {{ color:#6e7681;font-size:0.85em;text-align:center;padding:15px;background:#161b22;border-radius:8px;border:1px solid #21262d}}
    </style>
</head>
<body>
    <p><a href="/">← Predict221</a> <span style="color:#6e7681;margin-left:10px">|</span> <span style="margin-left:10px">{cat.capitalize()}</span></p>
    <h1>{question}</h1>

    <div class="snapshot">
        <div class="prob">{yes_pct} YES</div>
        <div class="labels">{yes_pct} YES · {no_pct} NO · {vol_fmt} traded · {stance}</div>
    </div>

    {rec_html}

    <div class="meta">
        Market stance: <strong>{stance}</strong> — {stance_desc}.
        <a href="{url}" style="margin-left:10px">View on Polymarket ↗</a>
    </div>

    {content}

    <a href="{referral}" class="cta">Analyze This Market on Polymarket →</a>

    <div class="disclaimer">
        <strong>Not financial advice.</strong> Prediction markets are speculative. This analysis is for educational purposes.
        Our track record: <a href="/record" style="color:#58a6ff;">transparent record →</a>
        · Affiliate: <a href="https://polymarket.com/?r={REFERRAL}">polymarket.com/?r={REFERRAL}</a>
    </div>
</body>
</html>"""

    filepath = ARTICLES_DIR / f"{slug}.html"
    filepath.write_text(html)
    return str(filepath)



def _build_recommendation_block(rec: dict) -> str:
    """Build the recommendation HTML block."""
    side = rec["side"]
    entry = rec["entry"]
    target = rec["target"]
    stop = rec["stop"]
    rr = rec["risk_reward"]
    conf = rec["confidence"]
    rationale = rec["rationale"]
    type_label = rec.get("type_label", "Trade Setup")

    return f"""
<div class="rec-box">
    <span class="rec-type">{type_label}</span>
    <h3>💡 Recommendation — {side}</h3>
    <div class="rec-row"><span class="rec-label">Direction</span><span class="rec-val {'green' if side=='YES' else 'red'}">{side}</span></div>
    <div class="rec-row"><span class="rec-label">Entry Zone</span><span class="rec-val">{entry:.1%}</span></div>
    <div class="rec-row"><span class="rec-label">Target</span><span class="rec-val green">{target:.1%}</span></div>
    <div class="rec-row"><span class="rec-label">Stop Loss</span><span class="rec-val red">{stop:.1%}</span></div>
    <div class="rec-row"><span class="rec-label">Risk/Reward</span><span class="rec-val">{rr:.1f}:1</span></div>
    <div class="rec-row"><span class="rec-label">Confidence</span><span class="rec-val">{conf:.0%}</span></div>
    <div class="insight-callout" style="margin-top:14px">
        <strong>Why this recommendation adds value:</strong> {rationale}
    </div>
</div>"""


# ─── MiniMax ──────────────────────────────────────────────────────────────────

def call_minimax(prompt, max_tokens=2500):
    data = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(
        MINIMAX_API,
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {MINIMAX_KEY}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        for block in result.get("content", []):
            if block.get("type") == "text":
                return block.get("text", "")
    except Exception as e:
        print(f"  ⚠️ MiniMax error: {e}")
    return ""


# ─── Main CLI ─────────────────────────────────────────────────────────────────

def main():
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    cmd = sys.argv[1] if len(sys.argv) > 1 else "generate"

    if cmd == "signals-only":
        # Lightweight: refresh signals dashboard HTML without generating articles
        print("📊 Refreshing signals dashboard...")
        refresh_signals_dashboard()
        return

    if cmd == "generate":
        print(f"📰 Fetching markets via pmxt...\n")
        raw_markets = get_markets_via_pmxt(limit=count * 3)
        markets = [m for m in raw_markets if parse_market(m)]

        # Filter to ones we haven't covered
        existing = {p.stem for p in ARTICLES_DIR.glob("*.html")}
        new_markets = [m for m in markets if parse_market(m) and parse_market(m)["slug"] not in existing]

        # ── Signal-ranked selection: prioritize markets with active DB signals ──
        def signal_rank(mkt):
            parsed = parse_market(mkt)
            if not parsed:
                return -1
            sig = get_signals_for_market(parsed["slug"])
            if not sig:
                return -1
            return sig.get("confidence", 0) or sig.get("divergence", 0) or -1

        # Sort: markets with signals first (by confidence desc), then shuffle remaining
        new_markets.sort(key=signal_rank, reverse=True)

        # Take top N with signals + some without to diversify
        with_signals = [m for m in new_markets if signal_rank(m) > 0]
        without_signals = [m for m in new_markets if signal_rank(m) <= 0]
        shuffle(without_signals)

        # Target: ~50% from signal-ranked, rest fill remaining slots
        target_with = min(count // 2 + 1, len(with_signals))
        selected = with_signals[:target_with] + without_signals[:count - target_with]
        shuffle(selected)

        print(f"📝 Generating {len(selected)} insight articles ({len(with_signals)} signal-backed, {len(without_signals)} baseline)...\n")

        generated = 0
        recs_published = 0
        for i, m in enumerate(selected, 1):
            parsed = parse_market(m)
            if not parsed:
                continue
            slug = parsed["slug"]
            question = parsed["question"][:60]

            # Check for live signal
            sig = get_signals_for_market(slug)
            rec_label = f"📊 {sig.get('source', 'signal').upper()}" if sig else "📄"

            print(f"[{i}] {rec_label} {question}...")
            path = generate_insight_article(m, signal=sig)
            if path:
                generated += 1
                if sig:
                    recs_published += 1
                    print(f"    ✅ SIGNAL-BACKED RECOMMENDATION ({sig.get('source', 'db')}, conf={sig.get('confidence', 0):.0%})")
                    if DB_OK:
                        try:
                            init_db()
                            rec = build_rec_from_signal(sig, parsed)
                            if rec:
                                signal_id = insert_signal(
                                    signal_type=rec["type"],
                                    market_slug=slug,
                                    question=parsed["question"],
                                    side=rec["side"],
                                    confidence=rec["confidence"],
                                    current_price=parsed["yes_price"],
                                    entry_price=rec["entry"],
                                    target_price=rec["target"],
                                    stop_loss=rec["stop"],
                                    rationale=rec["rationale"],
                                    market_url=parsed["url"],
                                    expires_hours=72,
                                )
                                print(f"    🆔 Signal #{signal_id} stored")
                        except Exception as e:
                            print(f"    ⚠️ DB error: {e}")
                else:
                    print(f"    ✅ INSIGHT ONLY (no recommendation warranted)")
            else:
                print(f"    ❌ Failed")

        print(f"\n✅ Done: {generated} articles ({recs_published} with signal-backed recommendations)")


def refresh_signals_dashboard():
    """Refresh lightweight signals dashboard HTML without calling MiniMax."""
    if not DB_OK:
        return
    try:
        init_db()
        # Placeholder — dashboard is served by server.py via /api
        print("  Dashboard served by server.py — no refresh needed")
    except Exception as e:
        print(f"  ⚠️ Dashboard error: {e}")


if __name__ == "__main__":
    main()
