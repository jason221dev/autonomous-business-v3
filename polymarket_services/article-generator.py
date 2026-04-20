#!/usr/bin/env python3
"""
Polymarket Trade-Setup Article Generator
Generates actionable trading insight articles from live market data + signals DB.
Each article includes: entry price, target, stop loss, confidence, rationale.
"""
import sys
import json
import requests
import urllib.request
from datetime import datetime
from pathlib import Path
from random import shuffle

MINIMAX_API = "https://api.minimax.io/anthropic/v1/messages"
MINIMAX_KEY = "sk-cp-rtpYtXvl0PyCng80lkRXn_3tAkWJhQPKav5vnCy6P6JGFvTVf_b77XpbomU2gHYtQh1iqSKMTQ9huKSz5oFDMdNI4s_mN3x5jDMbiHdfQeP5VgkraPsszR8"
MODEL = "MiniMax-M2.5"
GAMMA_API = "https://gamma-api.polymarket.com"
REFERRAL = "Predict221"
ARTICLES_DIR = Path("/var/www/polymarket-site/articles")
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

# Add opt/polymarket to path for signals_db
sys.path.insert(0, '/opt/polymarket')
try:
    from signals_db import get_active_signals, get_active_contrarian, get_active_arbitrage, init_db, get_top_signals_for_articles
    SIGNALS_OK = True
except Exception:
    SIGNALS_OK = False


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


def get_trending_markets(limit=15):
    """Fetch top markets by volume, using pmxt/polymarket-apis if available"""
    try:
        from polymarket_apis import PolymarketGammaClient
        client = PolymarketGammaClient()
        markets = client.get_markets(limit=limit, closed=False)
        return markets
    except Exception:
        pass

    # Fallback to direct API
    resp = requests.get(
        f"{GAMMA_API}/markets",
        params={"limit": limit, "closed": "false"},
        timeout=15
    )
    data = resp.json()
    return data if isinstance(data, list) else data.get("data", [])


def get_trade_setup_for_market(slug: str, question: str) -> dict | None:
    """Get any stored signal for a given market slug"""
    if not SIGNALS_OK:
        return None
    try:
        init_db()
        signals = get_active_signals(limit=10)
        for s in signals:
            if s.get("market_slug") == slug:
                return s
    except Exception:
        pass
    return None


def get_top_setup_articles(limit=5) -> list:
    """Pull best trade setups from signals DB for dedicated articles"""
    if not SIGNALS_OK:
        return []
    try:
        init_db()
        signals = get_active_signals(limit=limit)
        arbitrage = get_active_arbitrage()
        contrarian = get_active_contrarian(limit=3)
        return {
            "signals": signals,
            "arbitrage": arbitrage,
            "contrarian": contrarian,
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"⚠️ Signals DB error: {e}")
        return {}


def format_price(p: float) -> str:
    """Format price as percentage string"""
    return f"{p:.1%}"


def format_price_odds(p: float) -> str:
    """Format as decimal odds"""
    if p <= 0:
        return "N/A"
    return f"${p:.4f}"


