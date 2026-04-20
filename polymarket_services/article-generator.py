#!/usr/bin/env python3
"""
Polymarket Article Generator — Insights-first, Recommendations only when they add genuine value.
============================================================================================
Architecture:
  1. Every article is an editorial INSIGHT about a market.
  2. A RECOMMENDATION (entry/target/stop) is only published when it adds genuine edge.
  3. Recommendations are NOT generated separately — they are a conditional output of analysis.

When does a recommendation add value?
  - CONTRARIAN: Polymarket odds diverge >10% from an obvious external baseline
  - CATALYST: Upcoming event with a clear dominant outcome the market hasn't fully priced
  - ASYMMETRIC: Exit point clearly exceeds what fair value + fees justify
  - MOMENTUM CONFIRMED: Volume + price action strongly supports a side at current odds
"""
import sys
import json
import requests
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from random import shuffle, random

MINIMAX_API = "https://api.minimax.io/anthropic/v1/messages"
MINIMAX_KEY = "sk-cp-rtpYtXvl0PyCng80lkRXn_3tAkWJhQPKav5vnCy6P6JGFvTVf_b77XpbomU2gHYtQh1iqSKMTQ9huKSz5oFDMdNI4s_mN3x5jDMbiHdfQeP5VgkraPsszR8"
MODEL = "MiniMax-M2.5"
GAMMA_API = "https://gamma-api.polymarket.com"
REFERRAL = "Predict221"
ARTICLES_DIR = Path("/var/www/polymarket-site/articles")
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, '/opt/polymarket')
try:
    from signals_db import (
        init_db, get_active_signals, get_active_contrarian,
        get_active_arbitrage, get_record, insert_signal,
        get_recent_results
    )
    DB_OK = True
except Exception:
    DB_OK = False


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


# ─── Market Fetching ──────────────────────────────────────────────────────────

def get_markets(limit=20):
    """Fetch open markets sorted by volume"""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"limit": limit, "closed": "false"},
            timeout=15
        )
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        print(f"  ⚠️ Failed to fetch markets: {e}")
        return []


def parse_market(market: dict) -> dict | None:
    """Normalize market data from various API response formats"""
    try:
        slug = market.get("slug", "")
        question = market.get("question", "")
        volume = float(market.get("volume", 0) or 0)

        if volume < 5000 or not question:
            return None

        # Parse prices
        raw_prices = market.get("outcomePrices", [])
        if isinstance(raw_prices, str):
            try:
                raw_prices = json.loads(raw_prices)
            except:
                raw_prices = []
        if not isinstance(raw_prices, list):
            raw_prices = []

        yes_price = float(raw_prices[0]) if len(raw_prices) > 0 else 0.50
        no_price = float(raw_prices[1]) if len(raw_prices) > 1 else 1.0 - yes_price

        return {
            "slug": slug,
            "question": question,
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": volume,
            "liquidity": float(market.get("liquidity", 0) or 0),
            "url": f"https://polymarket.com/market/{slug}",
            "referral": f"https://polymarket.com/?r={REFERRAL}&goto=market&slug={slug}",
            "category": _categorize(question),
            "end_date": market.get("end_date", ""),
        }
    except Exception:
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
    if any(k in q for k in ["nba", "nfl", "football", "soccer", "election"]):
        return "sports"
    return "general"


# ─── Recommendation Evaluator ──────────────────────────────────────────────────

