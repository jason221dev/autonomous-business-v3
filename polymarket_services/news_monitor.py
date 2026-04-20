#!/usr/bin/env python3
"""
news_monitor.py — NewsAPI-driven insight triggers for Polymarket.
====================================================================
Scopes NewsAPI for news items relevant to Polymarket markets, then
cross-references against active markets to detect:
  1. NEWS_CORROBORATION  — credible news article confirms a market direction
  2. NEWS_CONTRADICTION  — news contradicts current market odds
  3. WHALE_NEWS          — large trader position opened after significant news
  4. CATALYST_NEWS       — breaking news about an upcoming event

Rate limit: 1000 req/day, resets 9am PST (17:00 UTC).
We target ~40–60 API calls/day (top-headlines x5 categories + search).
"""
import os, sys, json, time, sqlite3, re
from datetime import datetime, timedelta
from pathlib import Path
import requests

# ── Config ────────────────────────────────────────────────────────────────────
NEWS_API_KEY   = "9c9581d6f16f40bca0699996e3761165"
NEWS_API_BASE  = "https://newsapi.org/v2"
POLYMARKET_API = "https://gamma-api.polymarket.com"
DB_PATH        = "/var/lib/polymarket/signals.db"
LOG_DIR        = Path("/var/log/polymarket")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE       = LOG_DIR / "news_monitor.log"

# Categories to monitor (each triggers a separate call)
CATEGORIES = ["general", "business", "science", "world", "technology"]
COUNTRY    = "us"   # top-headlines country
MAX_RESULTS_PER_QUERY = 10

# Relevance keywords per category — maps to Polymarket market categories
CATEGORY_KEYWORDS = {
    "politics":   ["trump", "biden", "congress", "senate", "election", "president", "democrat", "republican", "vote", "gop", "supreme court", "impeach"],
    "economy":    ["fed", "federal reserve", "rate", "inflation", "cpi", "gdp", "recession", "treasury", "unemployment", " Jerome Powell"],
    "geopolitics":["russia", "ukraine", "china", "taiwan", "iran", "israel", "war", "nato", "putin", "zelensky", "military", "ceasefire", "sanctions", "middle east"],
    "crypto":      ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "bnb", "blockchain", "sec", "etf", "halving"],
    "sports":      ["nba", "nfl", "super bowl", "world cup", "olympics", "election"],
    "finance":     ["earnings", "stock", "market", "s&p", "nasdaq", "dow jones", "apple", "nvidia", "meta", "google", "amazon"],
}

# Markets to skip (no edge possible — special dates, meme markets)
SKIP_SLUGS = ["gta-vi", "before-gta-vi", "before-gta", "released-before-gta"]


# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.write_text(LOG_FILE.read_text() + line + "\n" if LOG_FILE.exists() else line + "\n")


# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def insert_news_signal(
    market_slug: str, question: str,
    trigger_type: str,       # NEWS_CORROBORATION | NEWS_CONTRADICTION | CATALYST_NEWS
    news_title: str,
    news_url: str,
    source: str,
    direction: str,         # YES | NO
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


