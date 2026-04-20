"""Polymarket Trading Signals Database
Stores actionable trade setups with transparent win/loss tracking.
"""
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = "/var/lib/polymarket/signals.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    import os
    os.makedirs("/var/lib/polymarket", exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trading_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT NOT NULL,
            question TEXT,
            signal_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            current_price REAL,
            entry_price REAL,
            target_price REAL,
            stop_loss REAL,
            side TEXT NOT NULL,
            rationale TEXT,
            market_url TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            article_url TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contrarian_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT NOT NULL,
            question TEXT,
            polymarket_odds REAL,
            external_odds REAL,
            divergence REAL,
            direction TEXT NOT NULL,
            rationale TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            article_url TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS arbitrage_opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT NOT NULL,
            question TEXT,
            polymarket_price REAL,
            kalshi_price REAL,
            spread REAL,
            net_edge REAL,
            direction TEXT NOT NULL,
            volume_usd REAL,
            rationale TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            market_slug TEXT,
            signal_side TEXT,
            entry_price REAL,
            target_price REAL,
            stop_loss REAL,
            resolved_at TIMESTAMP,
            outcome TEXT,
            final_price REAL,
            pnl REAL,
            roi_pct REAL,
            notes TEXT,
            FOREIGN KEY(signal_id) REFERENCES trading_signals(id)
        )
    """)
    # ── News Signals (from NewsAPI corroboration/contradiction) ───────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT NOT NULL,
            question TEXT,
            trigger_type TEXT NOT NULL,
            news_title TEXT,
            news_url TEXT,
            source TEXT,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            entry_price REAL,
            target_price REAL,
            stop_loss REAL,
            rationale TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            article_url TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS whale_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT NOT NULL,
            question TEXT,
            trigger_type TEXT NOT NULL,
            trader_address TEXT,
            side TEXT,
            size_usd REAL,
            price REAL,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            entry_price REAL,
            target_price REAL,
            stop_loss REAL,
            rationale TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            article_url TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orderflow_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT NOT NULL,
            question TEXT,
            signal_type TEXT NOT NULL,
            spread REAL,
            imbalance_pct REAL,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            entry_price REAL,
            target_price REAL,
            stop_loss REAL,
            rationale TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            article_url TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS catalyst_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_slug TEXT NOT NULL,
            question TEXT,
            catalyst_type TEXT NOT NULL,
            event_name TEXT,
            event_date TEXT,
            days_until INTEGER,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            entry_price REAL,
            target_price REAL,
            stop_loss REAL,
            rationale TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            article_url TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON trading_signals(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_expires ON trading_signals(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perf_signal ON signal_performance(signal_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perf_outcome ON signal_performance(outcome)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_signals_status ON news_signals(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_whale_signals_status ON whale_signals(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orderflow_status ON orderflow_signals(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalyst_status ON catalyst_signals(status)")
    conn.commit()
    conn.close()

def insert_signal(signal_type: str, market_slug: str, question: str, side: str,
                  confidence: float, current_price: float, entry_price: float,
                  target_price: float, stop_loss: float, rationale: str,
                  market_url: str = "", expires_hours: int = 72) -> int:
    conn = get_db()
    expires_at = datetime.now() + timedelta(hours=expires_hours)
    cursor = conn.execute("""
        INSERT INTO trading_signals 
        (market_slug, question, signal_type, confidence, current_price, entry_price,
         target_price, stop_loss, side, rationale, market_url, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [market_slug, question, signal_type, confidence, current_price,
          entry_price, target_price, stop_loss, side, rationale, market_url, expires_at])
    conn.commit()
    signal_id = cursor.lastrowid
    conn.close()
    return signal_id

def insert_contrarian(market_slug: str, question: str, polymarket_odds: float,
                      external_odds: float, direction: str, rationale: str) -> int:
    divergence = abs(polymarket_odds - external_odds)
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO contrarian_signals 
        (market_slug, question, polymarket_odds, external_odds, divergence, direction, rationale)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [market_slug, question, polymarket_odds, external_odds, divergence, direction, rationale])
    conn.commit()
    signal_id = cursor.lastrowid
    conn.close()
    return signal_id

def insert_arbitrage(market_slug: str, question: str, polymarket_price: float,
                     kalshi_price: float, spread: float, direction: str,
                     volume_usd: float, rationale: str, expires_hours: int = 2) -> int:
    net_edge = spread - 0.02
    if net_edge <= 0:
        return -1
    expires_at = datetime.now() + timedelta(hours=expires_hours)
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO arbitrage_opportunities 
        (market_slug, question, polymarket_price, kalshi_price, spread, net_edge,
         direction, volume_usd, rationale, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [market_slug, question, polymarket_price, kalshi_price, spread, net_edge,
          direction, volume_usd, rationale, expires_at])
    conn.commit()
    signal_id = cursor.lastrowid
    conn.close()
    return signal_id