class RecommendationEvaluator:
    """
    Decides whether a recommendation adds genuine value to an insight.

    A recommendation is ONLY published when it provides extra value beyond
    "the market already tells you what to do at current odds."

    Returns a dict with recommendation data if it qualifies, None otherwise.
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
        """
        Returns recommendation dict if it adds value, None if not worth publishing.
        """
        # Check each value-add criterion
        rec = None

        # 1. Contrarian check
        rec = self._check_contrarian()
        if rec:
            rec["type"] = "contrarian"
            rec["type_label"] = "Contrarian Edge"
            return rec

        # 2. Catalyst check
        rec = self._check_catalyst()
        if rec:
            rec["type"] = "catalyst"
            rec["type_label"] = "Catalyst-Driven"
            return rec

        # 3. Asymmetric R/R check
        rec = self._check_asymmetric()
        if rec:
            rec["type"] = "asymmetric"
            rec["type_label"] = "Asymmetric R/R"
            return rec

        # 4. Momentum confirmation (only if volume is strong AND odds in sweet spot)
        rec = self._check_momentum()
        if rec:
            rec["type"] = "momentum"
            rec["type_label"] = "Momentum Confirmed"
            return rec

        return None

    def _check_contrarian(self) -> dict | None:
        """
        Contrarian value: Polymarket odds diverge significantly from
        what an obvious external reference suggests.

        Examples:
        - PM shows 30% for X, but crypto markets are pricing 60%+ for X
        - PM shows 72% for Fed cut, but Fed guidance implies <20%
        - PM shows 55% for candidate win, but polling average shows 45%
        """
        divergence_threshold = 0.10  # 10 percentage points

        # External baselines (approximate real-world references)
        baselines = {}

        # Bitcoin halving effect — historically 6-12 months post-halving, BTC trends up strongly
        if any(k in self.q_lower for k in ["bitcoin", "btc"]):
            baselines["btc_12m"] = 0.65  # Historical post-halving probability of new highs

        # Fed rate cuts — market consensus vs actual Fed signals
        if "fed" in self.q_lower and "cut" in self.q_lower:
            baselines["fed_cuts"] = 0.30  # Fed has signaled restraint

        # Election markets — PM vs polling averages
        if any(k in self.q_lower for k in ["win the election", "be elected", "president"]):
            # If PM shows >55% for one candidate, real polling is usually closer
            if self.yes > 0.55:
                baselines["polling"] = self.yes - 0.08  # PM premium
            elif self.yes < 0.45:
                baselines["polling"] = self.yes + 0.08

        # Inflation — markets often under-react to inflation risks
        if "inflation" in self.q_lower:
            if self.yes < 0.50:
                baselines["inflation_risk"] = 0.65  # Inflation is stickier than priced

        # War/conflict — PM often underprices geopolitical tail risks
        if any(k in self.q_lower for k in ["war", "invasion", "attack", "conflict"]):
            if self.yes < 0.40:
                baselines["tail_risk"] = 0.55  # Geopolitical tail risks underpriced

        if not baselines:
            return None

        for baseline_name, baseline_prob in baselines.items():
            divergence = abs(self.yes - baseline_prob)
            if divergence > divergence_threshold:
                direction = "YES" if baseline_prob > self.yes else "NO"
                edge = abs(baseline_prob - self.yes)

                # Calculate entry, target, stop
                if direction == "YES":
                    entry = self.yes + 0.01  # slightly above current to confirm
                    target = baseline_prob - 0.02  # aim for fair value
                    stop = self.yes - 0.05  # allow 5% buffer
                else:
                    entry = self.no + 0.01
                    target = (1 - baseline_prob) - 0.02
                    stop = self.no - 0.05

                confidence = min(0.70 + edge * 0.5, 0.90)
                return self._build_rec(direction, entry, target, stop, confidence,
                    f"Contrarian: Polymarket odds ({self.yes:.0%}) diverge {edge:.0%} from {baseline_name} baseline ({baseline_prob:.0%}).")

        return None

    def _check_catalyst(self) -> dict | None:
        """
        Catalyst-driven value: An event is coming that has a clear dominant outcome,
        but the market hasn't fully priced it yet.
        """
        # Event categories with implied catalysts
        catalyst_thresholds = {
            "election": 14,   # days before election
            "fed": 7,         # days before FOMC
            "gdp": 5,        # days before GDP release
            "inflation": 5,   # days before CPI
            "earnings": 3,    # days before earnings
            "court": 14,      # days before Supreme Court ruling
        }

        # Parse end_date if available
        end_date_str = self.market.get("end_date", "")
        if not end_date_str:
            return None

        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except Exception:
            return None

        days_until = (end_date - datetime.now()).days

        # Fed meetings — market pricing of cuts is often wrong
        if "fed" in self.q_lower or "rate" in self.q_lower:
            if days_until <= 14 and days_until >= 0:
                # PM odds for "no cut" being >70% — potential buy on "cut" if catalyst strong
                if self.no > 0.70 and "cut" in self.q_lower.lower():
                    direction = "YES"
                    entry = self.yes + 0.01
                    target = min(self.yes + 0.15, 0.95)
                    stop = max(self.yes - 0.08, 0.20)
                    return self._build_rec(direction, entry, target, stop, 0.75,
                        f"Catalyst: FOMC meeting in {days_until} days. Market pricing {self.no:.0%} for no cut — historically overstated.")

        # Earnings — implied move often wider than actual
        if "apple" in self.q_lower or "nvidia" in self.q_lower or "meta" in self.q_lower:
            if 0 <= days_until <= 7:
                # High implied volatility — potential vol crush after
                if self.yes > 0.30 and self.yes < 0.70:
                    direction = "YES" if self.yes > 0.55 else "NO"
                    entry = self.yes + 0.01 if direction == "YES" else self.no + 0.01
                    target = self.yes + 0.10 if direction == "YES" else self.no - 0.08
                    stop = self.yes - 0.08 if direction == "YES" else self.no + 0.05
                    return self._build_rec(direction, entry, target, stop, 0.65,
                        f"Catalyst: Earnings in {days_until} day(s). Implied move suggests range-bound outcome not fully priced.")

        # US elections — PM is usually closer to reality but there is a systematic D/R premium
        if any(k in self.q_lower for k in ["win the 2026", "2026 presidential"]):
            if days_until <= 30:
                # Recent polling suggests tighter race than PM
                if 0.40 < self.yes < 0.60:
                    direction = "YES" if self.yes < 0.50 else "NO"
                    entry = self.yes + 0.01 if direction == "YES" else self.no + 0.01
                    target = self.yes + 0.12 if direction == "YES" else self.no - 0.10
                    stop = max(self.yes - 0.06, 0.25) if direction == "YES" else max(self.no - 0.06, 0.25)
                    return self._build_rec(direction, entry, target, stop, 0.68,
                        f"Catalyst: Election in {days_until} days. Odds at {self.yes:.0%} — recent polling tightening suggests value on {'YES' if self.yes < 0.50 else 'NO'}.")

        return None

    def _check_asymmetric(self) -> dict | None:
        """
        Asymmetric R/R value: The target is clearly justified by market structure,
        fees are low enough to allow profit, and the R/R ratio is compelling.
        """
        # Only consider if R/R > 2.5:1 (genuinely asymmetric)
        min_rr = 2.5

        # High-confidence markets where target is obvious
        if self.yes > 0.70:
            # Clear favorite — target above 90% should be achievable
            target = min(self.yes + 0.18, 0.97)
            stop = max(self.yes - 0.06, 0.40)
            side = "YES"
        elif self.yes < 0.30:
            # Clear underdog — target is approaching 0
            target = max(self.yes - 0.15, 0.02)
            stop = min(self.yes + 0.08, 0.60)
            side = "NO"
        else:
            return None  # No obvious asymmetric case

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
        rationale = (
            f"Asymmetric: Market at {self.yes:.0%} leaves {rr:.1f}:1 R/R. "
            f"Target {target:.0%} is reachable with typical post-event movement."
        )
        entry = self.yes + 0.01 if side == "YES" else self.no + 0.01
        return self._build_rec(side, entry, target, stop, confidence, rationale)

    def _check_momentum(self) -> dict | None:
        """
        Momentum confirmed value: Volume + price movement strongly supports
        a side, but ONLY if the R/R is genuinely compelling (>= 2.5:1).
        """
        # Need significant volume for momentum claim
        if self.volume < 50000:
            return None

        # Only in the "too close to call" zone where momentum can shift odds meaningfully
        if self.yes < 0.20 or self.yes > 0.80:
            return None

        # For 35-65% range — momentum can push toward extremes
        if 0.35 <= self.yes <= 0.65:
            # Strong recent volume suggests directional bias
            if self.volume > 200000:
                direction = "YES" if self.yes > 0.52 else "NO"
                entry = self.yes + 0.01 if direction == "YES" else self.no + 0.01
                # Target: 15-20% move from current price
                target = self.yes + 0.18 if direction == "YES" else self.no - 0.15
                # Stop: 6% against the trade
                stop = self.yes - 0.06 if direction == "YES" else self.no + 0.06

                # Calculate R/R — must be >= 2.5:1 to publish
                if direction == "YES":
                    risk = entry - stop
                    reward = target - entry
                else:
                    risk = entry - stop
                    reward = entry - target

                if risk <= 0:
                    return None
                rr = reward / risk
                if rr < 2.5:
                    return None  # R/R not compelling enough — no recommendation

                confidence = 0.65
                rationale = (
                    f"Momentum: ${self.volume/1000:.0f}K in volume at {self.yes:.0%} suggests "
                    f"institutional positioning. Directional move likely — {rr:.1f}:1 R/R."
                )
                return self._build_rec(direction, entry, target, stop, confidence, rationale)

        return None

    def _build_rec(self, side: str, entry: float, target: float,
                   stop: float, confidence: float, rationale: str) -> dict:
        """Build a recommendation dict"""
        if side == "YES":
            risk = entry - stop
            reward = target - entry
        else:
            risk = entry - stop
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


# ─── Article Generation ────────────────────────────────────────────────────────

def generate_insight_article(market: dict) -> str | None:
    """
    Generate an editorial insight article about a market.
    A recommendation block is conditionally included ONLY if it adds genuine value.
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

    # ── Run MiniMax analysis first ──────────────────────────────────────────
    insight_prompt = f"""Write a high-quality editorial INSIGHT article about the prediction market question: "{question}"

CURRENT MARKET DATA:
- Current YES probability: {yes:.1%}
- 24h volume: ${vol:,.0f}
- Market stance: "{stance}" — market sees this as {stance_desc}

CONTEXT:
- Category: {cat.capitalize()}
- Resolution date: {end_date[:10] if end_date else 'Open-ended'}

WRITE THE ARTICLE WITH THIS EXACT STRUCTURE:

1. **H1 Title** — Catchy, keyword-rich. Example: "Why the Fed's Next Move Could Shock Crypto Markets" or "Bitcoin Halving: What the {yes:.0%} Odds Actually Tell Us"

2. **Market Snapshot** (styled box):
   - Current Odds: {yes:.1%} YES / {no:.1%} NO
   - Volume: ${vol:,.0f}
   - Stance: {stance}

3. **What's Happening** (150 words): The current situation. What's driving the market right now. What participants are thinking.

4. **Why It Matters** (150 words): Why this market is worth watching. What makes it interesting beyond the obvious outcome.

5. **What the Odds Don't Tell You** (150 words): Interesting nuance, historical context, or angle that the current price doesn't fully reflect.

6. **Timeline & Resolution** (100 words): When does this resolve? What's the key date or event? What to watch between now and then.

7. **What Could Change the Odds** (100 words): Factors that could move the market higher or lower before resolution.

8. **CTA**: If you're interested in this market, you can trade it on Polymarket → https://polymarket.com/?r={REFERRAL}

9. **FAQ**: 3 natural questions a curious reader would ask, answered concisely.

10. **Disclaimer**: Not financial advice.

TONE: Informed, analytical, like a premium research newsletter (Bloomberg, The Breakdown). Specific numbers. No fluff. This is about understanding the market deeply.
LENGTH: 800-1000 words. Include the affiliate link naturally once.
FORMAT: Use H2 headers. No trade alert box unless genuinely warranted."""


    content = call_minimax(insight_prompt)
    if not content:
        return None

    # ── Evaluate whether a recommendation adds value ────────────────────────
    insight_data = {
        "stance": stance,
        "stance_desc": stance_desc,
        "volume": vol,
    }
    evaluator = RecommendationEvaluator(parsed, insight_data)
    rec = evaluator.evaluate()

    # ── Build HTML ───────────────────────────────────────────────────────────
    if rec:
        rec_html = _build_recommendation_block(rec)
    else:
        rec_html = ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{question[:80]} — Insight | Predict221</title>
    <meta name="description" content="{question[:150]}. Current odds: {yes:.1%} | ${vol:,.0f} traded. Insight and analysis from Predict221.">
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
        <div class="prob">{yes:.1%} YES</div>
        <div class="labels">{yes:.1%} YES · {no:.1%} NO · ${vol:,.0f} traded · {stance}</div>
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
    """Build the recommendation HTML block for a qualifying recommendation"""
    side = rec["side"]
    entry = rec["entry"]
    target = rec["target"]
    stop = rec["stop"]
    rr = rec["risk_reward"]
    conf = rec["confidence"]
    rationale = rec["rationale"]
    type_label = rec.get("type_label", "Trade Setup")
    rec_type_class = rec.get("type", "setup").lower()

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


