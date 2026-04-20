#!/usr/bin/env python3
"""
Polymarket Monitor - Fetches trending markets and formats for content creation.
"""
import requests
import json
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"
REFERRAL = "Predict221"

REFERRAL_LINK = f"https://polymarket.com/?r={REFERRAL}"

# Categories we want to target
CATEGORIES = {
    "crypto": ["bitcoin", "ethereum", "solana", "bnb", "ripple", "xrp", "cardano", "dogecoin", "crypto", "defi", "nft"],
    "politics": ["trump", "biden", "election", "president", "congress", "senate", "democrat", "republican", "harris"],
    "economy": ["fed", "rate", "inflation", "recession", "gdp", "unemployment", "stock", "market", "nasdaq", "s&p"],
    "tech": ["openai", "google", "meta", "apple", "microsoft", "ai", "gpt", "nvidia", "chip", "semiconductor"],
    "world": ["china", "russia", "ukraine", "israel", "iran", "nato", "war", "military"],
    "climate": ["climate", "temperature", "warming", "carbon", "emissions", "renewable"],
    "science": ["space", "mars", "moon", "nasa", "rocket"],
    "sports": ["nba", "nfl", "super bowl", "world cup", "olympics", "season", "championship"],
}

def search_markets(query, limit=5):
    """Search markets and return structured data"""
    try:
        resp = requests.get(f"{GAMMA_API}/public-search", params={"q": query}, timeout=15)
        if not resp.ok:
            return []
        data = resp.json()
        results = []
        for event in data.get("events", [])[:limit]:
            vol = float(event.get("volume", 0) or 0)
            if vol < 100:
                continue
            for m in event.get("markets", [])[:2]:
                try:
                    prices = json.loads(m.get("outcomePrices", "[]"))
                    outcomes = json.loads(m.get("outcomes", '["Yes","No"]'))
                    if len(prices) < 2:
                        continue
                    slug = event.get("slug", m.get("slug", ""))
                    results.append({
                        "question": m.get("question", ""),
                        "slug": slug,
                        "volume": vol,
                        "yes_prob": float(prices[0]) * 100,
                        "no_prob": float(prices[1]) * 100,
                        "outcomes": outcomes,
                        "url": f"https://polymarket.com/market/{slug}",
                        "referral": f"{REFERRAL_LINK}&goto=market&slug={slug}",
                    })
                except (json.JSONDecodeError, ValueError, IndexError):
                    continue
        return results
    except Exception as e:
        return []

def get_trending(limit=20):
    """Get trending markets across all major categories"""
    all_markets = {}
    
    for category, keywords in CATEGORIES.items():
        for kw in keywords[:2]:  # 2 keywords per category
            markets = search_markets(kw, limit=3)
            for m in markets:
                key = m["slug"]
                if key not in all_markets:
                    all_markets[key] = {**m, "category": category}
    
    # Sort by volume
    sorted_markets = sorted(all_markets.values(), key=lambda x: x["volume"], reverse=True)
    return sorted_markets[:limit]

def format_for_article(market):
    """Format market data for article prompts"""
    prob = market["yes_prob"]
    vol = market["volume"]
    
    if prob > 75:
        framing = "strong favorite"
        sentiment = "bullish"
    elif prob > 55:
        framing = "slight favorite"
        sentiment = "moderate"
    elif prob > 45:
        framing = "coin flip"
        sentiment = "neutral"
    elif prob > 25:
        framing = "underdog"
        sentiment = "surprising"
    else:
        framing = "long shot"
        sentiment = "unlikely"
    
    return {
        **market,
        "framing": framing,
        "sentiment": sentiment,
        "volume_fmt": f"${vol:,.0f}" if vol else "N/A",
        "prob_fmt": f"{prob:.1f}%",
    }

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "trending"
    
    if cmd == "trending":
        print(f"=== Top Trending Polymarket Markets === ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n")
        markets = get_trending(20)
        for i, m in enumerate((format_for_article(m) for m in markets), 1):
            print(f"{i:2}. [{m['prob_fmt']}] {m['question'][:65]}")
            print(f"     💰 {m['volume_fmt']} | {m['category']} | {m['framing']}")
            print(f"     🔗 {m['url']}")
            print()
    
    elif cmd == "category":
        cat = sys.argv[2] if len(sys.argv) > 2 else "crypto"
        print(f"=== {cat.upper()} Markets ===\n")
        keywords = CATEGORIES.get(cat, [cat])
        for kw in keywords[:5]:
            markets = search_markets(kw, 3)
            for m in markets[:1]:
                fm = format_for_article(m)
                print(f"[{fm['prob_fmt']}] {fm['question'][:60]}")
                print(f"  💰 {fm['volume_fmt']} | {fm['framing']}")
                print()
    
    elif cmd == "search":
        q = sys.argv[2] if len(sys.argv) > 2 else "bitcoin"
        print(f"=== Search: {q} ===\n")
        for m in search_markets(q, 10):
            fm = format_for_article(m)
            print(f"[{fm['prob_fmt']}] {fm['question'][:60]}")
            print(f"  💰 {fm['volume_fmt']} | {fm['framing']} | {fm['url']}")
            print()