def get_active_signals(limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM trading_signals 
        WHERE status = 'active' AND datetime(expires_at) > datetime('now')
        ORDER BY confidence DESC, generated_at DESC LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_contrarian(limit: int = 5) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM contrarian_signals
        WHERE status = 'active'
        ORDER BY divergence DESC, generated_at DESC LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_arbitrage() -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM arbitrage_opportunities
        WHERE status = 'active' AND datetime(expires_at) > datetime('now')
        ORDER BY net_edge DESC, detected_at DESC LIMIT 5
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_news_signals(limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM news_signals
        WHERE status = 'active' AND datetime(expires_at) > datetime('now')
        ORDER BY confidence DESC, generated_at DESC LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_whale_signals(limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM whale_signals
        WHERE status = 'active' AND datetime(expires_at) > datetime('now')
        ORDER BY confidence DESC, generated_at DESC LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_orderflow_signals(limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM orderflow_signals
        WHERE status = 'active' AND datetime(expires_at) > datetime('now')
        ORDER BY confidence DESC, generated_at DESC LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_active_catalyst_signals(limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM catalyst_signals
        WHERE status = 'active' AND datetime(expires_at) > datetime('now')
        ORDER BY confidence DESC, generated_at DESC LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_expired():
    """Mark expired signals as inactive"""
    conn = get_db()
    conn.execute("UPDATE trading_signals SET status='expired' WHERE status='active' AND datetime(expires_at) <= datetime('now')")
    conn.execute("UPDATE arbitrage_opportunities SET status='expired' WHERE status='active' AND datetime(expires_at) <= datetime('now')")
    conn.commit()
    conn.close()

# ─── WIN/LOSS TRACKING ───────────────────────────────────────────────────────

def get_record() -> dict:
    """Get transparent win/loss/pending record for all resolved signals"""
    conn = get_db()
    
    # Count by outcome
    rows = conn.execute("""
        SELECT outcome, COUNT(*) as count, 
               SUM(pnl) as total_pnl, 
               AVG(roi_pct) as avg_roi
        FROM signal_performance 
        GROUP BY outcome
    """).fetchall()
    
    record = {"wins": 0, "losses": 0, "pushes": 0, "pending": 0, "total_pnl": 0.0, "avg_roi": 0.0}
    pnl_sum = 0.0
    roi_sum = 0.0
    roi_count = 0
    
    for row in rows:
        outcome = row["outcome"]
        count = row["count"] or 0
        if outcome == "win":
            record["wins"] = count
        elif outcome == "loss":
            record["losses"] = count
        elif outcome == "push":
            record["pushes"] = count
        if row["total_pnl"]:
            pnl_sum += row["total_pnl"]
        if row["avg_roi"]:
            roi_sum += row["avg_roi"]
            roi_count += 1
    
    record["total_pnl"] = pnl_sum
    record["avg_roi"] = roi_sum / roi_count if roi_count > 0 else 0.0
    
    # Pending count
    pending = conn.execute("""
        SELECT COUNT(*) FROM trading_signals 
        WHERE status = 'active' AND datetime(expires_at) > datetime('now')
    """).fetchone()[0]
    record["pending"] = pending
    
    total_decided = record["wins"] + record["losses"] + record["pushes"]
    record["total"] = total_decided + record["pending"]
    record["win_rate"] = record["wins"] / total_decided if total_decided > 0 else 0.0
    
    conn.close()
    return record


def record_outcome(signal_id: int, outcome: str, final_price: float, 
                   entry_price: float, target_price: float, stop_loss: float,
                   side: str, notes: str = "") -> int:
    """
    Record the outcome of a resolved signal.
    outcome: 'win', 'loss', 'push'
    final_price: the actual YES price at resolution (0.0 to 1.0)
    """
    # Calculate P&L and ROI
    if side == "YES":
        if outcome == "win":
            pnl = (final_price - entry_price) / entry_price  # e.g., 0.80 - 0.60 / 0.60
        elif outcome == "loss":
            pnl = (final_price - entry_price) / entry_price  # negative
        else:
            pnl = 0.0
    else:  # NO
        if outcome == "win":
            pnl = (entry_price - final_price) / entry_price
        elif outcome == "loss":
            pnl = (entry_price - final_price) / entry_price  # negative
        else:
            pnl = 0.0
    
    roi_pct = pnl * 100
    
    conn = get_db()
    
    # Check if already recorded
    existing = conn.execute(
        "SELECT id FROM signal_performance WHERE signal_id = ?", [signal_id]
    ).fetchone()
    
    if existing:
        conn.execute("""
            UPDATE signal_performance 
            SET outcome=?, final_price=?, pnl=?, roi_pct=?, resolved_at=?, notes=?
            WHERE signal_id=?
        """, [outcome, final_price, pnl, roi_pct, datetime.now(), notes, signal_id])
    else:
        cursor = conn.execute("""
            INSERT INTO signal_performance 
            (signal_id, signal_side, entry_price, target_price, stop_loss, 
             outcome, final_price, pnl, roi_pct, resolved_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [signal_id, side, entry_price, target_price, stop_loss,
              outcome, final_price, pnl, roi_pct, datetime.now(), notes])
    
    # Update signal status
    conn.execute("UPDATE trading_signals SET status='resolved' WHERE id=?", [signal_id])
    
    conn.commit()
    conn.close()
    return pnl


def resolve_all_expired():
    """
    Auto-resolve expired signals that haven't been resolved.
    Uses Polymarket API to get final prices for markets.
    Call this daily via cron.
    """
    import requests
    
    conn = get_db()
    expired = conn.execute("""
        SELECT * FROM trading_signals 
        WHERE status = 'active' AND datetime(expires_at) <= datetime('now')
    """).fetchall()
    conn.close()
    
    if not expired:
        return 0
    
    resolved = 0
    for sig in expired:
        slug = sig["market_slug"]
        side = sig["side"]
        entry = sig["entry_price"]
        target = sig["target_price"]
        stop = sig["stop_loss"]
        signal_id = sig["id"]
        
        # Fetch final price from Polymarket
        final_price = None
        try:
            resp = requests.get(
                f"https://gamma-api.polymarket.com/markets",
                params={"slug": slug}, timeout=10
            )
            if resp.ok:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    m = data[0]
                    prices = m.get("outcomePrices", [])
                    if isinstance(prices, str):
                        prices = [prices]
                    if prices:
                        final_price = float(prices[0])
        except Exception:
            pass
        
        if final_price is None:
            # Can't fetch — mark as pending still
            continue
        
        # Determine outcome
        if side == "YES":
            if final_price >= target:
                outcome = "win"
            elif final_price <= stop:
                outcome = "loss"
            else:
                outcome = "push"
        else:  # NO
            if final_price <= (1 - target):
                outcome = "win"
            elif final_price >= (1 - stop):
                outcome = "loss"
            else:
                outcome = "push"
        
        pnl = record_outcome(signal_id, outcome, final_price, entry, target, stop, side)
        resolved += 1
        print(f"  {'✅' if outcome=='win' else '❌' if outcome=='loss' else '➖'} [{signal_id}] {side} {slug[:40]}: final={final_price:.2%} → {outcome.upper()} (pnl={pnl:+.1%})")
    
    return resolved


def get_recent_results(limit: int = 20) -> list:
    """Get recent resolved signals with outcomes for display"""
    conn = get_db()
    rows = conn.execute("""
        SELECT sp.*, ts.question, ts.signal_type, ts.side as signal_side,
               ts.entry_price, ts.target_price, ts.stop_loss, ts.market_slug
        FROM signal_performance sp
        JOIN trading_signals ts ON ts.id = sp.signal_id
        WHERE sp.outcome IS NOT NULL
        ORDER BY sp.resolved_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_signals_for_articles(limit: int = 5) -> dict:
    """Get best signals from ALL tables formatted for article inclusion."""
    signals = get_active_signals(limit)
    arbitrage = get_active_arbitrage()
    contrarian = get_active_contrarian(limit=3)
    record = get_record()

    # Fetch new table signals
    news_signals = get_active_news_signals(limit)
    whale_signals = get_active_whale_signals(limit)
    orderflow_signals = get_active_orderflow_signals(limit)
    catalyst_signals = get_active_catalyst_signals(limit)

    return {
        "signals": signals,
        "arbitrage": arbitrage,
        "contrarian": contrarian,
        "news_signals": news_signals,
        "whale_signals": whale_signals,
        "orderflow_signals": orderflow_signals,
        "catalyst_signals": catalyst_signals,
        "record": record,
        "generated_at": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "resolve":
        print(f"[{datetime.now().isoformat()}] Running signal resolver...")
        init_db()
        resolved = resolve_all_expired()
        print(f"Resolved {resolved} expired signals.")
    else:
        print("Usage: python signals_db.py resolve")