# ─── Main CLI ─────────────────────────────────────────────────────────────────

def main():
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    cmd = sys.argv[1] if len(sys.argv) > 1 else "generate"

    if cmd == "generate":
        print(f"📰 Fetching markets...\n")
        markets = get_markets(limit=count * 2)
        shuffle(markets)

        # Filter to ones we haven't covered
        existing = {p.stem for p in ARTICLES_DIR.glob("*.html")}
        new_markets = [m for m in markets if parse_market(m) and parse_market(m)["slug"] not in existing]
        new_markets = new_markets[:count]

        print(f"📝 Generating {len(new_markets)} insight articles...\n")
        generated = 0
        recs_published = 0
        for i, m in enumerate(new_markets, 1):
            parsed = parse_market(m)
            if not parsed:
                continue
            slug = parsed["slug"]
            question = parsed["question"][:60]

            # Quick check: would this even have a recommendation?
            evaluator = RecommendationEvaluator(parsed, {})
            rec = evaluator.evaluate()

            print(f"[{i}] {'📊 WITH REC' if rec else '📄'} {question}...")
            path = generate_insight_article(m)
            if path:
                generated += 1
                if rec:
                    recs_published += 1
                    print(f"    ✅ INSIGHT + RECOMMENDATION ({rec['type']}, {rec['risk_reward']:.1f}:1 R/R)")
                    # Store signal for tracking
                    if DB_OK:
                        try:
                            init_db()
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
                    print(f"    ✅ INSIGHT ONLY (no recommendation — market doesn't warrant extra)")
            else:
                print(f"    ❌ Failed")

        print(f"\n✅ Done: {generated} articles ({recs_published} with recommendations)")


if __name__ == "__main__":
    main()
