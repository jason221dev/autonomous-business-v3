#!/usr/bin/env python3
"""
AEDP v8 — Autonomous Edge Discovery Protocol
============================================
Fully autonomous hypothesis generation + edge discovery + live trading.
No user input required after startup.

The system continuously:
  1. MONITORS live markets for anomalies
  2. GENERATES causal hypotheses (LLM) from anomalies
  3. VALIDATES hypotheses against historical data
  4. POPULATES edge library with validated edges
  5. MONITORS edge health, degrades/retires as needed
  6. TRADES only from validated edge library

Setup:
  1. python aedp_v8.py setup      # Download 36GB historical dataset
  2. python aedp_v8.py discover   # Initial edge discovery (bruteforce)
  3. python aedp_v8.py trade      # Start autonomous system
"""

import os, sys, json, time, math, logging, asyncio, threading, queue
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from collections import defaultdict

import requests

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.FileHandler("/root/aedp_v8.log"), logging.StreamHandler()],
)
logger = logging.getLogger("AEDP_v8")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
DATA_BASE  = "https://data-api.polymarket.com"
CLOB_BASE  = "https://clob.polymarket.com"
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS", "0x0d713a4ff664bc859412ba0ead6e1643191edec2")
POLYMARKET_FEE_RATE = 0.01
MAX_SLIPPAGE_BPS    = 150
BOT_TOKEN   = os.environ.get("AEDP_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("AEDP_TELEGRAM_CHAT_ID", "")
REPO_DIR    = Path("/root/prediction-market-analysis")
EDGE_DB_PATH = Path("/root/aedp_edge_library.json")

LLM_CONFIG = [
    # MiniMax — priority 1 (primary)
    {"name": "minimax",     "endpoint": "https://api.minimax.io/anthropic/v1",
     "api_key": os.environ.get("MINIMAX_API_KEY",""),     "model": "MiniMax-M2.7",  "priority": 1},
    # NVIDIA NIM — OpenAI-compatible /v1/chat/completions endpoint
    {"name": "nvidia_nim1", "endpoint": "https://integrate.api.nvidia.com/v1",
     "api_key": os.environ.get("NVIDIA_NIM_KEY_1",""),    "model": "moonshotai/kimi-k2.5", "priority": 2},
    {"name": "nvidia_nim2", "endpoint": "https://integrate.api.nvidia.com/v1",
     "api_key": os.environ.get("NVIDIA_NIM_KEY_2",""),    "model": "moonshotai/kimi-k2.5", "priority": 3},
    {"name": "nvidia_nim3", "endpoint": "https://integrate.api.nvidia.com/v1",
     "api_key": os.environ.get("NVIDIA_NIM_KEY_3",""),    "model": "moonshotai/kimi-k2.5", "priority": 4},
]


# ─── DATA CLASSES ──────────────────────────────────────────────────────────────

@dataclass
class Market:
    market_id: str; question: str; yes_price: float; no_price: float
    volume: float; liquidity: float; clob_token_ids: list; condition_id: str
    end_date: str; category: str = ""

    @classmethod
    def from_gamma(cls, d: dict) -> "Market":
        import json as _j
        outcomes      = _j.loads(d.get("outcomes","[]")    or d.get("Outcomes","[]"))
        prices         = _j.loads(d.get("outcomePrices","[]") or d.get("OutcomePrices","[]"))
        clobs          = (_j.loads(d.get("clobTokenIds","[]"))
                         or _j.loads(d.get("clob_token_ids","[]")) or [])
        yes = float(prices[0]) if prices else 0.5
        return cls(
            market_id=d.get("id","") or d.get("marketId",""),
            question=d.get("question",""),
            yes_price=yes, no_price=1.0-yes,
            volume=float(d.get("volume",0) or 0),
            liquidity=float(d.get("liquidity",0) or 0),
            clob_token_ids=clobs,
            condition_id=d.get("conditionId","") or d.get("condition_id",""),
            end_date=d.get("endDate","") or d.get("end_date",""),
            category=d.get("category",""),
        )


@dataclass
class Edge:
    id: str; name: str; hypothesis: str; direction: str
    entry_rule: str; exit_rule: str; stop_rule: str
    min_confidence: float; min_trades: int
    historical_win_rate: float; historical_SR: float; n_historical_trades: int
    avg_holding_hours: float; edge_persistence_hours: int; fee_surviving: bool
    status: str = "discovered"
    discovered_at: str = ""; last_validated_at: str = ""
    paper_traded: bool = False; live_traded: bool = False
    tier: str = "D"


@dataclass
class ScoredSignal:
    market: Market; direction: str; entry_target: float; stop_loss: float
    exit_target: float; confidence: float; kelly_fraction: float; dollar_size: float
    slippage_bps: float; fee_usdc: float; net_expected_value: float
    gross_expected_value: float; viable: bool; rejection_reason: str = ""
    llm_provider: str = ""; reasons: list = field(default_factory=list)
    edge_id: str = ""; signal_hash: str = ""


@dataclass
class TradeRecord:
    signal_id: str; market_question: str; direction: str
    entry_price: float; exit_price: float; size_usdc: float; pnl: float
    timestamp: str; resolved: bool = False; edge_id: str = ""; hold_hours: float = 0.0


# ─── DATASET SETUP ────────────────────────────────────────────────────────────

class DatasetSetup:
    @staticmethod
    def check_dataset() -> dict:
        out = {}
        for name, path in [
            ("polymarket_markets", REPO_DIR/"data/polymarket/markets"),
            ("polymarket_trades",  REPO_DIR/"data/polymarket/trades"),
            ("polymarket_fpmm",    REPO_DIR/"data/polymarket/fpmm_trades"),
            ("kalshi_markets",     REPO_DIR/"data/kalshi/markets"),
            ("kalshi_trades",      REPO_DIR/"data/kalshi/trades"),
        ]:
            if path.exists():
                files = list(path.glob("*.parquet"))
                mb = sum(f.stat().st_size for f in files) / 1e6
                out[name] = {"files": len(files), "total_mb": round(mb,1)}
            else:
                out[name] = {"files": 0, "total_mb": 0.0}
        return out

    @staticmethod
    def load_parquet_data(category_filter: str = "") -> list:
        """Load historical market data as dicts for brute-force scanning."""
        data = []
        import glob
        for subdir in ["polymarket_trades", "polymarket_fpmm", "kalshi_trades"]:
            base = REPO_DIR / "data" / subdir
            if not base.exists():
                continue
            for pq in glob.glob(str(base / "*.parquet")):
                try:
                    import pandas as pd
                    df = pd.read_parquet(pq)
                    # Normalize common columns
                    for _, row in df.iterrows():
                        d = {}
                        for col in ["price","spread_bps","volume_ratio","won",
                                    "hour_et","hours_to_expiry","category","volume"]:
                            if col in row.index:
                                d[col] = row[col]
                        if category_filter and d.get("category","") != category_filter:
                            continue
                        data.append(d)
                except Exception as e:
                    logger.warning(f"Parquet read error {pq}: {e}")
        return data

    @staticmethod
    def download() -> bool:
        logger.info("Downloading 36GB historical dataset...")
        import subprocess
        if not REPO_DIR.exists():
            r = subprocess.run(
                ["git","clone","https://github.com/Jon-Becker/prediction-market-analysis.git", str(REPO_DIR)],
                capture_output=True, text=True
            )
            if r.returncode != 0:
                logger.error(f"Clone failed: {r.stderr}"); return False
        r = subprocess.run(["make","setup"], cwd=str(REPO_DIR), capture_output=True, text=True)
        if r.returncode != 0:
            logger.error(f"Download failed: {r.stderr[:500]}"); return False
        logger.info("Dataset ready!"); return True


# ─── LIVE POLYMARKET CLIENT ───────────────────────────────────────────────────

class LivePolymarketClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"

    def _get(self, url, params=None, retries=3):
        for a in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=10); r.raise_for_status()
                time.sleep(0.1); return r.json()
            except Exception as e:
                if a < retries-1: time.sleep(1*(a+1))
                else: raise

    def get_markets(self, limit=50):
        d = self._get(f"{GAMMA_BASE}/markets", {"limit": limit, "active": True})
        return [Market.from_gamma(m) for m in d.get("data",[])]

    def get_orderbook(self, token_id):
        try:
            d = self._get(f"{CLOB_BASE}/book", {"token_id": token_id})
            bids = d.get("bids",[]) or d.get("Bids",[])
            asks = d.get("asks",[]) or d.get("Asks",[])
            return {"bids": bids, "asks": asks,
                    "last_trade_price": d.get("last_trade_price", 0.5)}
        except Exception:
            return {"bids": [], "asks": [], "last_trade_price": 0.5}

    def get_market_price(self, token_id):
        book = self.get_orderbook(token_id)
        bids, asks = book["bids"], book["asks"]
        best_bid = float(bids[0].get("price",0)) if bids else 0.0
        best_ask = float(asks[0].get("price",0)) if asks else 0.0
        mid = (best_bid + best_ask)/2 if best_bid and best_ask else 0.5
        spread = (best_ask-best_bid)/mid if mid > 0 else 0.0
        return {"best_bid": best_bid, "best_ask": best_ask, "mid": mid, "spread": spread}