def get_active_news_signals(limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM news_signals
        WHERE status = 'active'
          AND datetime(expires_at) > datetime('now')
        ORDER BY confidence DESC, generated_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_news_signal_processed(signal_id: int):
    conn = get_db()
    conn.execute("UPDATE news_signals SET status='processed' WHERE id=?", [signal_id])
    conn.commit()
    conn.close()


# ── NewsAPI helpers ───────────────────────────────────────────────────────────
def api_call_count_key() -> int:
    """Return approximate daily API call count from a simple counter file."""
    counter_file = LOG_DIR / "news_api_calls.txt"
    today = datetime.now().strftime("%Y-%m-%d")
    if counter_file.exists():
        content = counter_file.read_text().strip()
        parts = content.split(":")
        if len(parts) == 2 and parts[0] == today:
            return int(parts[1])
    return 0


def increment_api_counter():
    counter_file = LOG_DIR / "news_api_calls.txt"
    today = datetime.now().strftime("%Y-%m-%d")
    current = api_call_count_key()
    counter_file.write_text(f"{today}:{current + 1}")


def newsapi_remaining() -> int:
    """Return remaining API calls for today."""
    return max(0, 1000 - api_call_count_key())


def fetch_top_headlines(category: str = "general", page_size: int = 10) -> list:
    """Fetch top headlines for a category. Respects rate limit."""
    if newsapi_remaining() < 5:
        log("⚠️ NewsAPI daily limit approaching, skipping headlines.")
        return []

    url = f"{NEWS_API_BASE}/top-headlines"
    params = {
        "apiKey":   NEWS_API_KEY,
        "category": category,
        "country":  COUNTRY,
        "pageSize": page_size,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        increment_api_counter()
        if r.status_code == 200:
            return r.json().get("articles", [])
        elif r.status_code == 429:
            log(f"⚠️ NewsAPI rate limited (429). Remaining: {newsapi_remaining()}")
        else:
            log(f"  NewsAPI top-headlines error ({category}): {r.status_code} {r.text[:100]}")
    except Exception as e:
        log(f"  NewsAPI exception ({category}): {e}")
    return []


def search_news(query: str, page_size: int = 10, sort_by: str = "publishedAt") -> list:
    """Search news for a specific topic."""
    if newsapi_remaining() < 10:
        log("⚠️ NewsAPI daily limit approaching, skipping search.")
        return []

    url = f"{NEWS_API_BASE}/everything"
    params = {
        "apiKey":   NEWS_API_KEY,
        "q":        query,
        "pageSize": page_size,
        "sortBy":   sort_by,
        "language": "en",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        increment_api_counter()
        if r.status_code == 200:
            return r.json().get("articles", [])
        elif r.status_code == 429:
            log(f"⚠️ NewsAPI rate limited (429). Remaining: {newsapi_remaining()}")
        else:
            log(f"  NewsAPI search error ({query[:40]}): {r.status_code}")
    except Exception as e:
        log(f"  NewsAPI search exception: {e}")
    return []


# ── Market matching ───────────────────────────────────────────────────────────
def get_active_markets(limit: int = 50) -> list:
    """Fetch active Polymarket markets with meaningful volume."""
    try:
        resp = requests.get(
            f"{POLYMARKET_API}/markets",
            params={"limit": limit, "closed": "false"},
            timeout=15
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
                "slug":     slug,
                "question": m.get("question", ""),
                "yes":      yes_price,
                "no":       float(raw_prices[1]) if len(raw_prices) > 1 else 1.0 - yes_price,
                "volume":   vol,
                "url":      f"https://polymarket.com/market/{slug}",
                "end_date": m.get("endDate", ""),
            })
        return result
    except Exception as e:
        log(f"  Failed to fetch markets: {e}")
        return []


def keyword_match_score(article_text: str, market_question: str) -> float:
    """
    Simple keyword overlap score between article text and market question.
    Returns 0.0–1.0. Higher = more relevant.
    """
    q_words = set(re.findall(r"[a-z]{4,}", market_question.lower()))
    a_words = set(re.findall(r"[a-z]{4,}", article_text.lower()))
    a_words_lower = set(w for w in a_words if w not in {"that", "this", "with", "from", "have", "they", "will", "been", "what", "when", "your", "their"})
    overlap = q_words & a_words_lower
    if not q_words:
        return 0.0
    return len(overlap) / len(q_words)


def detect_trigger_type(
    article: dict, market: dict, all_markets: list
) -> tuple[str, str, float, float, float, float] | None:
    """
    Returns (trigger_type, direction, confidence, entry, target, stop) if a
    signal is warranted, else None.

    NEWS_CORROBORATION  — article directly confirms current market direction
    NEWS_CONTRADICTION  — article undermines current market odds
    CATALYST_NEWS       — breaking news about upcoming event changes odds
    """
    title   = article.get("title", "") or ""
    desc    = article.get("description", "") or ""
    content = article.get("content", "") or ""
    source  = article.get("source", {}).get("name", "Unknown")
    text    = f"{title} {desc} {content}".lower()
    question = market["question"]
    q_lower  = question.lower()
    yes = market["yes"]
    no  = market["no"]

    score = keyword_match_score(text, question)
    if score < 0.15:
        return None  # Not relevant to this market

    # ── Breaking / high-signal keywords ────────────────────────────────────
    BREAKING_KW  = ["breaking", "just in", "developing", "exclusive", "urgent"]
    NEGATIVE_KW  = ["won't", "will not", "fail", "not happen", "unlikely", "defeated", "rejected", "denied", "sanctions lifted", "deal collapsed"]
    POSITIVE_KW  = ["will", "will happen", "passes", "approved", "elected", "reaches deal", "announces", "confirms", "breakthrough"]
    DEADLINE_KW  = ["days away", "within days", "imminent", "deadline", "this week", "by friday", "hours away"]

    is_breaking = any(k in text for k in BREAKING_KW)
    has_deadline = any(k in text for k in DEADLINE_KW)

    # ── Contradiction: news says opposite of what market is pricing ─────────
    if yes > 0.60:
        if any(k in text for k in NEGATIVE_KW):
            divergence = yes - 0.50
            if divergence > 0.10:
                trigger = "NEWS_CONTRADICTION"
                direction = "NO"
                entry = no + 0.01
                target = max(no - 0.15, 0.05)
                stop   = min(no + 0.08, 0.50)
                confidence = min(0.60 + divergence * 0.5, 0.82)
                rationale = (
                    f"News contradicts market: '{title[:80]}' — "
                    f"market pricing {yes:.0%} YES but credible source ({source}) "
                    f"suggests outcome is less likely than odds imply."
                )
                return (trigger, direction, confidence, entry, target, stop, rationale)

    if yes < 0.40:
        if any(k in text for k in POSITIVE_KW):
            divergence = 0.50 - yes
            if divergence > 0.10:
                trigger = "NEWS_CORROBORATION"
                direction = "YES"
                entry = yes + 0.01
                target = min(yes + 0.18, 0.95)
                stop   = max(yes - 0.08, 0.20)
                confidence = min(0.60 + divergence * 0.5, 0.82)
                rationale = (
                    f"News corroborates upside: '{title[:80]}' — "
                    f"source ({source}) reports developments supporting YES. "
                    f"Market at {yes:.0%} underprices the scenario."
                )
                return (trigger, direction, confidence, entry, target, stop, rationale)

    # ── Catalyst: deadline approach or breaking news about known event ───────
    if has_deadline or is_breaking:
        if yes > 0.40 and yes < 0.60:
            # Market is in coin-flip range — breaking news can move it
            direction = "YES" if any(k in text for k in POSITIVE_KW) else "NO" if any(k in text for k in NEGATIVE_KW) else None
            if direction:
                if direction == "YES":
                    entry = yes + 0.01
                    target = min(yes + 0.12, 0.92)
                    stop   = max(yes - 0.06, 0.25)
                else:
                    entry = no + 0.01
                    target = max(no - 0.10, 0.08)
                    stop   = min(no + 0.06, 0.75)
                confidence = 0.68 if is_breaking else 0.62
                rationale = (
                    f"Catalyst: {title[:80]} — "
                    f"Breaking news shifts near-term probability. "
                    f"Market at {yes:.0%} hasn't fully repriced the {direction} scenario."
                )
                return (trigger if 'trigger' in dir() else "CATALYST_NEWS",
                        direction, confidence, entry, target, stop, rationale)

    return None


# ── Main run ──────────────────────────────────────────────────────────────────
def run():
    log("=== News Monitor Run Starting ===")
    remaining = newsapi_remaining()
    log(f"  NewsAPI remaining today: {remaining}")

    if remaining < 5:
        log("  Skipping run — too few API calls remaining.")
        return

    # 1. Fetch top headlines from all categories
    all_articles = []
    for cat in CATEGORIES:
        if remaining - 5 < 0:
            break
        arts = fetch_top_headlines(category=cat, page_size=MAX_RESULTS_PER_QUERY)
        all_articles.extend(arts)
        remaining = newsapi_remaining()
        log(f"  {cat}: got {len(arts)} articles, {remaining} API calls left")
        time.sleep(0.3)  # gentle rate limiting

    # 2. Fetch active Polymarket markets
    markets = get_active_markets(limit=50)
    log(f"  Active markets fetched: {len(markets)}")

    # 3. Cross-reference articles → markets
    signals_generated = 0
    for article in all_articles:
        title = article.get("title", "") or ""
        if not title or title == "[Removed]":
            continue

        # Find best matching market
        best_match = None
        best_score = 0.0
        for mkt in markets:
            score = keyword_match_score(f"{title} {article.get('description','')}", mkt["question"])
            if score > best_score:
                best_score = score
                best_match = mkt

        if not best_match or best_score < 0.15:
            continue

        # Check for whale/trader activity keywords
        trader_kw = ["large position", "whale", "institution", "bought", "sold", "accumulated",
                      "million shares", "million dollars", "hedge fund", "billionaire"]
        is_trader_news = any(k in (title + article.get("description","")).lower() for k in trader_kw)

        if is_trader_news:
            # Whale news — look for matching market
            mkt = best_match
            yes = mkt["yes"]
            direction = "YES" if yes < 0.50 else "NO"  # contrarian on large player moves
            entry = yes + 0.01 if direction == "YES" else mkt["no"] + 0.01
            target = min(yes + 0.12, 0.90) if direction == "YES" else max(mkt["no"] - 0.10, 0.10)
            stop   = max(yes - 0.08, 0.25) if direction == "YES" else min(mkt["no"] + 0.08, 0.75)
            confidence = 0.70
            rationale = (
                f"Whale Activity: '{title[:80]}' — "
                f"Significant capital movement reported by {article.get('source',{}).get('name','a source')}. "
                f"Smart money positioning detected on Polymarket at {yes:.0%}."
            )
            signal_id = insert_news_signal(
                market_slug=mkt["slug"], question=mkt["question"],
                trigger_type="WHALE_NEWS",
                news_title=title, news_url=article.get("url",""),
                source=article.get("source",{}).get("name","Unknown"),
                direction=direction, confidence=confidence,
                entry_price=entry, target_price=target, stop_loss=stop,
                rationale=rationale,
            )
            log(f"  🐋 WHALE signal [{signal_id}]: {mkt['question'][:50]}")
            signals_generated += 1
            continue

        # Standard news corroboration/contradiction check
        result = detect_trigger_type(article, best_match, markets)
        if result:
            trigger, direction, confidence, entry, target, stop, rationale = result
            mkt = best_match
            signal_id = insert_news_signal(
                market_slug=mkt["slug"], question=mkt["question"],
                trigger_type=trigger,
                news_title=title, news_url=article.get("url",""),
                source=article.get("source",{}).get("name","Unknown"),
                direction=direction, confidence=confidence,
                entry_price=entry, target_price=target, stop_loss=stop,
                rationale=rationale,
            )
            emoji = "📰" if "CORROBORATION" in trigger else "🔴" if "CONTRADICTION" in trigger else "⏰"
            log(f"  {emoji} {trigger} [{signal_id}]: {mkt['question'][:50]}")
            signals_generated += 1

    log(f"=== News Monitor Run Complete: {signals_generated} signals generated ===")
    return signals_generated


if __name__ == "__main__":
    run()
