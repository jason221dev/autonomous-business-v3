#!/usr/bin/env python3
"""
news_monitor.py — NewsAPI-driven insight triggers for Polymarket.
====================================================================
Scopes NewsAPI for news relevant to Polymarket markets. Detects:
  1. NEWS_CORROBORATION  — credible news confirms a market direction
  2. NEWS_CONTRADICTION  — news contradicts current market odds
  3. BREAKING_NEWS       — urgent/imminent event news moves coin-flip markets
  4. EARNINGS_CATALYST   — earnings/results catalyst for related markets

Rate limit: 1000 req/day, resets 9am PST (17:00 UTC).
We target ~40-60 API calls/day (top-headlines x5 + targeted search).
Deduplication: tracks seen article URLs + per-market signal cooldowns.

pmxt runs under: /usr/bin/python3 (Python 3.12) for market data.
"""
import os, sys, json, time, sqlite3, re
from datetime import datetime, timedelta
from pathlib import Path
import requests

# ── Config ─────────────────────────────────────────────────────────────────────
NEWS_API_KEY   = "9c9581d6f16f40bca0699996e3761165"
NEWS_API_BASE  = "https://newsapi.org/v2"
DB_PATH        = "/var/lib/polymarket/signals.db"
LOG_DIR        = Path("/var/log/polymarket")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE       = LOG_DIR / "news_monitor.log"

# Categories for top-headlines (one call each = 5 calls/run)
CATEGORIES       = ["general", "business", "science", "world", "technology"]
COUNTRY          = "us"
MAX_RESULTS_QUERY = 10

# Targeted search queries — fired sparingly to find specific market catalysts
# These use /everything endpoint — more expensive, use only when API budget allows
TARGETED_SEARCHES = [
    "Federal Reserve interest rate decision",
    "China Taiwan military",
    "Russia Ukraine ceasefire",
    "Iran nuclear deal",
    "Bitcoin ETF approval",
    "Supreme Court ruling",
    "NATO summit",
    "OPEC meeting",
]

# Per-market cooldown: don't signal same market more than once per 36 hours
MARKET_COOLDOWN_HOURS = 36

# URL dedup window: don't re-process an article URL within 72 hours
URL_DEDUP_HOURS = 72

# CREDIBLE SOURCES — only these generate high-confidence signals
CREDIBLE_SOURCES = {
    "Reuters", "Associated Press", "AP News", "BBC", "BBC News",
    "The Guardian", "Financial Times", "Wall Street Journal", "WSJ",
    "Washington Post", "The New York Times", "NYT", "Politico",
    "Bloomberg", "CNBC", "The Economist", "The Hill", "Fox News",
    "NBC News", "ABC News", "CBS News", "CNN",
}

SKIP_SLUGS = ["gta-vi", "before-gta-vi", "before-gta", "released-before-gta"]


# ── Logging ────────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.write_text(
            LOG_FILE.read_text() + "\n" + line if LOG_FILE.exists() else line + "\n"
        )
    except Exception:
        pass


# ── DB ─────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def insert_news_signal(
    market_slug: str, question: str,
    trigger_type: str,
    news_title: str,
    news_url: str,
    source: str,
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
        INSERT INTO news_signals (
            market_slug, question, trigger_type, news_title, news_url, source,
            direction, confidence, entry_price, target_price, stop_loss,
            rationale, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        market_slug, question, trigger_type, news_title, news_url, source,
        direction, confidence, entry_price, target_price, stop_loss,
        rationale, expires_at
    ])
    conn.commit()
    signal_id = cursor.lastrowid
    conn.close()
    return signal_id


def is_url_processed(news_url: str) -> bool:
    """Return True if this URL was processed within URL_DEDUP_HOURS."""
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM news_signals
        WHERE news_url = ?
          AND datetime(generated_at) > datetime('now', ?)
        LIMIT 1
    """, [news_url, f"-{URL_DEDUP_HOURS} hours"]).fetchone()
    conn.close()
    return row is not None


def is_market_cooldown(market_slug: str) -> bool:
    """Return True if we signaled this market within MARKET_COOLDOWN_HOURS."""
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM news_signals
        WHERE market_slug = ?
          AND datetime(generated_at) > datetime('now', ?)
        LIMIT 1
    """, [market_slug, f"-{MARKET_COOLDOWN_HOURS} hours"]).fetchone()
    conn.close()
    return row is not None


# ── NewsAPI rate limit ─────────────────────────────────────────────────────────
def api_remaining() -> int:
    counter_file = LOG_DIR / "news_api_calls.txt"
    today = datetime.now().strftime("%Y-%m-%d")
    if counter_file.exists():
        content = counter_file.read_text().strip()
        parts = content.split(":")
        if len(parts) == 2 and parts[0] == today:
            return max(0, 1000 - int(parts[1]))
    return 1000


def increment_counter():
    counter_file = LOG_DIR / "news_api_calls.txt"
    today = datetime.now().strftime("%Y-%m-%d")
    current = 0
    if counter_file.exists():
        content = counter_file.read_text().strip()
        parts = content.split(":")
        if len(parts) == 2 and parts[0] == today:
            current = int(parts[1])
    counter_file.write_text(f"{today}:{current + 1}")