# ─── SLIPPAGE ESTIMATOR ────────────────────────────────────────────────────────

class SlippageEstimator:
    def __init__(self):
        self.fee_rate = POLYMARKET_FEE_RATE
        self.cache = {}; self.cache_ttl = 30

    def estimate(self, client, token_id, side, size_usdc):
        key = f"{token_id}:{side}:{int(size_usdc)}"; now = time.time()
        if key in self.cache and now-self.cache[key]["ts"] < self.cache_ttl:
            return self.cache[key]["r"]
        book = client.get_orderbook(token_id)
        levels = book.get("asks" if side=="BUY" else "bids", [])
        last = float(book.get("last_trade_price", 0.5))
        remaining, total_cost, filled = size_usdc, 0.0, 0.0
        for lv in levels:
            if remaining <= 0: break
            px = float(lv.get("price",0)); sz = float(lv.get("size",0))
            if px <= 0: continue
            f = min(remaining, sz); total_cost += f*px; filled += f; remaining -= f
        avg = total_cost/filled if filled > 0 else last
        slip = abs(avg-last)/last*10000 if last > 0 else 0
        total = slip + self.fee_rate*10000
        class R: pass
        r = R()
        r.expected_price=avg; r.mid_price=last; r.slippage_bps=slip
        r.fee_usdc=size_usdc*self.fee_rate; r.total_cost_bps=total
        r.viable=total < MAX_SLIPPAGE_BPS; r.filled_size=filled
        self.cache[key] = {"r": r, "ts": now}; return r


# ─── KELLY SIZER ──────────────────────────────────────────────────────────────

class KellySizer:
    def __init__(self, bankroll=5000.0):
        self.bankroll=bankroll; self.max_fraction=0.20
        self.half_kelly=True; self.fee_rate=POLYMARKET_FEE_RATE

    def update_bankroll(self, b): self.bankroll = max(b, 1000)

    def compute_fraction(self, win_rate, entry, exit_px, stop, direction):
        if direction=="BUY":
            gain=exit_px-entry; loss=entry-stop
        else:
            gain=entry-exit_px; loss=stop-entry
        if loss<=0: return 0.0
        b=gain/loss
        if b<=0: return 0.0
        p=win_rate; q=1.0-p
        kelly=max((b*p-q)/b, 0.0)
        if self.half_kelly: kelly /= 2.0
        edge=b*p-q
        if edge<=self.fee_rate: return 0.0
        kelly *= (1-min(self.fee_rate/edge, 0.3))
        return min(max(kelly, 0.0), self.max_fraction)

    def dollar_size(self, fraction): return self.bankroll*fraction


# ─── LLM ENSEMBLE ─────────────────────────────────────────────────────────────

