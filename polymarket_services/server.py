#!/usr/bin/env python3
"""
Polymarket Content Server - Trade setups with transparent win/loss record.
"""
import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request, redirect, send_from_directory

app = Flask(__name__)

REFERRAL = "Predict221"
REFERRAL_LINK = f"https://polymarket.com/?r={REFERRAL}"

sys.path.insert(0, '/opt/polymarket')
try:
    from signals_db import get_active_signals, get_active_contrarian, get_active_arbitrage, get_record, get_recent_results, init_db, get_top_signals_for_articles
    DB_OK = True
except Exception:
    DB_OK = False

# ─── TEMPLATE ─────────────────────────────────────────────────────────────────

HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Predict221 — Trade Setups & Insights</title>
    <meta name="description" content="Actionable trade setups from Polymarket prediction markets. Entry, target, stop, and transparent win/loss record.">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.6; }
        .container { max-width: 900px; margin: 0 auto; padding: 20px; }
        header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 40px 0; border-bottom: 1px solid #30363d; }
        header .container { display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 1.8em; font-weight: 700; color: #58a6ff; }
        .logo span { color: #f0883e; }
        nav a { color: #e6edf3; text-decoration: none; margin-left: 20px; font-size: 0.95em; }
        nav a:hover { color: #58a6ff; }
        .hero { text-align: center; padding: 60px 20px; background: linear-gradient(180deg, #161b22 0%, #0d1117 100%); }
        .hero h1 { font-size: 2.5em; margin-bottom: 15px; }
        .hero h1 span { color: #f0883e; }
        .hero p { color: #8b949e; font-size: 1.1em; max-width: 600px; margin: 0 auto 30px; }
        .cta-button { display: inline-block; background: #238636; color: white; padding: 15px 40px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 1.1em; transition: background 0.2s; }
        .cta-button:hover { background: #2ea043; text-decoration: none; color: white; }

        /* ── RECORD CARD ── */
        .record-section { padding: 40px 0; }
        .record-card { background: #161b22; border: 1px solid #30363d; border-radius: 16px; padding: 30px; margin-bottom: 20px; }
        .record-card h2 { color: #e6edf3; margin-bottom: 20px; font-size: 1.2em; }
        .record-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; text-align: center; }
        .record-stat { background: #21262d; border-radius: 10px; padding: 15px; }
        .record-stat .num { font-size: 2em; font-weight: 700; }
        .record-stat .label { color: #8b949e; font-size: 0.8em; text-transform: uppercase; margin-top: 4px; }
        .wins .num { color: #238636; }
        .losses .num { color: #f85149; }
        .pending .num { color: #f0883e; }
        .wr .num { color: #58a6ff; }
        .record-summary { text-align: center; margin-top: 15px; padding: 12px; background: #21262d; border-radius: 8px; color: #8b949e; font-size: 0.9em; }
        .record-summary strong { color: #e6edf3; }

        /* ── RECENT RESULTS ── */
        .results-table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 0.9em; }
        .results-table th { text-align: left; padding: 8px; color: #8b949e; text-transform: uppercase; font-size: 0.75em; letter-spacing: 0.05em; border-bottom: 1px solid #30363d; }
        .results-table td { padding: 10px 8px; border-bottom: 1px solid #21262d; }
        .results-table tr:hover { background: #1c2128; }
        .win-tag { background: #238636; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
        .loss-tag { background: #f85149; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
        .push-tag { background: #6e7681; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
        .pending-tag { background: #f0883e; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }

        /* ── SETUPS ── */
        .setups-section { padding: 40px 0; }
        .setup-card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; margin-bottom: 15px; transition: border-color 0.2s; }
        .setup-card:hover { border-color: #58a6ff; }
        .setup-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
        .setup-question { font-size: 1.05em; font-weight: 500; flex: 1; }
        .setup-side { font-size: 0.9em; font-weight: 700; padding: 4px 12px; border-radius: 6px; }
        .setup-side.yes { background: #238636; color: white; }
        .setup-side.no { background: #f85149; color: white; }
        .setup-meta { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
        .setup-badge { font-size: 0.85em; padding: 3px 10px; border-radius: 20px; background: #21262d; color: #8b949e; }
        .setup-prices { display: flex; gap: 15px; font-size: 0.9em; }
        .setup-prices span { color: #8b949e; }
        .setup-prices strong { color: #e6edf3; }
        .setup-conf { color: #58a6ff; font-weight: 600; }
        .setup-link { display: inline-block; margin-top: 10px; color: #58a6ff; text-decoration: none; font-size: 0.9em; }
        .setup-link:hover { text-decoration: underline; }

        /* ── ARTICLES ── */
        .articles-section { padding: 40px 0; }
        .article-card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 25px; margin-bottom: 20px; transition: border-color 0.2s; }
        .article-card:hover { border-color: #58a6ff; }
        .article-card h3 { font-size: 1.2em; margin-bottom: 10px; color: #e6edf3; }
        .article-card p { color: #8b949e; margin-bottom: 15px; }
        .article-card .meta { font-size: 0.85em; color: #6e7681; }

        footer { text-align: center; padding: 40px 0; color: #6e7681; font-size: 0.9em; border-top: 1px solid #30363d; margin-top: 50px; }
        .affiliate-disclaimer { background: #21262d; padding: 15px; border-radius: 8px; margin-top: 30px; font-size: 0.85em; color: #8b949e; text-align: center; }
        .no-data { color: #6e7681; font-style: italic; text-align: center; padding: 30px; }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <div class="logo">Predict<span>221</span></div>
            <nav>
                <a href="/">Home</a>
                <a href="/setups">Setups</a>
                <a href="/articles">Insights</a>
                <a href="/record">Record</a>
            </nav>
        </div>
    </header>

    <section class="hero">
        <div class="container">
            <h1>Trade <span>Prediction Markets</span> Like a Pro</h1>
            <p>Actionable setups with entry prices, targets, and stop losses — backed by a transparent win/loss record.</p>
            <a href="{{ referral_link }}" class="cta-button">Open Polymarket Account →</a>
        </div>
    </section>

    {% if record %}
    <section class="record-section">
        <div class="container">
            <div class="record-card">
                <h2>📊 Our Trading Record — Fully Transparent</h2>
                <div class="record-grid">
                    <div class="record-stat wins">
                        <div class="num">{{ record.wins }}</div>
                        <div class="label">Wins</div>
                    </div>
                    <div class="record-stat losses">
                        <div class="num">{{ record.losses }}</div>
                        <div class="label">Losses</div>
                    </div>
                    <div class="record-stat pending">
                        <div class="num">{{ record.pending }}</div>
                        <div class="label">Pending</div>
                    </div>
                    <div class="record-stat wr">
                        <div class="num">{% if record.total > 0 %}{{ (record.win_rate * 100)|int }}%{% else %}—{% endif %}</div>
                        <div class="label">Win Rate</div>
                    </div>
                </div>
                <div class="record-summary">
                    <strong>{{ record.wins + record.losses + record.pushes }}</strong> resolved ·
                    <strong>{{ record.pushes }}</strong> pushes ·
                    Avg R/R: <strong>{% if record.avg_roi != None %}{{ record.avg_roi|int }}%{% else %}—{% endif %}</strong>
                    · <a href="/record" style="color:#58a6ff;">Full history →</a>
                </div>
            </div>

            {% if recent_results %}
            <div class="record-card">
                <h2>📜 Recent Results</h2>
                <table class="results-table">
                    <thead>
                        <tr>
                            <th>Market</th><th>Side</th><th>Entry</th><th>Target</th><th>Result</th><th>Date</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for r in recent_results %}
                        <tr>
                            <td>{{ r.question[:45] if r.question else r.market_slug[:45] }}</td>
                            <td><span class="setup-side {{ r.signal_side|lower }}">{{ r.signal_side }}</span></td>
                            <td>{{ (r.entry_price * 100)|round(1) }}%</td>
                            <td>{{ (r.target_price * 100)|round(1) }}%</td>
                            <td>
                                {% if r.outcome == 'win' %}<span class="win-tag">WIN</span>
                                {% elif r.outcome == 'loss' %}<span class="loss-tag">LOSS</span>
                                {% elif r.outcome == 'push' %}<span class="push-tag">PUSH</span>
                                {% else %}<span class="pending-tag">PENDING</span>{% endif %}
                            </td>
                            <td style="color:#8b949e">{{ r.resolved_at[:10] if r.resolved_at else '—' }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% endif %}
        </div>
    </section>
    {% endif %}

    <section class="setups-section">
        <div class="container">
            <h2 class="section-title" style="font-size:1.3em;color:#e6edf3;border-left:4px solid #f0883e;padding-left:15px;margin-bottom:20px;">🎯 Active Trade Setups</h2>
            {% if setups %}
                {% for s in setups %}
                <div class="setup-card">
                    <div class="setup-header">
                        <div class="setup-question">{{ s.question or s.market_slug }}</div>
                        <span class="setup-side {% if s.side == 'YES' %}yes{% else %}no{% endif %}">{{ s.side }}</span>
                    </div>
                    <div class="setup-meta">
                        <span class="setup-conf">{{ (s.confidence * 100)|int }}% confidence</span>
                        <span class="setup-badge">{{ s.signal_type }}</span>
                        <span style="color:#8b949e;font-size:0.9em">{{ s.generated_at[:10] if s.generated_at else '' }}</span>
                    </div>
                    <div class="setup-prices">
                        <span>Entry: <strong>{{ (s.entry_price * 100)|round(1) }}%</strong></span>
                        <span>Target: <strong style="color:#238636">{{ (s.target_price * 100)|round(1) }}%</strong></span>
                        <span>Stop: <strong style="color:#f85149">{{ (s.stop_loss * 100)|round(1) }}%</strong></span>
                    </div>
                    <a href="/article/{{ s.market_slug }}" class="setup-link">View full setup →</a>
                </div>
                {% endfor %}
            {% else %}
                <p class="no-data">No active setups right now. Check back after the next signals run.</p>
            {% endif %}
            <div style="text-align:center;margin-top:20px">
                <a href="/setups" style="color:#58a6ff;font-size:0.95em;">View all setups →</a>
            </div>
        </div>
    </section>

    <section class="articles-section">
        <div class="container">
            <h2 class="section-title" style="font-size:1.3em;color:#e6edf3;border-left:4px solid #f0883e;padding-left:15px;margin-bottom:20px;">📊 Latest Insights</h2>
            {% for article in articles %}
            <div class="article-card">
                <h3>{{ article.title }}</h3>
                <p>{{ article.summary }}</p>
                <div class="meta">{{ article.date }} · {{ article.read_time }} min read</div>
            </div>
            {% endfor %}
        </div>
    </section>

    <footer>
        <div class="container">
            <p>Predict221 — Trade setups and analysis powered by Polymarket prediction markets.</p>
            <p style="margin-top:10px;">Affiliate: <a href="{{ referral_link }}" style="color:#58a6ff;">polymarket.com/?r=Predict221</a></p>
            <p style="margin-top:10px;">Not financial advice. Prediction markets are for entertainment only.</p>
        </div>
    </footer>
</body>
</html>
"""

RECORD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Record — Predict221</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.6; }
        .container { max-width: 900px; margin: 0 auto; padding: 20px; }
        h1 { color: #58a6ff; margin: 20px 0 10px; }
        .back { color: #58a6ff; text-decoration: none; font-size: 0.9em; }
        .back:hover { text-decoration: underline; }
        .record-card { background: #161b22; border: 1px solid #30363d; border-radius: 16px; padding: 30px; margin: 25px 0; }
        .record-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; text-align: center; }
        .record-stat { background: #21262d; border-radius: 10px; padding: 18px 10px; }
        .record-stat .num { font-size: 2.2em; font-weight: 700; }
        .record-stat .label { color: #8b949e; font-size: 0.75em; text-transform: uppercase; margin-top: 4px; }
        .wins .num { color: #238636; }
        .losses .num { color: #f85149; }
        .pushes .num { color: #6e7681; }
        .pending .num { color: #f0883e; }
        .wr .num { color: #58a6ff; }
        .pnl .num { color: #58a6ff; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 0.9em; }
        th { text-align: left; padding: 10px 8px; color: #8b949e; text-transform: uppercase; font-size: 0.75em; border-bottom: 1px solid #30363d; }
        td { padding: 12px 8px; border-bottom: 1px solid #21262d; }
        tr:hover { background: #161b22; }
        .win-tag { background: #238636; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
        .loss-tag { background: #f85149; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
        .push-tag { background: #6e7681; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
        .pending-tag { background: #f0883e; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
        .setup-side { padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
        .setup-side.yes { background: #238636; color: white; }
        .setup-side.no { background: #f85149; color: white; }
        .no-data { color: #6e7681; font-style: italic; text-align: center; padding: 40px; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back">← Back to Predict221</a>
        <h1>📊 Full Trading Record</h1>
        {% if record %}
        <div class="record-card">
            <div class="record-grid">
                <div class="record-stat wins"><div class="num">{{ record.wins }}</div><div class="label">Wins</div></div>
                <div class="record-stat losses"><div class="num">{{ record.losses }}</div><div class="label">Losses</div></div>
                <div class="record-stat pushes"><div class="num">{{ record.pushes }}</div><div class="label">Pushes</div></div>
                <div class="record-stat pending"><div class="num">{{ record.pending }}</div><div class="label">Pending</div></div>
                <div class="record-stat wr"><div class="num">{% if record.total > 0 %}{{ (record.win_rate * 100)|int }}%{% else %}—{% endif %}</div><div class="label">Win Rate</div></div>
            </div>
        </div>
        {% endif %}

        {% if all_results %}
        <div class="record-card">
            <h2 style="margin-bottom:15px;color:#e6edf3;">📜 Complete Signal History</h2>
            <table>
                <thead>
                    <tr>
                        <th>Date</th><th>Market</th><th>Type</th><th>Side</th><th>Entry</th><th>Target</th><th>Stop</th><th>Outcome</th><th>ROI</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in all_results %}
                    <tr>
                        <td style="color:#8b949e">{{ r.resolved_at[:10] if r.resolved_at else '—' }}</td>
                        <td>{{ r.question[:40] if r.question else r.market_slug[:40] }}</td>
                        <td style="color:#8b949e;font-size:0.85em">{{ r.signal_type }}</td>
                        <td><span class="setup-side {% if r.signal_side == 'YES' %}yes{% else %}no{% endif %}">{{ r.signal_side }}</span></td>
                        <td>{{ (r.entry_price * 100)|round(1) }}%</td>
                        <td style="color:#238636">{{ (r.target_price * 100)|round(1) }}%</td>
                        <td style="color:#f85149">{{ (r.stop_loss * 100)|round(1) }}%</td>
                        <td>
                            {% if r.outcome == 'win' %}<span class="win-tag">WIN</span>
                            {% elif r.outcome == 'loss' %}<span class="loss-tag">LOSS</span>
                            {% elif r.outcome == 'push' %}<span class="push-tag">PUSH</span>
                            {% else %}<span class="pending-tag">PENDING</span>{% endif %}
                        </td>
                        <td>{% if r.pnl != None %}<span style="color:{{ '#238636' if r.pnl > 0 else '#f85149' }}">{{ '+' if r.pnl > 0 else '' }}{{ (r.pnl * 100)|round(1) }}%</span>{% else %}—{% endif %}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
        <p class="no-data">No resolved signals yet. Pending setups will appear here once resolved.</p>
        {% endif %}
    </div>
</body>
</html>
"""

# ─── DATA FUNCTIONS ────────────────────────────────────────────────────────────

def get_sample_articles():
    return [
        {
            "title": "Bitcoin $120K Setup: Why 78% Odds Could Mean 3:1 Reward",
            "summary": "Breaking down the high-confidence BTC price prediction market — entry at 62%, target at 85%, stop at 48%.",
            "date": "April 20, 2026",
            "read_time": 5,
            "category": "Crypto"
        },
        {
            "title": "Fed Rate Decision: How to Play the 99% No-Cut Market",
            "summary": "With $117M in volume, this Fed decision trade has a 4:1 R/R setup. Here's the exact entry strategy.",
            "date": "April 19, 2026",
            "read_time": 4,
            "category": "Economy"
        },
    ]

ARTICLES_DIR = Path("/var/www/polymarket-site/articles")

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    if DB_OK:
        try:
            init_db()
            record = get_record()
            recent = get_recent_results(limit=10)
            setups = get_active_signals(limit=5)
        except Exception:
            record = None
            recent = []
            setups = []
    else:
        record = None
        recent = []
        setups = []

    articles = get_sample_articles()
    return render_template_string(
        HOME_TEMPLATE,
        record=record,
        recent_results=recent,
        setups=setups,
        articles=articles,
        referral_link=REFERRAL_LINK,
    )

@app.route("/record")
def record_page():
    if DB_OK:
        try:
            init_db()
            record = get_record()
            all_results = get_recent_results(limit=50)
        except Exception:
            record = None
            all_results = []
    else:
        record = None
        all_results = []

    return render_template_string(
        RECORD_TEMPLATE,
        record=record,
        all_results=all_results,
    )

@app.route("/api/record")
def api_record():
    if not DB_OK:
        return jsonify({"error": "DB not available"}), 500
    try:
        init_db()
        record = get_record()
        recent = get_recent_results(limit=20)
        return jsonify({"record": record, "recent": recent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/record/outcome", methods=["POST"])
def api_record_outcome():
    """Manually record an outcome for a signal"""
    if not DB_OK:
        return jsonify({"error": "DB not available"}), 500
    data = request.json
    required = ["signal_id", "outcome", "final_price", "entry_price", "target_price", "stop_loss", "side"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400
    
    from signals_db import record_outcome
    pnl = record_outcome(
        data["signal_id"], data["outcome"], data["final_price"],
        data["entry_price"], data["target_price"], data["stop_loss"],
        data["side"], data.get("notes", "")
    )
    return jsonify({"success": True, "pnl": pnl})

@app.route("/markets")
def markets():
    return redirect(REFERRAL_LINK)

@app.route("/about")
def about():
    return f"""
    <html><body style="background:#0d1117;color:#e6edf3;padding:50px;text-align:center;font-family:sans-serif;">
    <h1>About Predict221</h1>
    <p>We publish actionable trade setups from Polymarket prediction markets.</p>
    <p>Every setup includes entry, target, and stop loss — with a full transparent win/loss record.</p>
    <p>Use our affiliate link: <a href="{REFERRAL_LINK}" style="color:#58a6ff;">polymarket.com/?r=Predict221</a></p>
    <p style="margin-top:30px;"><a href="/" style="color:#58a6ff;">← Back to home</a></p>
    </body></html>
    """

@app.route("/article/<slug>")
def article_page(slug):
    for ext in ["", ".html"]:
        file_path = ARTICLES_DIR / f"{slug}{ext}"
        if file_path.exists():
            return send_from_directory(ARTICLES_DIR, file_path.name)
    for prefix in ["setup-", ""]:
        file_path = ARTICLES_DIR / f"{prefix}{slug}.html"
        if file_path.exists():
            return send_from_directory(ARTICLES_DIR, file_path.name)
    return f"<html><body style='background:#0d1117;color:#e6edf3;padding:50px;font-family:sans-serif'><h1>Article not found</h1><p><a href='/' style='color:#58a6ff;'>← Back</a></p></body></html>", 404

@app.route("/setups")
def setups():
    setups_file = ARTICLES_DIR / "top-setups.html"
    if setups_file.exists():
        return send_from_directory(ARTICLES_DIR, "top-setups.html")
    return f"<html><body style='background:#0d1117;color:#e6edf3;padding:50px;font-family:sans-serif'><h1>No setups yet</h1><p><a href='/' style='color:#58a6ff;'>← Back</a></p></body></html>", 404

@app.route("/articles")
def articles():
    files = sorted(ARTICLES_DIR.glob("*.html"))
    # Exclude the dashboard from the articles list
    article_files = [f for f in files if f.name != "top-setups.html"]
    links = "".join(
        f"<li><a href='/article/{f.stem}' style='color:#58a6ff;'>{f.stem[:80]}</a> ({f.stat().st_size//1024}KB)</li>"
        for f in article_files
    )
    return f"""
    <html><body style='background:#0d1117;color:#e6edf3;padding:40px;font-family:sans-serif'>
    <h1>📊 Insights & Analysis</h1>
    <p style='margin:15px 0'><a href='/' style='color:#58a6ff;'>← Back to home</a></p>
    <p>{len(article_files)} articles generated</p>
    <ul style='line-height:2'>{links or '<li style="color:#8b949e">No articles yet</li>'}</ul>
    </body></html>
    """

# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
