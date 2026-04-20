#!/usr/bin/env python3
"""Helper: fetches Polymarket markets via pmxt, prints JSON to stdout."""
import sys, json
from pmxt import Polymarket
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
try:
    poly = Polymarket()
    markets = poly.fetch_markets(params={"limit": limit})
    result = []
    for m in markets:
        combined = (m.title + " " + m.slug).lower()
        skip = ["gta-vi","before-gta","released-before-gta","grand-theft-auto"]
        if any(s in combined for s in skip):
            continue
        vol = float(m.volume or 0)
        if vol < 10000:
            continue
        yo = m.yes
        if not yo:
            continue
        yes_price = float(yo.price)
        if yes_price < 0.01 or yes_price > 0.99:
            continue
        result.append({
            "slug": m.slug, "title": m.title, "question": m.question or m.title,
            "yes": yes_price,
            "no": float(m.no.price) if m.no else 1.0 - yes_price,
            "volume": vol, "volume_24h": float(m.volume_24h or 0),
            "outcome_id": yo.outcome_id,
            "category": m.category or "unknown",
            "end_date": str(m.resolution_date) if m.resolution_date else "",
            "market_id": getattr(m, 'market_id', '') or '',
        })
    print(json.dumps(result))
except Exception as e:
    print(f"ERROR: {e}"); sys.exit(1)