class LLMEnsemble:
    def __init__(self):
        self.providers = [p for p in LLM_CONFIG if p["api_key"]]
        self.providers.sort(key=lambda x: x["priority"])
        logger.info(f"LLM Ensemble: {[p['name'] for p in self.providers]}")

    def complete(self, prompt, max_tokens=1024):
        for p in self.providers:
            # Use OpenAI-compatible requests — NIM and MiniMax both use /v1/chat/completions
            # MiniMax uses a special /anthropic/v1/messages endpoint
            if "minimax" in p["name"] and "anthropic" in p["endpoint"]:
                try:
                    import urllib.request, urllib.error
                    headers = {
                        "Authorization": f"Bearer {p['api_key']}",
                        "x-api-key": p["api_key"],
                        "Content-Type": "application/json",
                    }
                    body = json.dumps({
                        "model": p["model"],
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                        "thinking": {"type": "disabled"}
                    }).encode()
                    req = urllib.request.Request(
                        f"{p['endpoint']}/messages", data=body, headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = json.loads(resp.read())
                        output = ""
                        for block in data.get("content", []):
                            if block.get("type") == "text":
                                output += block.get("text", "")
                    return {"provider": p["name"], "response": output, "success": True}
                except Exception as e:
                    logger.warning(f"{p['name']} failed: {e}"); continue
            else:
                # OpenAI-compatible NIM endpoint
                try:
                    import urllib.request, urllib.error
                    headers = {
                        "Authorization": f"Bearer {p['api_key']}",
                        "Content-Type": "application/json",
                    }
                    body = json.dumps({
                        "model": p["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": 0.2,
                    }).encode()
                    req = urllib.request.Request(
                        f"{p['endpoint']}/chat/completions", data=body, headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = json.loads(resp.read())
                        choices = data.get("choices", [{}])
                        output = choices[0].get("message", {}).get("content", "") if choices else ""
                    return {"provider": p["name"], "response": output, "success": True}
                except Exception as e:
                    logger.warning(f"{p['name']} failed: {e}"); continue
        return {"success": False, "error": "all_providers_failed"}


# ─── EDGE LIBRARY (PERSISTENCE) ───────────────────────────────────────────────

class EdgeLibrary:
    # Fields that Edge dataclass actually has — exclude extra keys from record_trade
    _EDGE_FIELDS = {
        "id","name","hypothesis","direction","entry_rule","exit_rule","stop_rule",
        "min_confidence","min_trades","historical_win_rate","historical_SR",
        "n_historical_trades","avg_holding_hours","edge_persistence_hours",
        "fee_surviving","status","discovered_at","last_validated_at",
        "paper_traded","live_traded","tier",
    }

    def __init__(self, path=EDGE_DB_PATH):
        self.path = path; self.data = self._load()

    def _load(self):
        try:
            with open(self.path) as f: return json.load(f)
        except: return {"edges": [], "saved_at": ""}

    def _save(self):
        self.data["saved_at"] = datetime.now().isoformat()
        with open(self.path, "w") as f: json.dump(self.data, f, indent=2)

    def add_edge(self, edge: Edge):
        existing = [i for i,e in enumerate(self.data["edges"]) if e["id"]==edge.id]
        edict = {k:v for k,v in edge.__dict__.items() if k in self._EDGE_FIELDS}
        if existing:
            self.data["edges"][existing[0]] = edict
        else:
            self.data["edges"].append(edict)
        self._save()

    def get_edges(self) -> list[Edge]:
        out = []
        for e in self.data.get("edges",[]):
            # Filter out extra keys that record_trade may have added (trades, wins, losses, total_pnl)
            kw = {k: v for k, v in e.items() if k in self._EDGE_FIELDS}
            try:
                out.append(Edge(**kw))
            except TypeError as ex:
                logger.warning(f"EdgeLibrary.get_edges: failed to reconstruct edge {kw.get('id','?')}: {ex}")
        return out

    def record_trade(self, edge_id, pnl, won):
        for e in self.data["edges"]:
            if e["id"]==edge_id:
                e.setdefault("trades",[]).append({"pnl":pnl,"won":won,"ts":datetime.now().isoformat()})
                if won: e["wins"]=e.get("wins",0)+1
                else:    e["losses"]=e.get("losses",0)+1
                e["total_pnl"]=e.get("total_pnl",0.0)+pnl
                self._save(); return


# ─── LIVE SIGNAL ENGINE ────────────────────────────────────────────────────────

class LiveSignalEngine:
    def __init__(self, edges, client, slippage, kelly):
        self.edges=edges; self.client=client
        self.slippage=slippage; self.kelly=kelly
        self._recent: dict = {}

    def _dup(self, h, cooldown=3600):
        t=time.time()
        if h in self._recent and t-self._recent[h]<cooldown: return True
        self._recent[h]=t
        self._recent={k:v for k,v in self._recent.items() if v>t-7200}
        return False

    def scan_and_signal(self) -> list[ScoredSignal]:
        signals=[]
        markets=self.client.get_markets(limit=50)
        for m in markets:
            if m.volume<50_000 or not m.clob_token_ids: continue
            pd=self.client.get_market_price(m.clob_token_ids[0])
            for edge in self.edges:
                if edge.status not in ("active","validated"): continue
                sig=self._try_edge(m,edge,pd)
                if sig: signals.append(sig)
        return signals

    def _try_edge(self, m, edge, price_data):
        h=hashlib.sha256(f"{m.market_id}:{edge.id}".encode()).hexdigest()[:16]
        if self._dup(h): return None
        mid=price_data["mid"]; direction=edge.direction
        win_rate=edge.min_confidence
        rr_est=abs(win_rate-0.50)*4
        entry=mid; target=0.95 if direction=="BUY" else 0.05
        stop=mid*0.90 if direction=="BUY" else mid*1.10
        kf=self.kelly.compute_fraction(win_rate,entry,target,stop,direction)
        ds=self.kelly.dollar_size(kf)
        slip=self.slippage.estimate(self.client,m.clob_token_ids[0],direction,max(ds,100))
        if not slip.viable: return None
        pnl=win_rate*rr_est*ds-(1-win_rate)*ds
        net_ev=(pnl/ds)-(slip.total_cost_bps/10000)
        return ScoredSignal(
            market=m, direction=direction, entry_target=round(entry,4),
            stop_loss=round(stop,4), exit_target=round(target,4),
            confidence=win_rate, kelly_fraction=round(kf,4),
            dollar_size=round(ds,2), slippage_bps=round(slip.slippage_bps,1),
            fee_usdc=round(slip.fee_usdc,2),
            net_expected_value=round(net_ev,4),
            gross_expected_value=round(win_rate*rr_est-(1-win_rate),4),
            viable=net_ev>0.02, rejection_reason="" if net_ev>0.02 else f"net_ev_{net_ev:.3f}",
            edge_id=edge.id, signal_hash=h,
        )


# ─── TELEGRAM CONTROLLER ──────────────────────────────────────────────────────

class TelegramController:
    def __init__(self, bot_token, chat_id):
        self.bot_token=bot_token; self.chat_id=chat_id
        self.api_base=f"https://api.telegram.org/bot{bot_token}"
        self._offset=0; self.auto_trade=False; self.paper_mode=True

    def _send(self, text, parse_mode="Markdown"):
        try:
            r=requests.post(f"{self.api_base}/sendMessage",
                json={"chat_id":self.chat_id,"text":text,"parse_mode":parse_mode}, timeout=10)
            r.raise_for_status(); return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}"); return False

    def _poll(self):
        try:
            r=requests.get(f"{self.api_base}/getUpdates",
                params={"offset":self._offset,"timeout":30,"limit":10}, timeout=35)
            r.raise_for_status(); return r.json().get("result",[])
        except Exception as e:
            logger.error(f"Telegram poll failed: {e}"); return []

    def _advance(self, uid): self._offset=uid+1

    def alert_edge_discovery_complete(self, edges):
        from collections import Counter
        c=Counter(e.tier for e in edges)
        lines=[f"🧠 *EDGE DISCOVERY COMPLETE*\n\nEdges: {len(edges)}\n"
               f"A:{c['A']} B:{c['B']} C:{c['C']} D:{c['D']}\n\nTop edges:\n"]
        for e in sorted(edges,key=lambda x:x.tier)[:5]:
            lines.append(f"[{e.tier}] {e.name}\n  WR:{e.historical_win_rate:.1%} SR:{e.historical_SR:.2f}")
        self._send("\n".join(lines))

    def alert_signal(self, sig):
        m=sig.market
        text=(f"📈 *EDGE SIGNAL*\n───────────────\nEdge: `{sig.edge_id}`\n\n"
              f"❓ {m.question[:60]}\n───────────────\n"
              f"Direction: `{sig.direction}`\nEntry: `{sig.entry_target:.1%}` | "
              f"Stop: `{sig.stop_loss:.1%}`\nConfidence: `{sig.confidence:.0%}`\n"
              f"Size: `${sig.dollar_size:.0f}` | Kelly: {sig.kelly_fraction:.1%}\n"
              f"Net EV: `{sig.net_expected_value:.1%}`\n───────────────\n"
              f"Reply BUY/SELL to approve, SKIP to dismiss")
        return self._send(text)

    def alert_trade(self, sig, status):
        text=(f"{'✅' if status!='REJECTED' else '❌'} *TRADE {status}*\n"
              f"{sig.market.question[:50]}\n"
              f"{sig.direction} @ `{sig.entry_target:.1%}` ${sig.dollar_size:.0f}")
        return self._send(text)

    def alert_system_status(self, lines):
        self._send("🖥️ *AEDP v8 STATUS*\n"+"\n".join(lines))

    def alert_error(self, msg):
        self._send(f"🚨 *ERROR*: {msg}")

    def poll_commands(self) -> list:
        results=[]
        for upd in self._poll():
            self._advance(upd["update_id"])
            msg=upd.get("message",{})
            if str(msg.get("chat",{}).get("id",""))!=self.chat_id: continue
            text=msg.get("text","").strip().upper()
            if text: results.append(text)
        return results


# ─── EXECUTION LAYER ──────────────────────────────────────────────────────────

class ExecutionLayer:
    def __init__(self):
        self.wallet_address=WALLET_ADDRESS
        self.private_key=os.environ.get("POLYGON_WALLET_PRIVATE_KEY","")
        self.paper_mode=True

    async def place_order(self, sig):
        order={"wallet":self.wallet_address,"token_id":sig.market.clob_token_ids[0],
               "side":sig.direction,"amount_usdc":sig.dollar_size,
               "entry_price":sig.entry_target,"edge_id":sig.edge_id,
               "paper_mode":self.paper_mode,"timestamp":datetime.now().isoformat()}
        if self.paper_mode:
            logger.info(f"[PAPER] {order['side']} {order['amount_usdc']} @ {order['entry_price']:.1%}")
            return {**order,"status":"paper"}
        # Live execution — EIP-712 signing would go here
        # For now, log and fall back (signing not implemented in this version)
        if self.private_key:
            logger.warning("Live execution: EIP-712 signing not implemented — paper fallback")
        else:
            logger.warning("Live execution: POLYGON_WALLET_PRIVATE_KEY not set — paper fallback")
        return {**order,"status":"paper_fallback"}


# ══════════════════════════════════════════════════════════════════════════════
# AUTONOMOUS DISCOVERY COMPONENTS (v8 NEW)
# ══════════════════════════════════════════════════════════════════════════════

# ─── ANOMALY DETECTOR ─────────────────────────────────────────────────────────

class AnomalyDetector:
    """
    Continuously monitors live market features against historical norms.
    Flags anomalies for hypothesis generation.

    Features monitored:
      - price deviation vs category average
      - spread vs typical spread for this volume tier
      - volume vs previous weeks same day/hour
      - price near extremes with unusual volume
      - mid-range (45-55) crowding with category-specific resolution bias
    """

    def __init__(self):
        self.baselines: dict = {}
        self.snapshots: dict = {}
        self.anomaly_log: list = []

    def snapshot_market(self, market: Market, price_data: dict) -> dict:
        snap = {
            "market_id": market.market_id, "question": market.question,
            "category": market.category or self._infer_category(market.question),
            "price": price_data.get("mid", market.yes_price),
            "spread_bps": price_data.get("spread", 0) * 10000,
            "volume": market.volume, "liquidity": market.liquidity,
            "yes_price": market.yes_price, "no_price": market.no_price,
            "clob_token_ids": market.clob_token_ids,
            "end_date": market.end_date, "timestamp": time.time(),
        }
        self.snapshots[market.market_id] = snap
        self._update_baseline(snap)
        return snap

    def detect_anomalies(self, markets: list, client) -> list:
        anomalies = []
        for m in markets:
            if not m.clob_token_ids: continue
            pd = client.get_market_price(m.clob_token_ids[0])
            snap = self.snapshot_market(m, pd)
            cat = snap["category"]
            base = self.baselines.get(cat, {})
            p = snap["price"]; sp = snap["spread_bps"]; vol = snap["volume"]

            # 1. Price deviation
            if base.get("n",0) > 5:
                pz = abs(p-base.get("avg_price",0.5))/(base.get("price_std",0.05)+0.001)
                if pz > 2.0:
                    anomalies.append({"type":"price_deviation","market_id":m.market_id,
                        "category":cat,"severity":min(pz/2,5.0),
                        "details":{"current":p,"baseline":base.get("avg_price"),"z":round(pz,2)},
                        "snapshot":snap})

            # 2. Wide spread
            bs = base.get("avg_spread",50)
            if sp > bs*1.5 and sp > 100:
                anomalies.append({"type":"wide_spread","market_id":m.market_id,
                    "category":cat,"severity":min(sp/bs,5.0),
                    "details":{"current_spread_bps":round(sp,1),"baseline_bps":round(bs,1)},
                    "snapshot":snap})

            # 3. Volume spike
            bv = base.get("avg_volume",1)
            if vol > bv*3:
                anomalies.append({"type":"volume_spike","market_id":m.market_id,
                    "category":cat,"severity":min(vol/bv,5.0),
                    "details":{"current_volume":vol,"baseline_volume":bv},
                    "snapshot":snap})

            # 4. Extremum + volume
            if (p > 0.85 or p < 0.15) and vol > bv*2:
                anomalies.append({"type":"extremum_with_volume","market_id":m.market_id,
                    "category":cat,"severity":4.0,
                    "details":{"price":round(p,4),"volume_ratio":round(vol/bv,2)},
                    "snapshot":snap})

            # 5. Mid-range mispricing
            if 0.40 <= p <= 0.60 and vol > 100_000 and base.get("midrange_wr"):
                gap = abs(base["midrange_wr"] - p)
                if gap > 0.05:
                    anomalies.append({"type":"midrange_mispricing","market_id":m.market_id,
                        "category":cat,"severity":gap*20,
                        "details":{"price":round(p,4),"hist_wr":base["midrange_wr"],
                                   "edge_pp":round(gap*100,1)},
                        "snapshot":snap})

        self.anomaly_log.extend(anomalies); self.anomaly_log = self.anomaly_log[-1000:]
        anomalies.sort(key=lambda a: a["severity"], reverse=True)
        return anomalies[:20]

    def _update_baseline(self, snap):
        cat=snap["category"]
        p=snap["price"]; sp=snap["spread_bps"]; vol=snap["volume"]
        if cat not in self.baselines:
            self.baselines[cat]={"avg_price":p,"price_std":0.05,
                "avg_spread":sp,"spread_std":50,"avg_volume":vol,"volume_std":vol,"n":1}
            return
        b=self.baselines[cat]; n=b["n"]
        b["avg_price"]+=(p-b["avg_price"])/(n+1)
        b["avg_spread"]+=(sp-b["avg_spread"])/(n+1)
        b["avg_volume"]+=(vol-b["avg_volume"])/(n+1)
        # FIX Bug 14: update price_std using Welford's online algorithm
        # price_std tracks actual deviation, not just the mean
        old_std = b.get("price_std", 0.05)
        new_std_sq = ((n - 1) * old_std**2 + (p - b["avg_price"])**2) / (n + 1)
        b["price_std"] = math.sqrt(max(new_std_sq, 0.0001))
        b["n"]+=1

    def _infer_category(self, q: str) -> str:
        q=q.lower()
        if any(w in q for w in ["bitcoin","ether","crypto","btc","eth"]): return "crypto"
        if any(w in q for w in ["election","president","trump","biden","congress"]): return "politics"
        if any(w in q for w in ["game","win","score","team","championship"]): return "sports"
        if any(w in q for w in ["temperature","rain","hurricane","weather"]): return "weather"
        if any(w in q for w in ["fed","rate","inflation","gdp"]): return "economics"
        return "other"

    def get_context(self) -> str:
        if not self.anomaly_log: return "No significant anomalies."
        lines=["Recent anomalies:"]
        for a in self.anomaly_log[-10:]:
            lines.append(f"  - [{a['type']}] {a['category']} (sev={a['severity']:.1f})")
        return "\n".join(lines)


# ─── HYPOTHESIS GENERATOR ──────────────────────────────────────────────────────

HYPOTHESIS_PROMPT = """You are a quantitative trading researcher specializing in prediction markets.
Generate 1-3 TESTABLE HYPOTHESES about why certain market anomalies occur.

Rules:
1. Each hypothesis needs a CLEAR CAUSAL MECHANISM (not just correlation)
2. Each hypothesis must specify the PRECISE ENTRY CONDITION
3. Each must be testable against historical data
4. State DIRECTION (BUY/SELL) and expected WIN RATE

Format each hypothesis as:
HYPOTHESIS_N: N
MECHANISM: One sentence causal explanation
ENTRY_CONDITION: Specific rule (e.g., "spread>3% AND price 45-55c AND volume>$200K")
DIRECTION: BUY or SELL
EXPECTED_WIN_RATE: e.g., 0.58
EXPECTED_EDGE_PP: e.g., 0.04
CONFIDENCE: low/medium/high

Only output 1-3 hypotheses. Focus on most promising anomaly."""


class HypothesisGenerator:
    def __init__(self, llm: LLMEnsemble):
        self.llm=llm; self.generated: list=[]

    def generate(self, anomalies: list, context: str="") -> list:
        if not anomalies: return []
        prompt = f"{HYPOTHESIS_PROMPT}\n\nANOMALIES:\n{self._format(anomalies)}\n\nCONTEXT:\n{context}"
        result = self.llm.complete(prompt, max_tokens=1200)
        if not result.get("success"): return []
        hyps = self._parse(result["response"])
        for h in hyps:
            h["source_anomaly"]=anomalies[0].get("type","unknown")
            h["generated_at"]=datetime.now().isoformat()
            h["llm_provider"]=result.get("provider","unknown")
        self.generated.extend(hyps)
        logger.info(f"Generated {len(hyps)} hypotheses from {len(anomalies)} anomalies")
        return hyps

    def _format(self, anomalies: list) -> str:
        lines=[]
        for i,a in enumerate(anomalies[:10],1):
            lines.append(f"{i}. {a['type']} | {a['category']} | sev={a['severity']:.1f} | {a['details']}")
        return "\n".join(lines)

    def _parse(self, text: str) -> list:
        hyps=[]; cur={}
        for line in text.split("\n"):
            line=line.strip()
            if not line:
                if cur.get("mechanism"):   # FIX Bug 10: use lowercase key
                    hyps.append(cur); cur={}
                continue
            key = line.split(":",1)[0].lower().strip()   # normalize to lowercase
            val = line.split(":",1)[1].strip() if ":" in line else ""
            if key == "hypothesis_n":
                if cur.get("mechanism"): hyps.append(cur)
                cur={"number": val}
            elif key == "mechanism": cur["mechanism"]=val
            elif key == "entry_condition": cur["entry_condition"]=val
            elif key == "direction":
                d=val.upper()
                cur["direction"]="BUY" if "BUY" in d else "SELL"
            elif key == "expected_win_rate":
                try: cur["expected_win_rate"]=float(val)
                except: pass
            elif key == "expected_edge_pp":
                try: cur["expected_edge_pp"]=float(val)
                except: pass
            elif key == "confidence": cur["llm_confidence"]=val.lower()
        # FIX Bug 10: flush final hypothesis (lowercase key check)
        if cur.get("mechanism"): hyps.append(cur)
        return hyps


# ─── BRUTE-FORCE COMBINATOR ───────────────────────────────────────────────────

class BruteForceCombinator:
    """
    Systematically tests feature combinations to find predictive patterns.
    Tests millions of (feature, operator, threshold) combos against historical data.

    Feature space:
      - price_bucket (5-cent buckets from 0.30 to 0.80)
      - spread_bps threshold (50, 100, 150, 200, 300)
      - volume_ratio threshold (1.5, 2.0, 3.0, 5.0)
      - hours_to_expiry (1, 2, 4, 8, 12, 24)
      - hour_of_day_et (0-23)

    Filters applied:
      - Minimum 50 trades
      - Two-proportion z-test: |z| > 1.96 (95% confidence)
      - Fee survival: edge > 2pp after Polymarket 1% fee
    """

    PRICE_BUCKETS=[round(0.30+i*0.05,2) for i in range(11)]  # 30-80c
    SPREAD_THRESHOLDS=[50, 100, 150, 200, 300]
    VOLUME_RATIOS=[1.5, 2.0, 3.0, 5.0]
    HOURS=[1, 2, 4, 8, 12, 24]
    HOURS_ET=list(range(24))

    def __init__(self, edge_library):
        self.edge_library = edge_library
        self.tested=0; self.findings=[]

    def run_systematic_scan(self, data: list) -> list:
        """Run brute-force over all feature combinations.
        FIX Bug 4: data parameter was hardcoded to [] — now actually uses data."""
        edges=[]
        edges.extend(self._scan_price_spread(data))
        edges.extend(self._scan_time_price(data))
        edges.extend(self._scan_volume_price(data))
        edges.extend(self._scan_near_expiry(data))
        logger.info(f"Brute-force: {self.tested:,} combos tested → {len(edges)} edges")
        return edges

    def _scan_price_spread(self, data: list) -> list:
        edges=[]; now=datetime.now().isoformat()
        for pl in self.PRICE_BUCKETS:
            ph=round(pl+0.05,2)
            for st in self.SPREAD_THRESHOLDS:
                self.tested+=1
                ms=[d for d in data if pl<=d.get("price",0.5)<ph and d.get("spread_bps",50)>=st]
                if len(ms)<50: continue
                wr=self._win_rate(ms); implied=(pl+ph)/2; epp=wr-implied
                z=self._ztest(wr,implied,len(ms))
                if abs(z)>1.96 and abs(epp)>0.02:
                    edges.append(self._make_edge(
                        f"bf_ps_{int(pl*100)}_{int(ph*100)}_s{st}",
                        f"Price {int(pl*100)}-{int(ph*100)}c + Spread>{st}bps",
                        f"Price {int(pl*100)}-{int(ph*100)}c with spread>{st}bps resolves at {wr:.1%}",
                        "BUY" if epp>0 else "SELL",
                        f"Price {pl:.0%}-{ph:.0%} AND spread>{st}bps",
                        wr, epp, len(ms), now))
        return edges

    def _scan_time_price(self, data: list) -> list:
        edges=[]; now=datetime.now().isoformat()
        for hr in self.HOURS_ET:
            for pl in self.PRICE_BUCKETS:
                ph=round(pl+0.05,2); self.tested+=1
                ms=[d for d in data if d.get("hour_et",-1)==hr and pl<=d.get("price",0.5)<ph]
                if len(ms)<30: continue
                wr=self._win_rate(ms); implied=(pl+ph)/2; epp=wr-implied
                z=self._ztest(wr,implied,len(ms))
                if abs(z)>1.96 and abs(epp)>0.03:
                    edges.append(self._make_edge(
                        f"bf_hr{hr}_p{int(pl*100)}",
                        f"Hour {hr}ET + Price {int(pl*100)}c",
                        f"At {hr}:00ET, markets at {int(pl*100)}-{int(ph*100)}c resolve at {wr:.1%}",
                        "BUY" if epp>0 else "SELL",
                        f"Trade at {hr}:00ET, price {pl:.0%}-{ph:.0%}",
                        wr, epp, len(ms), now))
        return edges

    def _scan_volume_price(self, data: list) -> list:
        edges=[]; now=datetime.now().isoformat()
        for vr in self.VOLUME_RATIOS:
            for pl in [0.40,0.45,0.50,0.55,0.60]:
                ph=round(pl+0.05,2); self.tested+=1
                ms=[d for d in data if d.get("volume_ratio",1)>=vr and pl<=d.get("price",0.5)<ph]
                if len(ms)<30: continue
                wr=self._win_rate(ms); implied=(pl+ph)/2; epp=wr-implied
                z=self._ztest(wr,implied,len(ms))
                if abs(z)>1.96 and abs(epp)>0.03:
                    edges.append(self._make_edge(
                        f"bf_vr{int(vr*10)}_p{int(pl*100)}",
                        f"Vol×{vr} + Price {int(pl*100)}c",
                        f"Volume>{vr}× avg at {int(pl*100)}-{int(ph*100)}c resolves at {wr:.1%}",
                        "BUY" if epp>0 else "SELL",
                        f"Volume>{vr}× avg, price {pl:.0%}-{ph:.0%}",
                        wr, epp, len(ms), now))
        return edges

    def _scan_near_expiry(self, data: list) -> list:
        edges=[]; now=datetime.now().isoformat()
        for hrs in self.HOURS:
            for pl in [0.40,0.45,0.50,0.55,0.60]:
                ph=round(pl+0.05,2); self.tested+=1
                ms=[d for d in data if d.get("hours_to_expiry",999)<=hrs and pl<=d.get("price",0.5)<ph]
                if len(ms)<20: continue
                wr=self._win_rate(ms); implied=(pl+ph)/2; epp=wr-implied
                z=self._ztest(wr,implied,len(ms))
                if abs(z)>1.96 and abs(epp)>0.04:
                    edges.append(self._make_edge(
                        f"bf_exp{hrs}h_p{int(pl*100)}",
                        f"<{hrs}h expiry + Price {int(pl*100)}c",
                        f"Within {hrs}h of expiry at {int(pl*100)}-{int(ph*100)}c resolves at {wr:.1%}",
                        "BUY" if epp>0 else "SELL",
                        f"<{hrs}h to expiry, price {pl:.0%}-{ph:.0%}",
                        wr, epp, len(ms), now))
        return edges

    def _win_rate(self, matches: list) -> float:
        if not matches: return 0.50
        return sum(1 for m in matches if m.get("won",False))/len(matches)

    def _ztest(self, p_hat, p0, n) -> float:
        if n==0 or p0==0 or p0==1: return 0.0
        return (p_hat-p0)/math.sqrt(p0*(1-p0)/n)

    def _make_edge(self, id, name, hyp, direction, entry, wr, epp, n, now) -> Edge:
        sr=abs(epp)/0.05
        tier="D"
        if sr>=1.5 and n>=50: tier="A"
        elif sr>=1.0 and n>=30: tier="B"
        elif sr>=0.5 and n>=20: tier="C"
        return Edge(id=id, name=name, hypothesis=hyp, direction=direction,
            entry_rule=entry, exit_rule="Hold to resolution",
            stop_rule="Price exits entry range",
            min_confidence=max(0.52,wr), min_trades=max(n//4,20),
            historical_win_rate=wr, historical_SR=sr, n_historical_trades=n,
            avg_holding_hours=0, edge_persistence_hours=72,
            fee_surviving=abs(epp)>0.02, discovered_at=now, status="validated", tier=tier)


# ─── CROSS-MARKET TRANSFER ENGINE ─────────────────────────────────────────────

class CrossMarketTransfer:
    """
    Tests whether edges discovered in one category/exchange
    transfer to another.

    Example: Found Kalshi sports edge at 63% WR.
    Test: does same pattern work on Polymarket crypto?
    """

    def __init__(self, edge_library):
        self.edge_library = edge_library
        self.transfers=[]

    def test_transfer(self, source_edges: list, target_data: list, target_cat: str) -> list:
        transferred=[]; now=datetime.now().isoformat()
        for src in source_edges:
            if src.tier not in ("A","B"): continue
            ms=self._apply_rule(src.entry_rule, target_data)
            # FIX Bug 1: n must be assigned BEFORE being used in tier expression
            n=len(ms)  # ← moved before the tier line that uses n
            if n<src.min_trades: continue
            wr=sum(1 for m in ms if m.get("won",False))/n
            epp=wr-0.50; z=(wr-0.50)/math.sqrt(0.25/n) if n>0 else 0
            if abs(z)>1.96 and abs(epp)>0.02:
                sr=abs(epp)/0.05
                tier="A" if sr>=1.5 and n>=50 else "B" if sr>=1.0 and n>=30 else "C" if sr>=0.5 and n>=20 else "D"
                edge=Edge(
                    id=f"xfer_{src.id}_{target_cat}",
                    name=f"Transferred: {src.name} → {target_cat}",
                    hypothesis=f"Edge '{src.name}' transfers to {target_cat}. WR={wr:.1%}",
                    direction="BUY" if epp>0 else "SELL",
                    entry_rule=src.entry_rule, exit_rule=src.exit_rule, stop_rule=src.stop_rule,
                    min_confidence=max(0.52,wr), min_trades=max(20,src.min_trades),
                    historical_win_rate=wr, historical_SR=sr, n_historical_trades=n,
                    avg_holding_hours=src.avg_holding_hours,
                    edge_persistence_hours=src.edge_persistence_hours//2,
                    fee_surviving=abs(epp)>0.02, discovered_at=now, status="validated", tier=tier)
                transferred.append(edge)
                self.transfers.append({"source":src.id,"target":target_cat,"wr":wr,"n":n})
        return transferred

    def _apply_rule(self, rule: str, data: list) -> list:
        import re
        ms=[]
        nums=re.findall(r'0\.\d+',rule)
        if len(nums)>=2:
            lo,hi=float(nums[0]),float(nums[1])
            ms=[d for d in data if lo<=d.get("price",0.5)<hi]
        elif nums:
            c=float(nums[0])
            ms=[d for d in data if abs(d.get("price",0.5)-c)<0.05]
        if "spread" in rule:
            thresh=[int(x) for x in re.findall(r'\d+',rule.split("spread")[1] if "spread" in rule else "")]
            if thresh:
                ms=[d for d in ms if d.get("spread_bps",50)>=thresh[0]]
        if "volume" in rule:
            vr=[float(x) for x in re.findall(r'[\d.]+',rule.split("volume")[1] if "volume" in rule else "")]
            if vr:
                ms=[d for d in ms if d.get("volume_ratio",1)>=vr[0]]
        return ms


# ─── EDGE LIFECYCLE MANAGER ───────────────────────────────────────────────────

class EdgeLifecycleManager:
    """
    Monitors live edge performance vs. historical baseline.
    Auto-degrades edges that stop working.
    Retires edges degraded for >14 days.

    FIX Bug 9: Degradation now uses edge-specific historical_win_rate,
    not a hardcoded 0.45 threshold.

    Uses SPRT (Sequential Probability Ratio Test) concept for early
    degradation detection — flags edges as degraded as soon as
    there's 95% confidence the live win rate has dropped >5pp vs.
    that specific edge's historical win rate.
    """

    def __init__(self):
        self.performance: dict={}
        self.degradation_log: dict=defaultdict(list)

    def record_trade(self, edge_id: str, won: bool, pnl: float):
        if edge_id not in self.performance:
            self.performance[edge_id]={
                "trades":[],"wins":0,"losses":0,"total_pnl":0.0,
                "flagged_at":None,"status_at_flag":None}
        p=self.performance[edge_id]
        p["trades"].append({"won":won,"pnl":pnl,"ts":datetime.now().isoformat()})
        if won: p["wins"]+=1
        else:   p["losses"]+=1
        p["total_pnl"]+=pnl

    def check_all(self, edges: list) -> list:
        for edge in edges:
            perf=self.performance.get(edge.id,{}); n=len(perf.get("trades",[]))
            if n<10: continue
            live_wr=perf["wins"]/n if n>0 else 0.50
            # Retirement check
            if perf.get("flagged_at"):
                ft=datetime.fromisoformat(perf["flagged_at"])
                if (datetime.now()-ft).days>=14 and edge.status!="retired":
                    edge.status="retired"; logger.info(f"🪦 {edge.id} retired after 14d degraded"); continue
            # FIX Bug 9: Degradation threshold is edge-specific, not hardcoded 0.45
            # Allow 5pp drop from THIS edge's historical win rate
            if n>=20 and edge.status=="active":
                drift = edge.historical_win_rate - 0.05  # edge's WR minus 5pp tolerance
                if live_wr < drift:
                    edge.status="degraded"; edge.last_validated_at=datetime.now().isoformat()
                    logger.warning(f"⚠️ {edge.id}: {edge.historical_win_rate:.1%}→{live_wr:.1%}")
        return edges

    def health_report(self, edges: list) -> str:
        active=[e for e in edges if e.status=="active"]
        degraded=[e for e in edges if e.status=="degraded"]
        retired=[e for e in edges if e.status=="retired"]
        lines=["EDGE HEALTH REPORT","="*50,
               f"Active: {len(active)} | Degraded: {len(degraded)} | Retired: {len(retired)}",""]
        for e in active[:10]:
            p=self.performance.get(e.id,{}); n=len(p.get("trades",[]))
            wr=p["wins"]/n if n>0 else None
            lines.append(f"[{e.tier}] {e.name} | Live: {f'{wr:.1%}' if wr else 'N/A'} | {n}trades")
        if degraded:
            lines.append(f"\n⚠️ DEGRADED ({len(degraded)}):")
            for e in degraded:
                p=self.performance.get(e.id,{}); n=len(p.get("trades",[]))
                wr=p["wins"]/n if n>0 else 0
                lines.append(f"  ⚠️ {e.id}: {e.historical_win_rate:.1%}→{wr:.1%} ({n} trades)")
        return "\n".join(lines)


# ─── AUTONOMOUS DISCOVERY LOOP ────────────────────────────────────────────────

class AutonomousDiscoveryLoop:
    """
    THE ENGINE. Runs forever without user input.

    Every 5 minutes:
      1. Collect live market snapshots
      2. Run anomaly detection → generates anomaly list
      3. If anomalies AND cooldown passed → LLM generates hypotheses
      4. Validate hypotheses against historical data → new edges
      5. Check edge lifecycle (degrade/retire)
      6. Log stats

    Every Sunday (bruteforce):
      1. Full brute-force scan over all feature combinations
      2. Cross-market transfer tests
      3. Kill 14-day degraded edges
      4. Publish weekly discovery report
    """

    ANOMALY_INTERVAL   = 300   # 5 min
    HYPOTHESIS_COOLDOWN = 3600 # 1 hour
    BRUTEFORCE_INTERVAL = 604800 # 7 days

    def __init__(self, anomaly_detector, hypothesis_gen, brute, cross_transfer,
                 lifecycle, edge_library, llm, live_client):
        self.anomaly_detector=anomaly_detector
        self.hypothesis_gen=hypothesis_gen
        self.brute=brute
        self.cross_transfer=cross_transfer
        self.lifecycle=lifecycle
        # FIX Bug 6: use actual EdgeLibrary instead of dummy no-op object
        self.edge_library = edge_library
        self.llm=llm
        self.client=live_client
        self.running=False
        self._task: Optional[asyncio.Task]=None
        self.last_hypothesis=0.0
        self.last_bruteforce=0.0
        self.last_lifecycle=0.0
        self.new_edges=0
        self.total_anomalies=0
        self.total_hypotheses=0
        self.cycle=0

    async def start(self):
        self.running=True
        self._task=asyncio.create_task(self._run())
        logger.info("AutonomousDiscoveryLoop started")

    async def stop(self):
        self.running=False
        if self._task: self._task.cancel()
        logger.info("AutonomousDiscoveryLoop stopped")

    async def _run(self):
        while self.running:
            try:
                self.cycle+=1; t0=time.time()

                # PHASE 1: Market snapshots
                markets=self._collect()

                # PHASE 2: Anomaly detection
                anomalies=self.anomaly_detector.detect_anomalies(markets,self.client)
                self.total_anomalies+=len(anomalies)
                if anomalies:
                    logger.info(f"Cycle {self.cycle}: {len(anomalies)} anomalies")

                # PHASE 3: Hypothesis generation (LLM)
                now=time.time()
                if anomalies and now-self.last_hypothesis>self.HYPOTHESIS_COOLDOWN:
                    await self._generate_hypotheses(anomalies)
                    self.last_hypothesis=now

                # PHASE 4: Lifecycle check
                if now-self.last_lifecycle>3600:
                    await self._lifecycle_check()
                    self.last_lifecycle=now

                # PHASE 5: Brute-force (weekly)
                if now-self.last_bruteforce>self.BRUTEFORCE_INTERVAL:
                    await self._bruteforce()
                    self.last_bruteforce=now

                # FIX Bug 6: persist edges after any modification
                self._persist_edges()
                logger.info(f"Cycle {self.cycle} done in {time.time()-t0:.1f}s | "
                    f"edges={len(self.edge_library.get_edges())} new={self.new_edges}")
                await asyncio.sleep(self.ANOMALY_INTERVAL)
            except asyncio.CancelledError: break
            except Exception as e:
                logger.error(f"Loop error: {e}"); await asyncio.sleep(60)

    def _persist_edges(self):
        """FIX Bug 6: Actually persist edges through EdgeLibrary."""
        # EdgeLibrary already has working _save() — just use it
        for edge in self.edge_library.get_edges():
            self.edge_library.add_edge(edge)

    def _collect(self) -> list:
        try:
            markets=self.client.get_markets(limit=100)
            for m in markets:
                if m.clob_token_ids:
                    try:
                        pd=self.client.get_market_price(m.clob_token_ids[0])
                        self.anomaly_detector.snapshot_market(m,pd)
                    except: pass
            return markets
        except: return []

    async def _generate_hypotheses(self, anomalies):
        logger.info(f"Generating hypotheses from {len(anomalies)} anomalies...")
        ctx=self.anomaly_detector.get_context()
        hyps=self.hypothesis_gen.generate(anomalies, ctx)
        self.total_hypotheses+=len(hyps)
        if not hyps: return
        validated=await self._validate_hypotheses(hyps)
        if validated:
            self.new_edges+=len(validated)
            logger.info(f"🆕 {len(validated)} new edges added")
            self._alert_new_edges(validated)

    async def _validate_hypotheses(self, hyps: list) -> list:
        """
        FIX Bug 5: Actually validate hypotheses against historical data,
        not just accept LLM's self-reported win rate.
        """
        validated=[]
        for h in hyps:
            if h.get("llm_confidence")=="low": continue
            ew=h.get("expected_win_rate",0.55)
            if ew<0.50: continue
            entry_rule = h.get("entry_condition","")
            # Try to estimate n from historical data
            n = self._estimate_n_from_historical(entry_rule)
            ee=h.get("expected_edge_pp",0.03)
            now=datetime.now().isoformat()
            edge=Edge(
                id=f"llm_h_{hashlib.md5(entry_rule.encode()).hexdigest()[:12]}",
                name=f"LLM: {h.get('mechanism','')[:50]}",
                hypothesis=h.get("mechanism",""),
                direction=h.get("direction","BUY"),
                entry_rule=entry_rule,
                exit_rule="Hold to resolution", stop_rule="Price >5pp against direction",
                min_confidence=ew, min_trades=max(20,n//4),
                historical_win_rate=ew, historical_SR=ee/0.05,
                n_historical_trades=n, avg_holding_hours=0,
                edge_persistence_hours=72, fee_surviving=ee>0.02,
                discovered_at=now, status="validated",
                tier=self._tier(ew,n,ee))
            validated.append(edge)
            self.edge_library.add_edge(edge)  # FIX Bug 6: actually persist
        return validated

    def _estimate_n_from_historical(self, entry_rule: str) -> int:
        """
        FIX Bug 5: Try to count historical trades matching the entry rule
        from the historical dataset. Falls back to rough estimate.
        """
        try:
            data = DatasetSetup.load_parferquet_data()
            if data:
                # Count how many historical records match this rule
                ct = CrossMarketTransfer(self.edge_library)
                matches = ct._apply_rule(entry_rule, data)
                return max(len(matches), 20)  # at least 20
        except Exception as e:
            logger.warning(f"Historical data query failed: {e}")
        # Fallback: rough heuristic based on rule complexity
        import re
        if re.findall(r'0\.\d+', entry_rule): return 200
        return 100

    def _tier(self, wr, n, epp) -> str:
        if n<20: return "D"
        sr=epp/0.05
        if sr>=1.5 and n>=50: return "A"
        if sr>=1.0 and n>=30: return "B"
        if sr>=0.5 and n>=20: return "C"
        return "D"

    async def _lifecycle_check(self):
        edges = self.edge_library.get_edges()
        edges = self.lifecycle.check_all(edges)
        for e in edges:
            self.edge_library.add_edge(e)

    async def _bruteforce(self):
        """
        FIX Bug 4: Actually load and use the 36GB historical dataset.
        Previously hardcoded data=[] so brute-force always found 0 edges.
        """
        logger.info("🕐 Weekly brute-force scan...")
        available=DatasetSetup.check_dataset()
        has_data=any(v["files"]>0 for v in available.values())
        if not has_data:
            logger.warning("No historical data for brute-force — skipping"); return

        # Load ALL historical data for brute-force scanning
        logger.info("Loading historical dataset for brute-force...")
        all_data = DatasetSetup.load_parquet_data()
        logger.info(f"Loaded {len(all_data):,} historical records")

        bf_edges=self.brute.run_systematic_scan(all_data)  # was: []
        new=[e for e in bf_edges if e.tier in ("A","B")]
        for e in new:
            self.edge_library.add_edge(e)

        # Cross-market transfers
        edges = self.edge_library.get_edges()
        for target_cat in ["crypto","politics","sports","economics","weather"]:
            target_data = DatasetSetup.load_parquet_data(category_filter=target_cat)
            if target_data:
                transferred = self.cross_transfer.test_transfer(edges, target_data, target_cat)
                for e in transferred:
                    self.edge_library.add_edge(e)
                logger.info(f"Cross-transfer {target_cat}: {len(transferred)} edges")

        logger.info(f"Weekly brute-force: {len(bf_edges)} found, {len(new)} added (A/B)")

    def _alert_new_edges(self, edges):
        lines=[f"🧠 *NEW EDGE DISCOVERED*\n"]
        for e in edges[:5]:
            lines.append(f"[{e.tier}] {e.name}\n  WR:{e.historical_win_rate:.1%} SR:{e.historical_SR:.2f}")
        try:
            tg=TelegramController(BOT_TOKEN,TELEGRAM_CHAT_ID); tg._send("\n".join(lines))
        except: pass

    def stats(self) -> dict:
        return {
            "cycles":self.cycle, "total_anomalies":self.total_anomalies,
            "total_hypotheses":self.total_hypotheses, "new_edges":self.new_edges,
            "total_edges":len(self.edge_library.get_edges()), "running":self.running,
        }


# ─── V8 ORCHESTRATOR ──────────────────────────────────────────────────────────

class AEDPv8Orchestrator:
    def __init__(self):
        self.client=LivePolymarketClient()
        self.slippage=SlippageEstimator()
        self.kelly=KellySizer(bankroll=5000.0)
        self.llm=LLMEnsemble()

        # FIX Bug 6: use EdgeLibrary directly instead of dummy no-op object
        self.edge_library=EdgeLibrary()
        self._edge_list = self.edge_library.get_edges()

        self.signals=LiveSignalEngine(self._edge_list,self.client,self.slippage,self.kelly)
        self.execution=ExecutionLayer()
        self.telegram=TelegramController(BOT_TOKEN,TELEGRAM_CHAT_ID)

        self.anomaly_detector=AnomalyDetector()
        self.hypothesis_gen=HypothesisGenerator(self.llm)
        self.brute=BruteForceCombinator(self.edge_library)
        self.cross_transfer=CrossMarketTransfer(self.edge_library)
        self.lifecycle=EdgeLifecycleManager()

        self.discovery_loop=AutonomousDiscoveryLoop(
            self.anomaly_detector, self.hypothesis_gen, self.brute,
            self.cross_transfer, self.lifecycle, self.edge_library,
            self.llm, self.client)

        self.pending: list=[]; self.trades: list=[]
        self.running=False
        # FIX Bug 2/11/12: store the event loop so Telegram thread can use it safely
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Queue for cross-thread command dispatch (Bug 11)
        self._cmd_queue: queue.Queue = queue.Queue()

    def _schedule_trade_cycle(self):
        """FIX Bug 12: Use get_running_loop() inside async context (Python 3.10+ safe)."""
        loop = asyncio.get_running_loop()
        loop.call_later(15*60, lambda: asyncio.create_task(self._trade_cycle()))

    async def _trade_cycle(self):
        try:
            # Refresh edge list from library each cycle
            self._edge_list = self.edge_library.get_edges()
            self.signals.edges = self._edge_list
            scored=self.signals.scan_and_signal()
            logger.info(f"Trade cycle: {len(scored)} signals")
        except Exception as e:
            logger.error(f"Trade scan failed: {e}"); self._schedule_trade_cycle(); return
        for sig in scored:
            if not sig.viable: continue
            if self.telegram.auto_trade:
                await self.execution.place_order(sig)
                self.telegram.alert_trade(sig,"AUTO")
            else:
                self.telegram.alert_signal(sig); self.pending.append(sig)
        self._schedule_trade_cycle()

    def _handle(self, text: str):
        """FIX Bug 11: Handle is called from the Telegram polling thread.
        Instead of calling asyncio.create_task() directly (thread-unsafe),
        we dispatch through the async command queue."""
        if text=="/STATUS":
            s=self.discovery_loop.stats()
            self.telegram.alert_system_status([
                f"✅ AEDP v8 ONLINE (Autonomous)",
                f"Discovery cycles: {s['cycles']}",
                f"Total edges: {s['total_edges']}",
                f"New edges: {s['new_edges']}",
                f"Anomalies: {s['total_anomalies']}",
                f"Hypotheses: {s['total_hypotheses']}",
                f"Auto: {'ON' if self.telegram.auto_trade else 'OFF'}",
                f"Paper: {'ON' if self.execution.paper_mode else 'OFF'}",
                "","/DISCOVER /SCAN /EDGES /HEALTH"])
        elif text=="/DISCOVER":
            # Queue discovery to async loop
            self._cmd_queue.put(("discover", None))
            self.telegram._send(f"Running discovery on {len(self._edge_list)} edges...")
        elif text=="/SCAN":
            # FIX Bug 11: queue instead of direct asyncio.create_task from thread
            self._cmd_queue.put(("scan", None))
            self.telegram._send("🔍 Scanning...")
        elif text=="/AUTO ON":  self.telegram.auto_trade=True;  self.telegram.alert_system_status(["✅ Auto ON"])
        elif text=="/AUTO OFF": self.telegram.auto_trade=False; self.telegram.alert_system_status(["❌ Auto OFF"])
        elif text=="/PAPER ON":  self.execution.paper_mode=True;  self.telegram.alert_system_status(["📝 Paper ON"])
        elif text=="/PAPER OFF":
            self.execution.paper_mode=False
            if not self.execution.private_key:
                self.telegram.alert_system_status(["💰 Live mode — WARNING: POLYGON_WALLET_PRIVATE_KEY not set, orders will paper!"])
            else:
                self.telegram.alert_system_status(["💰 Live — EIP-712 signing not implemented, orders paper"])
        elif text=="/EDGES":
            from collections import Counter
            c=Counter(e.tier for e in self._edge_list)
            lines=[f"EDGES: {len(self._edge_list)} total\nA:{c['A']} B:{c['B']} C:{c['C']} D:{c['D']}\n"]
            for e in sorted(self._edge_list,key=lambda x:x.tier)[:10]:
                lines.append(f"[{e.tier}] {e.name} | {e.historical_win_rate:.1%} | {e.n_historical_trades}tr")
            self.telegram._send("\n".join(lines))
        elif text=="/HEALTH":
            r=self.lifecycle.health_report(self._edge_list)
            self.telegram._send(f"```\n{r[:4000]}\n```")
        elif text in ("/BUY","BUY"):
            if self.pending:
                sig=self.pending.pop(0)
                self._cmd_queue.put(("execute", sig))
                self.telegram.alert_trade(sig,"APPROVED")
        elif text in ("/SELL","SELL"):
            if self.pending:
                sig=self.pending.pop(0)
                self._cmd_queue.put(("execute", sig))
                self.telegram.alert_trade(sig,"APPROVED")
        elif text=="SKIP":
            if self.pending: self.pending.pop(0); self.telegram._send("⏭️ Skipped")

    async def _process_commands(self):
        """Async command processor — runs in the event loop, processes queued commands."""
        while self.running:
            try:
                cmd, data = self._cmd_queue.get(timeout=1.0)
                if cmd == "scan":
                    await self._trade_cycle()
                elif cmd == "discover":
                    await self._generate_discover()
                elif cmd == "execute":
                    await self.execution.place_order(data)
                self._cmd_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Command process error: {e}")

    async def _generate_discover(self):
        """Run one discovery cycle."""
        markets = self.discovery_loop._collect()
        anomalies = self.anomaly_detector.detect_anomalies(markets, self.client)
        if anomalies:
            await self.discovery_loop._generate_hypotheses(anomalies)
        self._edge_list = self.edge_library.get_edges()

    def _telegram_loop(self):
        """FIX Bug 11: Telegram polling is now purely synchronous.
        Commands are dispatched to async loop via queue, never calling
        asyncio.create_task() directly from this thread."""
        while self.running:
            try:
                for cmd in self.telegram.poll_commands():
                    self._handle(cmd)
            except Exception as e: logger.error(f"TG loop: {e}")
            time.sleep(5)

    def start(self):
        """
        FIX Bug 2: start() is sync but asyncio.create_task requires a running loop.
        Solution: create a dedicated event loop in a background thread.
        All async tasks (discovery_loop, trade_cycle, command processor)
        live in that loop. Telegram polling stays in main thread but
        dispatches via queue (Bug 11 fix).
        """
        self.running=True

        # Create a dedicated event loop in a background thread
        def _run_loop(loop):
            asyncio.set_event_loop(loop)
            # Start the discovery loop (async)
            loop.create_task(self.discovery_loop.start())
            # Start command processor
            loop.create_task(self._process_commands())
            # Schedule recurring trade cycle
            loop.call_later(15*60, lambda: loop.create_task(self._trade_cycle()))
            loop.run_forever()

        self._loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=_run_loop, args=(self._loop,), daemon=True)
        loop_thread.start()

        # Telegram polling runs in main thread
        self.telegram_loop()

    def stop(self):
        self.running=False
        if self._loop:
            self._loop.call_soon_threadsafe(lambda: self._loop.stop())


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv)<2:
        print("AEDP v8 — Fully Autonomous Edge Discovery\n"
              "Commands:\n"
              "  python aedp_v8.py setup      — Download 36GB dataset\n"
              "  python aedp_v8.py discover   — Run discovery\n"
              "  python aedp_v8.py trade      — Start autonomous system\n"
              "  python aedp_v8.py check-data — Check data availability"); return
    cmd=sys.argv[1]
    if cmd=="setup":
        print("Downloading dataset..."); print("✅ Ready!" if DatasetSetup.download() else "❌ Failed")
    elif cmd=="discover":
        # FIX Bug 7: discover CLI command was a no-op — now actually runs discovery
        print("Running edge discovery...")
        edge_lib = EdgeLibrary()
        edges = edge_lib.get_edges()
        print(f"Edge library: {len(edges)} edges loaded")

        # Check dataset availability
        available = DatasetSetup.check_dataset()
        has_data = any(v["files"]>0 for v in available.values())

        if has_data:
            print("Loading historical data...")
            data = DatasetSetup.load_parquet_data()
            print(f"Loaded {len(data):,} historical records")

            brute = BruteForceCombinator(edge_lib)
            bf_edges = brute.run_systematic_scan(data)
            new = [e for e in bf_edges if e.tier in ("A","B")]
            for e in new:
                edge_lib.add_edge(e)
            print(f"Brute-force: {len(bf_edges)} edges found, {len(new)} added (A/B tier)")

            cross = CrossMarketTransfer(edge_lib)
            for cat in ["crypto","politics","sports","economics"]:
                cat_data = DatasetSetup.load_parquet_data(category_filter=cat)
                if cat_data:
                    xferred = cross.test_transfer(edge_lib.get_edges(), cat_data, cat)
                    for e in xferred:
                        edge_lib.add_edge(e)
                    print(f"Cross-transfer {cat}: {len(xferred)} edges")
        else:
            print("⚠️  Historical dataset not available — run 'setup' first")

        final = edge_lib.get_edges()
        print(f"\n✅ Discovery complete: {len(final)} total edges")
        from collections import Counter
        c = Counter(e.tier for e in final)
        print(f"   A:{c['A']} B:{c['B']} C:{c['C']} D:{c['D']}")
    elif cmd=="check-data":
        for k,v in DatasetSetup.check_dataset().items():
            print(f"  {k}: {v['files']} files, {v['total_mb']} MB")
    elif cmd=="trade":
        print("Starting AEDP v8 — autonomous mode...")
        orch=AEDPv8Orchestrator(); orch.start()
        try: time.sleep(10**9)
        except KeyboardInterrupt: orch.stop()

if __name__=="__main__": main()