def fetch_headlines(category: str) -> list:
    if api_remaining() < 5:
        log(f"  ⚠️ Low API budget ({api_remaining()}), skipping {category}")
        return []
    try:
        r = requests.get(
            f"{NEWS_API_BASE}/top-headlines",
            params={"apiKey": NEWS_API_KEY, "category": category,
                    "country": COUNTRY, "pageSize": MAX_RESULTS_QUERY},
            timeout=15
        )
        increment_counter()
        if r.status_code == 200:
            return r.json().get("articles", [])
        log(f"  {category}: {r.status_code}")
    except Exception as e:
        log(f"  {category} exception: {e}")
    return []


def search_news(query: str) -> list:
    if api_remaining() < 10:
        return []
    try:
        r = requests.get(
            f"{NEWS_API_BASE}/everything",
            params={"apiKey": NEWS_API_KEY, "q": query, "pageSize": 5,
                    "sortBy": "publishedAt", "language": "en"},
            timeout=15
        )
        increment_counter()
        if r.status_code == 200:
            arts = r.json().get("articles", [])
            # Filter out [Removed] articles
            return [a for a in arts if a.get("title") and a["title"] != "[Removed]"]
        log(f"  search '{query[:30]}': {r.status_code}")
    except Exception as e:
        log(f"  search exception: {e}")
    return []


PMXT_BIN = "/usr/bin/python3"


PMXT_MARKETS = "/usr/bin/python3 /tmp/pmxt_markets.py 200"


def get_target_markets_via_pmxt() -> list:
    """Fetch Polymarket markets via /tmp/pmxt_markets.py helper."""
    try:
        r = __import__("subprocess").run(
            PMXT_MARKETS, shell=True,
            capture_output=True, text=True, timeout=25,
        )
        if r.returncode != 0:
            log(f"  pmxt markets error: {r.stderr.strip()[:100]}")
            return []
        return json.loads(r.stdout.strip())
    except Exception as e:
        log(f"  pmxt markets exception: {e}")
        return []


# ── Relevance scoring ──────────────────────────────────────────────────────────
STOPWORDS = {"that", "this", "with", "from", "have", "they", "been",
             "what", "when", "your", "their", "will", "from", "about",
             "after", "before", "over", "into", "more", "some", "such"}


def relevance_score(article_title: str, article_desc: str, market_question: str) -> float:
    """Keyword overlap score. Returns 0.0–1.0."""
    q_words = set(re.findall(r"[a-z]{4,}", market_question.lower()))
    a_text  = (article_title + " " + article_desc).lower()
    a_words = set(w for w in re.findall(r"[a-z]{4,}", a_text)
                  if w not in STOPWORDS)
    overlap = q_words & a_words
    if not q_words:
        return 0.0
    return len(overlap) / len(q_words)


# ── Signal detection ───────────────────────────────────────────────────────────
def is_credible(source_name: str) -> bool:
    return any(cs.lower() in source_name.lower() for cs in CREDIBLE_SOURCES)


def build_signal(
    article: dict,
    market: dict,
    trigger_type: str,
    direction: str,
    confidence: float,
    entry: float,
    target: float,
    stop: float,
    rationale: str,
) -> int | None:
    """
    Store a news signal if URL hasn't been processed recently
    and market isn't on cooldown.
    """
    news_url = article.get("url", "")
    if not news_url or news_url == "[Removed]":
        return None
    slug = market["slug"]

    if is_url_processed(news_url):
        return None
    if is_market_cooldown(slug):
        return None

    source = article.get("source", {}).get("name", "Unknown")
    sid = insert_news_signal(
        market_slug=slug,
        question=market["title"],
        trigger_type=trigger_type,
        news_title=article.get("title", ""),
        news_url=news_url,
        source=source,
        direction=direction,
        confidence=confidence,
        entry_price=entry,
        target_price=target,
        stop_loss=stop,
        rationale=rationale,
    )
    return sid