def generate_trade_setup_article(signal: dict) -> str | None:
    """Generate a full trade-setup article from a signal"""
    sig_type = signal.get("signal_type", "trend")
    slug = signal.get("market_slug", "")
    question = signal.get("question", "")
    side = signal.get("side", "YES")
    confidence = signal.get("confidence", 0.65)
    entry = signal.get("entry_price", 0.50)
    target = signal.get("target_price", 0.80)
    stop = signal.get("stop_loss", 0.35)
    rationale = signal.get("rationale", "")
    current = signal.get("current_price", entry)
    market_url = signal.get("market_url", f"https://polymarket.com/market/{slug}")
    
    # Calculate risk/reward
    if side == "YES":
        risk = entry - stop
        reward = target - entry
    else:
        risk = entry - stop
        reward = entry - target
    
    rr_ratio = reward / risk if risk > 0 else 0
    risk_pct = (risk / entry) * 100 if entry > 0 else 0
    
    # Signal type labels
    type_labels = {
        "price_divergence": "Price Divergence Setup",
        "volume_spike": "Volume Spike Setup",
        "trend_continuation": "Trend Continuation Setup",
        "breakout": "Breakout Setup",
        "mean_reversion": "Mean Reversion Setup",
    }
    setup_label = type_labels.get(sig_type, "Trade Setup")
    
    # Category inference
    cat = "general"
    q_lower = question.lower()
    if any(k in q_lower for k in ["bitcoin", "btc", "crypto", "eth", "sol"]):
        cat = "crypto"
    elif any(k in q_lower for k in ["trump", "biden", "election", "president", "vote"]):
        cat = "politics"
    elif any(k in q_lower for k in ["fed", "rate", "inflation", "gdp", "recession"]):
        cat = "economy"
    elif any(k in q_lower for k in ["china", "russia", "iran", "israel", "war"]):
        cat = "geopolitics"

    prompt = f"""Write a compelling, SEO-optimized trade setup article about: "{question}"

This is a **{side}** trade on Polymarket prediction market.

TRADE SETUP DATA:
- Market: {question}
- Signal Type: {setup_label}
- Current Price: {format_price(current)} ({side})
- Entry Price: {format_price(entry)}
- Target Price: {format_price(target)}
- Stop Loss: {format_price(stop)}
- Risk/Reward Ratio: {rr_ratio:.1f}:1
- Estimated Risk: {risk_pct:.0f}% of entry
- Confidence: {confidence:.0%}
- Rationale: {rationale}

WRITE THE ARTICLE WITH THESE SECTIONS:

1. **H1 Title** — Catchy, keyword-rich, includes the trade direction. Example: "Bitcoin to $120K? This {side} Trade Has a {rr_ratio:.1f}:1 Risk/Reward"

2. **Trade Alert Box** (rendered as a styled box at top):
   - Direction: {side}
   - Entry: {format_price(entry)}
   - Target: {format_price(target)}
   - Stop Loss: {format_price(stop)}
   - Risk/Reward: {rr_ratio:.1f}:1
   - Confidence: {confidence:.0%}
   - Market: {question}

3. **Introduction** (150 words): Why this trade setup matters RIGHT NOW. What event, data release, or catalyst is coming.

4. **Why This Setup** (200 words): Explain the technical/practical rationale. What does the signal type ({sig_type}) tell us? Why is the market at this price?

5. **Catalyst & Timeline** (150 words): What event or date resolves this market? When does the trade need to work?

6. **Risk Management** (100 words): Where to exit if wrong ({format_price(stop)}), position sizing guidance (don't bet more than you can afford to lose), why the stop makes sense.

7. **What the Odds Tell Us** (100 words): Current probability of {format_price(current)} — what does that mean for this trade? Probability interpretation.

8. **Call to Action**: "Set up your free Polymarket account and take this trade → https://polymarket.com/?r={REFERRAL}"

9. **FAQ** (3 questions): Common concerns about this type of trade, answered concisely.

10. **Disclaimer**: Not financial advice. Prediction markets are speculative. Trade responsibly.

TONE: Confident, analytical, like a trading newsletter you'd pay for. Use specific numbers. No fluff.
LENGTH: 900-1100 words. Include the affiliate link naturally 2-3 times.
FORMAT: Use H2 headers. Include a styled trade alert box (HTML) near the top."""

    content = call_minimax(prompt)
    if not content:
        return None
    
    # Build HTML
    trade_alert_html = f"""
<div style="background:#161b22;border:2px solid #238636;border-radius:12px;padding:20px;margin:20px 0;font-family:monospace">
  <div style="color:#238636;font-weight:700;font-size:1.1em;margin-bottom:12px">📊 TRADE SETUP — {setup_label.upper()}</div>
  <table style="width:100%;color:#e6edf3;font-size:0.95em">
    <tr><td style="padding:4px 8px;color:#8b949e">Direction</td><td style="padding:4px 8px;font-weight:700;color:{'#238636' if side=='YES' else '#f85149'}">{side}</td></tr>
    <tr><td style="padding:4px 8px;color:#8b949e">Current Price</td><td style="padding:4px 8px">{format_price(current)}</td></tr>
    <tr><td style="padding:4px 8px;color:#8b949e">Entry Zone</td><td style="padding:4px 8px">{format_price(entry)}</td></tr>
    <tr><td style="padding:4px 8px;color:#8b949e">Target</td><td style="padding:4px 8px;color:#238636">{format_price(target)}</td></tr>
    <tr><td style="padding:4px 8px;color:#8b949e">Stop Loss</td><td style="padding:4px 8px;color:#f85149">{format_price(stop)}</td></tr>
    <tr><td style="padding:4px 8px;color:#8b949e">Risk/Reward</td><td style="padding:4px 8px">{rr_ratio:.1f}:1</td></tr>
    <tr><td style="padding:4px 8px;color:#8b949e">Confidence</td><td style="padding:4px 8px">{confidence:.0%}</td></tr>
  </table>
</div>"""

    # Embed signal_id for outcome tracking
    signal_id = signal.get("id", "")
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{question[:80]} — {side} Trade Setup | Predict221</title>
    <meta name="description" content="Actionable {side} trade setup on: {question}. Entry {format_price(entry)} → target {format_price(target)}. R/R {rr_ratio:.1f}:1. {confidence:.0%} confidence.">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.7; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #58a6ff; font-size: 1.7em; margin: 25px 0 10px; }}
        h2 {{ color: #f0883e; border-bottom: 1px solid #30363d; padding-bottom: 8px; margin: 28px 0 14px; }}
        .meta {{ background: #161b22; padding: 15px; border-radius: 8px; margin: 20px 0; border: 1px solid #30363d; font-size: 0.9em; color: #8b949e; }}
        .trade-box {{ background:#161b22;border:2px solid #238636;border-radius:12px;padding:20px;margin:20px 0;position:relative}}
        .trade-box h3 {{ color:#238636;margin:0 0 12px;font-size:1em;text-transform:uppercase;letter-spacing:0.05em}}
        .trade-row {{ display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #21262d}}
        .trade-row:last-child {{ border:none }}
        .trade-label {{ color:#8b949e }}
        .trade-val {{ font-weight:600 }}
        .trade-val.green {{ color:#238636 }}
        .trade-val.red {{ color:#f85149 }}
        .cta {{ background:#238636;color:white;padding:15px 30px;border-radius:8px;text-decoration:none;display:inline-block;margin:20px 0;font-weight:600;font-size:1.1em }}
        .cta:hover {{ background:#2ea043;color:white;text-decoration:none }}
        .disclaimer {{ background:#21262d;padding:15px;border-radius:8px;margin-top:40px;font-size:0.85em;color:#8b949e }}
        .signal-badge {{ display:inline-block;background:#238636;color:white;padding:2px 8px;border-radius:4px;font-size:0.75em;margin-left:8px;text-transform:uppercase }}
        a {{ color:#58a6ff }}
        p {{ margin:14px 0 }}
        .signal-id {{ position:absolute;top:10px;right:15px;font-size:0.7em;color:#6e7681 }}
        .outcome-banner {{ background:#21262d;border:1px solid #30363d;border-radius:10px;padding:20px;margin:25px 0;text-align:center }}
        .outcome-banner h3 {{ margin:0 0 10px;color:#e6edf3 }}
        .outcome-banner .result {{ font-size:2em;font-weight:700;margin:10px 0 }}
        .outcome-banner .result.win {{ color:#238636 }}
        .outcome-banner .result.loss {{ color:#f85149 }}
        .outcome-banner .result.pending {{ color:#f0883e }}
        .outcome-banner .result.push {{ color:#6e7681 }}
    </style>
</head>
<body>
    <p><a href="/">← Back to Predict221</a> <span style="color:#8b949e;margin-left:10px">|</span> <span style="margin-left:10px">{cat.capitalize()}</span> <span style="color:#6e7681;margin-left:10px">|</span> <span style="margin-left:10px;color:#6e7681">Signal #{signal_id}</span></p>
    
    <h1>{question}{'<span class="signal-badge">' + setup_label + '</span>' if setup_label != "Trade Setup" else ''}</h1>
    
    <div class="trade-box" id="trade-box">
        <span class="signal-id">Signal #{signal_id}</span>
        <h3>📊 TRADE SETUP — {setup_label.upper()}</h3>
        <div class="trade-row"><span class="trade-label">Direction</span><span class="trade-val {'green' if side=='YES' else 'red'}">{side}</span></div>
        <div class="trade-row"><span class="trade-label">Current Price</span><span class="trade-val">{format_price(current)}</span></div>
        <div class="trade-row"><span class="trade-label">Entry Zone</span><span class="trade-val">{format_price(entry)}</span></div>
        <div class="trade-row"><span class="trade-label">Target</span><span class="trade-val green">{format_price(target)}</span></div>
        <div class="trade-row"><span class="trade-label">Stop Loss</span><span class="trade-val red">{format_price(stop)}</span></div>
        <div class="trade-row"><span class="trade-label">Risk/Reward</span><span class="trade-val">{rr_ratio:.1f}:1</span></div>
        <div class="trade-row"><span class="trade-label">Confidence</span><span class="trade-val">{confidence:.0%}</span></div>
    </div>
    
    <div class="meta">
        <strong>{format_price(current)}</strong> current price · Signal confidence {confidence:.0%} · <a href="{market_url}">View on Polymarket ↗</a> · <a href="/record">View full record →</a>
    </div>
    
    {content}
    
    <a href="https://polymarket.com/?r={REFERRAL}&goto=market&slug={slug}" class="cta">Take This Trade on Polymarket →</a>
    
    <div class="disclaimer">
        <strong>Not financial advice.</strong> Prediction markets are speculative. This trade setup is for educational purposes only. Never bet more than you can afford to lose. 
        Track our full transparent record: <a href="/record">/record</a> · Affiliate: <a href="https://polymarket.com/?r={REFERRAL}">polymarket.com/?r={REFERRAL}</a>
    </div>
    
    <script>
    // Auto-fetch outcome for this signal and show banner if resolved
    fetch('/api/record')
      .then(r => r.json())
      .then(data => {{
        // Find this signal in the record results
        const signalId = {signal_id};
        if (!signalId) return;
        const resolved = data.recent ? data.recent.find(r => r.signal_id === signalId) : null;
        const pending = data.record ? data.record.pending : 0;
        const box = document.getElementById('trade-box');
        if (resolved && resolved.outcome) {{
          const cls = resolved.outcome === 'win' ? 'win' : resolved.outcome === 'loss' ? 'loss' : 'push';
          const banner = document.createElement('div');
          banner.className = 'outcome-banner';
          banner.innerHTML = '<h3>📜 Signal Result</h3><div class="result ' + cls + '">' + resolved.outcome.toUpperCase() + '</div>' +
            '<div style="color:#8b949e">Final price: ' + (resolved.final_price * 100).toFixed(1) + '% · ' +
            'ROI: <span style="color:' + (resolved.pnl > 0 ? '#238636' : '#f85149') + '">' + (resolved.pnl * 100 > 0 ? '+' : '') + (resolved.pnl * 100).toFixed(1) + '%</span></div>' +
            '<div style="margin-top:8px;font-size:0.85em;color:#6e7681">Resolved: ' + (resolved.resolved_at || '—').slice(0,10) + '</div>';
          box.after(banner);
        }}
      }})
      .catch(() => {{}});
    </script>
</body>
</html>"""
    
    filename = ARTICLES_DIR / f"setup-{slug}.html"
    filename.write_text(html)
    return str(filename)


def generate_market_article(market: dict) -> str | None:
    """Generate a market-overview article with trade context embedded"""
    try:
        raw_prices = market.get("outcomePrices", {})
        if isinstance(raw_prices, str):
            prices = json.loads(raw_prices)
        elif isinstance(raw_prices, list):
            # list format: ["0.65", "0.35"] = [yes, no]
            prices = {"yes": raw_prices[0] if len(raw_prices) > 0 else 0.5,
                      "no": raw_prices[1] if len(raw_prices) > 1 else 0.5}
        elif isinstance(raw_prices, dict):
            prices = raw_prices
        else:
            prices = {"yes": 0.5}
    except:
        prices = {"yes": 0.5}
    
    try:
        if isinstance(prices, dict):
            yes_price = float(prices.get("yes", 0.5) or 0.5)
        elif isinstance(prices, list) and len(prices) > 0:
            yes_price = float(prices[0])
        else:
            yes_price = 0.5
    except (ValueError, TypeError):
        yes_price = 0.5
    slug = market.get("slug", "")
    question = market.get("question", "")
    volume = float(market.get("volume", 0) or 0)
    liquidity = float(market.get("liquidity", 0) or 0)
    
    if volume < 5000 or yes_price < 0.02 or yes_price > 0.98:
        return None
    
    # Check for existing signal
    signal = get_trade_setup_for_market(slug, question)
    
    if signal:
        return generate_trade_setup_article(signal)
    
    # No signal — generate standard market analysis article with trade context
    cat = "general"
    q_lower = question.lower()
    if any(k in q_lower for k in ["bitcoin", "btc", "crypto", "eth", "sol"]):
        cat = "crypto"
    elif any(k in q_lower for k in ["trump", "biden", "election", "president", "vote"]):
        cat = "politics"
    elif any(k in q_lower for k in ["fed", "rate", "inflation", "gdp", "recession"]):
        cat = "economy"
    
    prob = yes_price
    
    # Framing
    if prob > 0.75:
        stance, framing = "strong favorite", "likely to happen"
        side_hint, target_hint = "YES", min(prob + 0.10, 0.95)
        stop_hint = prob - 0.08
    elif prob > 0.55:
        stance, framing = "slight favorite", "moderate chance"
        side_hint = "YES" if prob > 0.5 else "NO"
        target_hint = prob + 0.15
        stop_hint = prob - 0.12
    elif prob > 0.40:
        stance, framing = "coin flip", "too close to call"
        side_hint = "YES" if prob > 0.5 else "NO"
        target_hint = prob + 0.20
        stop_hint = prob - 0.15
    else:
        stance, framing = "underdog", "long shot"
        side_hint = "NO" if prob < 0.5 else "YES"
        target_hint = max(prob + 0.15, 0.90)
        stop_hint = prob - 0.08
    
    prompt = f"""Write a compelling, SEO-optimized trade-analysis article about the prediction market question: "{question}"

MARKET DATA:
- Current YES probability: {prob:.1%}
- Volume: ${volume:,.0f}
- Liquidity: ${liquidity:,.0f}
- Market stance: "{stance}" — market sees this as {framing}
- Suggested trade direction: {side_hint}

WRITE THIS ARTICLE:

1. **H1 Title**: Catchy, keyword-rich. Example: "Will [EVENT]? What the {prob:.0%} Odds Tell Traders"

2. **Market Snapshot Box** (styled HTML):
   - Current Odds: {prob:.1%}
   - Volume: ${volume:,.0f}
   - Stance: {stance}

3. **Introduction** (120 words): Why this market matters now.

4. **Reading the Odds** (150 words): What {prob:.1%} probability actually means in practical terms. Include a hypothetical trade setup example:
   - Entry: ~{prob:.1%}
   - Target if {side_hint}: ~{target_hint:.1%}
   - Stop: ~{stop_hint:.1%}
   (Note these are illustrative, not recommendations)

5. **Market Sentiment** (150 words): Why traders are positioned this way. What's driving the current price?

6. **Catalyst** (100 words): What event or date resolves this? When will we know?

7. **What Could Shift the Odds** (100 words): Factors that could move the price higher or lower.

8. **CTA**: Sign up on Polymarket → https://polymarket.com/?r={REFERRAL}

9. **FAQ**: 3 common questions.

10. **Disclaimer**: Not financial advice.

TONE: Informed, analytical, like a Bloomberg or trading desk briefing.
LENGTH: 800-1000 words. Include affiliate link 2-3 times naturally."""

    content = call_minimax(prompt)
    if not content:
        return None
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{question[:80]} — Prediction Market Analysis | Predict221</title>
    <meta name="description" content="{question[:155]}. Current odds: {prob:.1%} | ${volume:,.0f} traded. Analysis and trade perspectives on Polymarket.">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.7; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #58a6ff; font-size: 1.7em; margin: 25px 0 10px; }}
        h2 {{ color: #f0883e; border-bottom: 1px solid #30363d; padding-bottom: 8px; margin: 28px 0 14px; }}
        .market-box {{ background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;margin:20px 0 }}
        .prob {{ font-size:2.2em;font-weight:700;color:{'#238636' if prob>0.5 else '#f85149'} }}
        .cta {{ background:#238636;color:white;padding:15px 30px;border-radius:8px;text-decoration:none;display:inline-block;margin:20px 0;font-weight:600;font-size:1.05em }}
        .cta:hover {{ background:#2ea043;color:white;text-decoration:none }}
        .disclaimer {{ background:#21262d;padding:15px;border-radius:8px;margin-top:40px;font-size:0.85em;color:#8b949e }}
        a {{ color:#58a6ff }}
        .trade-hint {{ background:#1c2128;border-left:3px solid #f0883e;padding:12px 16px;margin:15px 0;font-size:0.92em }}
        .trade-hint strong {{ color:#f0883e }}
    </style>
</head>
<body>
    <p><a href="/">← Back to Predict221</a> <span style="color:#8b949e;margin-left:10px">|</span> <span style="margin-left:10px">{cat.capitalize()}</span></p>
    <h1>{question}</h1>
    
    <div class="market-box">
        <div class="prob">{prob:.1%} YES</div>
        <div style="color:#8b949e;margin-top:8px">${volume:,.0f} traded · {stance} · <a href="https://polymarket.com/market/{slug}">View on Polymarket ↗</a></div>
    </div>
    
    {content}
    
    <div class="trade-hint">
        <strong>📊 Illustrative Trade Context:</strong> If you're studying this market, typical trader setups at {prob:.0%} might look at entries near {prob:.0%}, targets around {target_hint:.0%}, and stops near {stop_hint:.0%}. These are educational examples only, not recommendations.
    </div>
    
    <a href="https://polymarket.com/?r={REFERRAL}&goto=market&slug={slug}" class="cta">Analyze This Market on Polymarket →</a>
    
    <div class="disclaimer">
        <strong>Not financial advice.</strong> Prediction markets are speculative. Trade responsibly. Affiliate: <a href="https://polymarket.com/?r={REFERRAL}">polymarket.com/?r={REFERRAL}</a>
    </div>
</body>
</html>"""
    
    filename = ARTICLES_DIR / f"{slug}.html"
    filename.write_text(html)
    return str(filename)


def generate_signals_dashboard_article() -> str | None:
    """Generate a top signals roundup article from DB"""
    if not SIGNALS_OK:
        return None
    try:
        init_db()
        setup_data = get_top_setup_articles(limit=5)
    except Exception as e:
        print(f"⚠️ Could not load signals: {e}")
        return None
    
    signals = setup_data.get("signals", [])
    arbitrage = setup_data.get("arbitrage", [])
    contrarian = setup_data.get("contrarian", [])
    record = setup_data.get("record", {})
    
    if not signals and not arbitrage and not contrarian:
        return None
    
    # Record stats for dashboard banner
    wins = record.get("wins", 0)
    losses = record.get("losses", 0)
    pushes = record.get("pushes", 0)
    pending = record.get("pending", 0)
    win_rate = record.get("win_rate", 0)
    wr_str = f"{int(win_rate * 100)}%" if record.get("total", 0) > 0 else "—"
    
    record_banner = f"""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;margin:20px 0;text-align:center">
        <div style="font-size:0.85em;color:#8b949e;margin-bottom:15px;text-transform:uppercase;letter-spacing:0.05em">Transparent Trading Record</div>
        <div style="display:flex;gap:20px;justify-content:center;flex-wrap:wrap">
            <div style="background:#21262d;border-radius:8px;padding:15px 25px;min-width:80px">
                <div style="font-size:1.8em;font-weight:700;color:#238636">{wins}</div>
                <div style="color:#8b949e;font-size:0.8em">Wins</div>
            </div>
            <div style="background:#21262d;border-radius:8px;padding:15px 25px;min-width:80px">
                <div style="font-size:1.8em;font-weight:700;color:#f85149">{losses}</div>
                <div style="color:#8b949e;font-size:0.8em">Losses</div>
            </div>
            <div style="background:#21262d;border-radius:8px;padding:15px 25px;min-width:80px">
                <div style="font-size:1.8em;font-weight:700;color:#6e7681">{pushes}</div>
                <div style="color:#8b949e;font-size:0.8em">Pushes</div>
            </div>
            <div style="background:#21262d;border-radius:8px;padding:15px 25px;min-width:80px">
                <div style="font-size:1.8em;font-weight:700;color:#f0883e">{pending}</div>
                <div style="color:#8b949e;font-size:0.8em">Pending</div>
            </div>
            <div style="background:#21262d;border-radius:8px;padding:15px 25px;min-width:80px">
                <div style="font-size:1.8em;font-weight:700;color:#58a6ff">{wr_str}</div>
                <div style="color:#8b949e;font-size:0.8em">Win Rate</div>
            </div>
        </div>
        <div style="margin-top:15px;font-size:0.85em;color:#6e7681">
            {wins + losses + pushes} resolved · <a href="/record" style="color:#58a6ff;">View full record →</a>
        </div>
    </div>"""
    
    # Build trade setups table HTML
    rows_html = ""
    for s in signals:
        sig_id = s.get("id", "")
        rows_html += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #21262d">{s.get('market_slug','')[:30]}<br><span style="font-size:0.75em;color:#6e7681">#{sig_id}</span></td>
            <td style="padding:8px;border-bottom:1px solid #21262d;color:{'#238636' if s.get('side')=='YES' else '#f85149'};font-weight:600">{s.get('side','N/A')}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d">{s.get('entry_price',0):.1%}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d;color:#238636">{s.get('target_price',0):.1%}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d;color:#f85149">{s.get('stop_loss',0):.1%}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d">{s.get('confidence',0):.0%}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d">{s.get('signal_type','')}</td>
        </tr>"""
    
    arb_rows = ""
    for a in arbitrage:
        arb_rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #21262d">{a.get('market_slug','')[:30]}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d;color:#f0883e">{a.get('direction','')}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d">{a.get('spread',0):.4f}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d;color:#238636">{a.get('net_edge',0):.4f}</td>
            <td style="padding:8px;border-bottom:1px solid #21262d">${a.get('volume_usd',0):,.0f}</td>
        </tr>"""
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Today's Top Trade Setups — Predict221</title>
    <meta name="description" content="Actionable Polymarket trade setups for {datetime.now().strftime('%B %d, %Y')}. Entry prices, targets, stop losses, and confidence ratings.">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.7; max-width: 900px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #58a6ff; font-size: 1.8em; margin: 25px 0 10px; }}
        h2 {{ color: #f0883e; border-bottom: 1px solid #30363d; padding-bottom: 8px; margin: 30px 0 15px; }}
        .timestamp {{ color:#8b949e;font-size:0.9em;margin-bottom:25px }}
        table {{ width:100%;border-collapse:collapse;font-size:0.9em }}
        th {{ text-align:left;padding:10px 8px;background:#161b22;color:#8b949e;text-transform:uppercase;font-size:0.75em;letter-spacing:0.05em }}
        td {{ padding:10px 8px }}
        tr:hover {{ background:#161b22 }}
        .section-box {{ background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;margin:20px 0;overflow-x:auto }}
        .cta {{ background:#238636;color:white;padding:15px 30px;border-radius:8px;text-decoration:none;display:inline-block;margin:20px 0;font-weight:600 }}
        .cta:hover {{ background:#2ea043;color:white;text-decoration:none }}
        .disclaimer {{ background:#21262d;padding:15px;border-radius:8px;margin-top:40px;font-size:0.85em;color:#8b949e }}
        a {{ color:#58a6ff }}
        .no-data {{ color:#8b949e;font-style:italic;padding:20px;text-align:center }}
    </style>
</head>
<body>
    <p><a href="/">← Back to Predict221</a></p>
    <h1>📊 Top Trade Setups — {datetime.now().strftime('%B %d, %Y')}</h1>
    <p class="timestamp">Auto-generated from Predict221 signals engine · {datetime.now().strftime('%H:%M UTC')}</p>
    
    {record_banner}
    
    <h2>🎯 Active Trade Setups</h2>
    <div class="section-box">
        <table>
            <thead>
                <tr>
                    <th>Market</th><th>Side</th><th>Entry</th><th>Target</th><th>Stop</th><th>Confidence</th><th>Type</th>
                </tr>
            </thead>
            <tbody>
                {rows_html or '<tr><td colspan="7" class="no-data">No active setups — check back soon</td></tr>'}
            </tbody>
        </table>
    </div>
    
    <h2>⚡ Arbitrage Opportunities</h2>
    <div class="section-box">
        <table>
            <thead>
                <tr>
                    <th>Market</th><th>Direction</th><th>Spread</th><th>Net Edge</th><th>Volume</th>
                </tr>
            </thead>
            <tbody>
                {arb_rows or '<tr><td colspan="5" class="no-data">No arbitrage opportunities detected right now</td></tr>'}
            </tbody>
        </table>
    </div>
    
    <h2>🔄 Contrarian Signals</h2>
    <div class="section-box">
        <table>
            <thead>
                <tr>
                    <th>Market</th><th>PM Odds</th><th>Baseline</th><th>Divergence</th><th>Direction</th><th>Confidence</th>
                </tr>
            </thead>
            <tbody>
                {"".join(f'''<tr>
                    <td style="padding:8px;border-bottom:1px solid #21262d">{c.get('market_slug','')[:30]}</td>
                    <td style="padding:8px;border-bottom:1px solid #21262d">{c.get('polymarket_odds',0):.0%}</td>
                    <td style="padding:8px;border-bottom:1px solid #21262d">{c.get('external_odds',0):.0%}</td>
                    <td style="padding:8px;border-bottom:1px solid #21262d;color:{'#238636' if c.get('divergence',0)>0 else '#f85149'}">{c.get('divergence',0):+.0%}</td>
                    <td style="padding:8px;border-bottom:1px solid #21262d;color:{'#238636' if c.get('direction')=='YES' else '#f85149'}">{c.get('direction','')}</td>
                    <td style="padding:8px;border-bottom:1px solid #21262d">{c.get('confidence',0):.0%}</td>
                </tr>''' for c in contrarian) or '<tr><td colspan="6" class="no-data">No contrarian signals — market in sync with baselines</td></tr>'}
            </tbody>
        </table>
    </div>
    
    <a href="https://polymarket.com/?r={REFERRAL}" class="cta">Take These Trades on Polymarket →</a>
    
    <div class="disclaimer">
        <strong>Not financial advice.</strong> These are algorithmic signals for educational purposes. Prediction markets are speculative. Always trade responsibly. <a href="https://polymarket.com/?r={REFERRAL}">Use our affiliate link →</a>
    </div>
</body>
</html>"""
    
    filename = ARTICLES_DIR / "top-setups.html"
    filename.write_text(html)
    return str(filename)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "generate"
    
    if cmd == "generate":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        print(f"🔍 Fetching markets...\n")
        
        # Always regenerate the signals dashboard
        dash = generate_signals_dashboard_article()
        if dash:
            print(f"  ✅ Dashboard: {dash}")
        
        # Try to generate trade setup articles first
        if SIGNALS_OK:
            try:
                init_db()
                signals = get_active_signals(limit=10)
                if signals:
                    print(f"📊 Generating {len(signals)} trade setup articles from signals DB...\n")
                    for i, sig in enumerate(signals, 1):
                        slug = sig.get("market_slug", "")
                        print(f"[{i}] SETUP: {sig.get('side')} {slug[:50]} @ {sig.get('entry_price', 0):.0%} → {sig.get('target_price', 0):.0%}")
                        path = generate_trade_setup_article(sig)
                        if path:
                            print(f"    ✅ {path}")
                        else:
                            print(f"    ❌ Failed")
                    count -= len(signals)
            except Exception as e:
                print(f"⚠️ Signals DB not ready: {e}")
        
        # Fill remaining slots with market overview articles
        if count > 0:
            markets = get_trending_markets(limit=count * 2)
            # Shuffle for variety, pick ones we haven't covered
            shuffle(markets)
            existing = {p.stem.replace("setup-","") for p in ARTICLES_DIR.glob("*.html")}
            new_markets = [m for m in markets if m.get("slug","") not in existing][:count]
            
            print(f"\n📰 Generating {len(new_markets)} market overview articles...\n")
            for i, m in enumerate(new_markets, 1):
                slug = m.get("slug", "")
                q = m.get("question", "")[:60]
                print(f"[{i}] {q}...")
                path = generate_market_article(m)
                if path:
                    print(f"    ✅ {path}")
                else:
                    print(f"    ⚠️ Skipped (low volume or no data)")
    
    elif cmd == "signals-only":
        if not SIGNALS_OK:
            print("❌ Signals DB not available")
            return
        init_db()
        dash = generate_signals_dashboard_article()
        if dash:
            print(f"✅ Dashboard: {dash}")
        signals = get_active_signals(limit=10)
        for s in signals:
            path = generate_trade_setup_article(s)
            print(f"  {'✅' if path else '❌'} {s.get('side')} {s.get('market_slug','')[:50]}")
    
    elif cmd == "status":
        articles = sorted(ARTICLES_DIR.glob("*.html"))
        print(f"Total articles: {len(articles)}\n")
        for a in articles:
            print(f"  {a.name} ({a.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