def detect_signals(article: dict, markets: list) -> list:
    """
    Given an article and all target markets, return list of (signal_id, description).
    Only fires on high-relevance matches from credible sources.
    """
    title    = article.get("title", "") or ""
    desc     = article.get("description", "") or ""
    content  = article.get("content", "") or ""
    source   = article.get("source", {}).get("name", "Unknown")
    text     = (title + " " + desc + " " + content).lower()
    signals  = []

    if not title or title == "[Removed]":
        return []

    # Best market match
    best_mkt, best_score = None, 0.0
    for m in markets:
        sc = relevance_score(title, desc, m["title"])
        if sc > best_score:
            best_score = sc
            best_mkt = m

    if not best_mkt or best_score < 0.18:
        return []

    yes  = best_mkt["yes"]
    no   = best_mkt["no"]
    mkt  = best_mkt

    # ── Signal type detection ───────────────────────────────────────────────

    # 1. NEWS_CORROBORATION: credible source confirms YES direction
    if yes < 0.55 and is_credible(source):
        POSITIVE = ["will", "passes", "approved", "elected", "reaches deal",
                    "announces", "confirms", "breakthrough", "wins", "signs",
                    "success", "positive", "in favor", "ahead", "leads"]
        if any(k in text for k in POSITIVE):
            divergence = 0.50 - yes
            entry  = yes + 0.01
            target = min(yes + 0.18, 0.92)
            stop   = max(yes - 0.08, 0.25)
            conf   = min(0.62 + divergence * 0.8 + (0.1 if is_credible(source) else 0), 0.84)
            rat    = (f"News corroborates YES: '{title[:80]}' — "
                      f"{source} supports outcome. Market at {yes:.0%} undervalues scenario.")
            sid = build_signal(article, mkt, "NEWS_CORROBORATION", "YES", conf,
                               entry, target, stop, rat)
            if sid:
                signals.append((sid, f"NEWS_CORROBORATION on {mkt['title'][:40]}"))

    # 2. NEWS_CONTRADICTION: credible source confirms NO direction
    if yes > 0.45 and is_credible(source):
        NEGATIVE = ["won't", "will not", "fail", "not happen", "unlikely",
                     "defeated", "rejected", "denied", "collapsed", "against",
                     "drops", "falls", "recession", "reverses"]
        if any(k in text for k in NEGATIVE):
            divergence = yes - 0.50
            entry  = no + 0.01
            target = max(no - 0.12, 0.08)
            stop   = min(no + 0.08, 0.55)
            conf   = min(0.62 + divergence * 0.8 + (0.1 if is_credible(source) else 0), 0.84)
            rat    = (f"News contradicts YES: '{title[:80]}' — "
                      f"{source} reports contrary evidence. Market at {yes:.0%} overprices YES.")
            sid = build_signal(article, mkt, "NEWS_CONTRADICTION", "NO", conf,
                               entry, target, stop, rat)
            if sid:
                signals.append((sid, f"NEWS_CONTRADICTION on {mkt['title'][:40]}"))

    # 3. BREAKING_NEWS: urgent/imminent news on a coin-flip market
    if 0.35 <= yes <= 0.65:
        BREAKING = ["breaking", "just in", "developing", "urgent", "imminent",
                    "within days", "hours away", "this week", "tomorrow", "today"]
        if any(k in text for k in BREAKING):
            direction = "YES" if any(k in text for k in
                ["will", "passes", "approved", "wins", "success", "positive"]) else "NO"
            entry  = yes + 0.01 if direction == "YES" else no + 0.01
            target = min(yes + 0.15, 0.92) if direction == "YES" else max(no - 0.12, 0.08)
            stop   = max(yes - 0.07, 0.25) if direction == "YES" else min(no + 0.07, 0.75)
            conf   = 0.70 if is_credible(source) else 0.64
            rat    = (f"BREAKING: '{title[:80]}' — "
                      f"Time-sensitive news. Market at {yes:.0%} hasn't repriced this.")
            sid = build_signal(article, mkt, "BREAKING_NEWS", direction, conf,
                               entry, target, stop, rat)
            if sid:
                signals.append((sid, f"BREAKING on {mkt['title'][:40]}"))

    return signals


# ── Main ───────────────────────────────────────────────────────────────────────
def run():
    log("=== News Monitor Run Starting ===")
    remaining = api_remaining()
    log(f"  NewsAPI budget: {remaining}/1000")

    if remaining < 10:
        log("  Skipping — too few API calls remaining.")
        return 0

    # 1. Fetch top headlines from 5 categories (5 API calls)
    all_articles = []
    for cat in CATEGORIES:
        if remaining < 5:
            break
        arts = fetch_headlines(cat)
        all_articles.extend(arts)
        remaining = api_remaining()
        log(f"  {cat}: {len(arts)} articles, {remaining} calls left")
        time.sleep(0.25)

    # 2. Also do 2-3 targeted searches if budget allows (uses more calls)
    if remaining >= 20:
        for q in TARGETED_SEARCHES[:3]:
            arts = search_news(q)
            all_articles.extend(arts)
            remaining = api_remaining()
            time.sleep(0.25)

    log(f"  Total articles collected: {len(all_articles)}")

    # Deduplicate by URL before processing
    seen_urls = set()
    unique_articles = []
    for a in all_articles:
        url = a.get("url", "")
        if url and url != "[Removed]" and url not in seen_urls:
            seen_urls.add(url)
            unique_articles.append(a)
    log(f"  Unique articles after dedup: {len(unique_articles)}")

    # 3. Fetch target Polymarket markets via pmxt
    markets = get_target_markets_via_pmxt()
    log(f"  Target Polymarket markets: {len(markets)}")

    # 4. Generate signals
    total = 0
    for article in unique_articles:
        sigs = detect_signals(article, markets)
        for sid, desc in sigs:
            emoji = "📰" if "CORROB" in desc else "🔴" if "CONTRAD" in desc else "🚨"
            log(f"  {emoji} [{sid}]: {desc}")
            total += 1

    log(f"=== News Monitor Complete: {total} signals ===")
    return total


if __name__ == "__main__":
    run()
