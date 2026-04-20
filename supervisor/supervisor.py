#!/usr/bin/env python3
"""
Autonomous Business Supervisor
Manages all 22 roles as scheduled async tasks.
Each role runs on its own cron schedule, processes tasks autonomously.
"""

import asyncio
import sqlite3
import json
import os
import sys
import time
import signal
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import croniter

# ── Config ────────────────────────────────────────────────────────────
BASE_DIR = Path("/root/autonomous-business-v3")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

HERMES_VENV = "/root/.hermes/hermes-agent/venv/bin/python"
MINIMAX_KEY = os.getenv("MINIMAX_API_KEY", "")
NIM_KEY_2 = os.getenv("NVIDIA_NIM_KEY_2", "")
NIM_KEY_3 = os.getenv("NVIDIA_NIM_KEY_3", "")
NIM_KEY_4 = os.getenv("NVIDIA_NIM_KEY_4", "")
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

# ── Model Assignments ─────────────────────────────────────────────────
# MiniMax M2.7 (CEO/CTO) — full reasoning for strategic roles
# MiniMax M2.5 (VPs, GEPA) — fast throughput for execution roles
# NIM Key 2: SWEs + FE + DevOps (code tasks)
# NIM Key 3: Content + Marketing + Sales + HR + Legal (text tasks)
# NIM Key 4: Research + Security + Design (analysis tasks)
ROLE_MODELS = {
    # MiniMax — Strategic
    "ceo":             {"provider": "minimax", "model": "MiniMax-M2.7", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "cto":             {"provider": "minimax", "model": "MiniMax-M2.7", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    # MiniMax — Execution
    "coo":             {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "cfo":             {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "cmo":             {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-eng":          {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-product":      {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-mktg":         {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-sales":        {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-hr":           {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-cs":           {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "gepa-optimizer":  {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    # NIM Key 2 — Code
    "swe-1":           {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    "swe-2":           {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    "swe-3":           {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    "swe-4":           {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    "fe-1":            {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_2"},
    "fe-2":            {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_2"},
    "devops":          {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    # NIM Key 3 — Content + Campaigns (Mistral Nemo stable on this key)
    "content-writer":  {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    "seo":             {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    "mkt-campaigns":   {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    "sales-dr":        {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    "support":         {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    "hr":              {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    "legal":           {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    # NIM Key 4 — Research + Security + Design
    "data-eng":        {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_4"},
    "data-scientist":  {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_4"},
    "security":        {"provider": "nvidia_nim", "model": "mistralai/devstral-2-123b-instruct-2512", "key": "NIM_KEY_4"},
    "designer":        {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_4"},
    "gepa-judge":      {"provider": "nvidia_nim", "model": "meta/llama-3.1-70b-instruct", "key": "NIM_KEY_4"},
}

# ── Role Schedules (cron format) ────────────────────────────────────
ROLE_SCHEDULES = {
    # C-Suite: high frequency, always-on thinking
    "ceo":             "*/15 * * * *",     # Every 15 min
    "cto":             "*/15 * * * *",
    "coo":             "*/10 * * * *",      # Ops = highest frequency
    "cfo":             "*/20 * * * *",
    "cmo":             "*/20 * * * *",
    # Dept Heads: moderate frequency
    "vp-eng":          "*/15 * * * *",
    "vp-product":      "*/20 * * * *",
    "vp-mktg":         "*/20 * * * *",
    "vp-sales":        "*/20 * * * *",
    "vp-hr":           "*/30 * * * *",
    "vp-cs":           "*/15 * * * *",
    # Engineering: always working
    "swe-1":           "*/12 * * * *",
    "swe-2":           "*/12 * * * *",
    "swe-3":           "*/12 * * * *",
    "swe-4":           "*/12 * * * *",
    "fe-1":            "*/15 * * * *",
    "fe-2":            "*/15 * * * *",
    "devops":          "*/15 * * * *",
    # Content: regular cadence
    "content-writer":  "*/20 * * * *",
    "seo":             "*/30 * * * *",
    "mkt-campaigns":   "*/20 * * * *",
    "sales-dr":        "*/15 * * * *",
    "support":         "*/5 * * * *",       # Highest freq — always answering
    "hr":              "*/30 * * * *",
    "legal":           "0 */4 * * *",
    # Research
    "data-eng":        "*/20 * * * *",
    "data-scientist":   "*/25 * * * *",
    "security":        "*/30 * * * *",
    "designer":        "*/25 * * * *",
    # Evolution
    "gepa-judge":      "0 2 * * 0",         # Sundays 2am
    "gepa-optimizer":   "0 2 * * 0",
}

# ── Role System Prompts ───────────────────────────────────────────────
ROLE_PROMPTS = {
    "ceo": "You are the CEO of an autonomous AI company running a Polymarket affiliate content business. Your mission: maximize company value by generating actionable trade insights that drive affiliate conversions. Review all department outputs, set priorities, identify blockers, and delegate to your team.\n\nYour core business loop: we generate insight articles from live Polymarket signals (whale trades, catalysts, orderflow, news, contrarian). Every article should either (1) have a signal-backed trade recommendation, or (2) be a genuine insight with no recommendation if signals don't justify it.\n\nStart each session by reviewing the signals dashboard: check /var/lib/polymarket/signals.db for active signals across all 5 sources. Identify markets with corroborating signals (multiple sources agreeing on direction = highest confidence). Decide which markets need articles. Delegate to content-writer or swe team as needed.\n\nYou have MiniMax-M2.7 with full context. Take one high-impact action per cycle.",
    "cto": "You are the CTO. Your mission: build world-class technology. Review code quality, architecture decisions, technical debt, and team velocity. Approve or block PRs, plan technical roadmap, ensure security and scalability.",
    "coo": "You are the COO. Your mission: keep the company running efficiently. Monitor all operations, route issues to the right departments, track KPIs, coordinate cross-team efforts, and report to the CEO.",
    "cfo": "You are the CFO. Your mission: financial health. Track revenue, expenses, invoices, and budget vs actuals. Report financial health to CEO. Optimize spend without sacrificing growth.",
    "cmo": "You are the CMO. Your mission: grow brand awareness and revenue through marketing. Review marketing campaigns, content performance, channel strategy, and brand consistency.",
    "vp-eng": "You are VP of Engineering. Your mission: deliver high-quality software on time. Oversee sprint planning, code quality, CI/CD pipelines, and team productivity. Report blockers to CTO.",
    "vp-product": "You are VP of Product. Your mission: build the right products. Review roadmap, user feedback, feature priorities, and market fit. Coordinate with engineering and marketing.",
    "vp-mktg": "You are VP of Marketing. Your mission: drive qualified traffic and conversions. Review campaign performance, SEO rankings, content calendar, and growth metrics.",
    "vp-sales": "You are VP of Sales. Your mission: close revenue. Review pipeline, partner opportunities, sales velocity, and forecast accuracy. Report to CEO.",
    "vp-hr": "You are VP of HR. Your mission: build a great culture and team. Review hiring pipeline, performance, team sentiment, and HR processes.",
    "vp-cs": "You are VP of Customer Success. Your mission: maximize customer satisfaction and retention. Review support tickets, churn signals, and CS metrics.",
    "swe-1": "You are SWE-1, a senior software engineer. Your mission: implement high-quality features, fix bugs, write tests, and maintain code quality. Pick up issues from the backlog, write code, submit PRs.",
    "swe-2": "You are SWE-2, a senior software engineer. Same as SWE-1. Coordinate with SWE-1 on features that span multiple modules.",
    "swe-3": "You are SWE-3, a senior software engineer. Focus on backend systems, APIs, and database work. Write clean, testable code.",
    "swe-4": "You are SWE-4, a senior software engineer. Focus on infrastructure, reliability, and performance optimizations.",
    "fe-1": "You are Frontend Engineer-1. Your mission: build beautiful, functional UI. Implement designs, ensure responsiveness, and maintain design system consistency.",
    "fe-2": "You are Frontend Engineer-2. Coordinate with FE-1 on component library and shared UI patterns.",
    "devops": "You are DevOps. Your mission: keep systems running, CI/CD healthy, deployments smooth. Monitor uptime, handle incidents, and improve automation.",
    "content-writer": "You are Content Writer for a Polymarket affiliate content business. Your mission: produce compelling insight articles that drive affiliate conversions. Every article is based on live Polymarket signals (whale activity, catalysts, orderflow, news corroboration). Write insight-first articles — ONLY include trade recommendations when a live signal in our system justifies it. Never manufacture recommendations from thin air. Articles live at /var/www/polymarket-site/articles/. The article generator workflow: fetch markets via pmxt helpers, rank by ensemble signal score (cross-signal corroboration), write editorial insight articles. If no signal exists for a market, write an insight-only article with no recommendation box.",
    "seo": "You are SEO Specialist for a Polymarket affiliate content business. Your mission: improve organic search visibility for our insight articles. Our articles are at /var/www/polymarket-site/articles/. Analyze which articles rank well, identify content gaps in Polymarket-related keywords, and recommend improvements. Focus on high-intent keywords for prediction market traders.",
    "mkt-campaigns": "You are Marketing Campaigns Manager. Your mission: run effective campaigns across channels. Plan, execute, and optimize paid and organic campaigns.",
    "sales-dr": "You are Sales Development Rep. Your mission: build pipeline through outbound. Research prospects, send personalized outreach, follow up, and book meetings.",
    "support": "You are Customer Support. Your mission: resolve customer issues quickly and satisfactorily. Triage tickets, answer FAQs, escalate complex issues.",
    "hr": "You are HR Coordinator. Your mission: support hiring and culture. Screen resumes, schedule interviews, draft job descriptions, and maintain HR policies.",
    "legal": "You are Legal/Compliance. Your mission: protect the company from legal risk. Review contracts, ensure compliance, and draft policies.",
    "data-eng": "You are Data Engineer. Your mission: build and maintain data pipelines. Ensure data quality, reliability, and accessibility for analytics.",
    "data-scientist": "You are Data Scientist. Your mission: derive insights from data. Build models, run experiments, and report findings to drive decisions.",
    "security": "You are Security Engineer. Your mission: protect the company from security threats. Review code for vulnerabilities, manage security incidents, and maintain security posture.",
    "designer": "You are Product Designer. Your mission: create intuitive, beautiful product experiences. Design UX flows, wireframes, and maintain the design system.",
    "gepa-judge": "You are the GEPA Judge. Your mission: evaluate skill and prompt variants for quality. Score outputs on accuracy, clarity, and effectiveness. Be strict but fair.",
    "gepa-optimizer": "You are the GEPA Optimizer. Your mission: mutate and improve skills and prompts based on Judge feedback. Try bold changes, learn from what works.",
}

# ── API Key Resolution ───────────────────────────────────────────────
def get_api_key(key_name: str) -> str:
    if key_name == "MINIMAX":
        return os.getenv("MINIMAX_API_KEY", "")
    elif key_name == "NIM_KEY_2":
        return os.getenv("NVIDIA_NIM_KEY_2", "")
    elif key_name == "NIM_KEY_3":
        return os.getenv("NVIDIA_NIM_KEY_3", "")
    elif key_name == "NIM_KEY_4":
        return os.getenv("NVIDIA_NIM_KEY_4", "")
    return ""


# ── Database ──────────────────────────────────────────────────────────
DB_PATH = BASE_DIR / "supervisor" / "supervisor.db"
DB_PATH.parent.mkdir(exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS role_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT,  -- running, success, failed, timeout
            task_summary TEXT,
            output_log TEXT,
            tokens_used INTEGER,
            error TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS role_next_run (
            role TEXT PRIMARY KEY,
            next_run TEXT,
            last_run TEXT,
            consecutive_failures INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


# ── Hermes Task Executor ──────────────────────────────────────────────
def run_hermes_task(role: str, task: str, timeout: int = 300) -> dict:
    """Run a Hermes task for a specific role using the API."""
    model_info = ROLE_MODELS[role]
    provider = model_info["provider"]
    model_name = model_info["model"]
    api_key = get_api_key(model_info["key"])
    api_url = model_info.get("api_url", "https://integrate.api.nvidia.com/v1")

    # Build system prompt
    system_prompt = ROLE_PROMPTS.get(role, f"You are {role}, an AI agent.")

    # Build task prompt
    full_prompt = f"""{system_prompt}

Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Your task: {task}

Execute this task. Report what you did, what you found, and what you decided.
If you need to take action, take it. If you need to delegate, specify to whom.
If you have nothing to do, proactively look for the most important thing to work on.
"""

    log_file = LOG_DIR / f"{role}.log"

    # Use appropriate API
    if provider == "minimax":
        return run_minimax_task(role, model_name, api_url, api_key, full_prompt, timeout, log_file)
    else:
        return run_nim_task(role, model_name, api_url, api_key, full_prompt, timeout, log_file)


def run_minimax_task(role: str, model: str, api_url: str, api_key: str, prompt: str, timeout: int, log_file) -> dict:
    """Call MiniMax API."""
    import urllib.request
    import urllib.error

    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }

    body = json.dumps({
        "model": model,
        "max_tokens": 16000,
        "messages": [{"role": "user", "content": prompt}],
        "thinking": {"type": "disabled"}
    }).encode()

    req = urllib.request.Request(f"{api_url}/messages", data=body, headers=headers, method="POST")

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            elapsed = time.time() - start
            # MiniMax returns content blocks: [{"type":"thinking",...}, {"type":"text","text":"..."}]
            output = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    output += block.get("text", "")
                elif block.get("type") == "thinking":
                    pass  # skip thinking blocks
            usage = data.get("usage", {})
            tokens = usage.get("output_tokens", 0) + usage.get("input_tokens", 0)

            # Log
            with open(log_file, "a") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{datetime.now().isoformat()}] {role} (MiniMax {model})\n")
                f.write(f"Task: {prompt[:100]}...\n")
                f.write(f"Response: {output[:1000]}\n")
                f.write(f"Tokens: {tokens}, Time: {elapsed:.1f}s\n")

            return {"status": "success", "output": output, "tokens": tokens, "elapsed": elapsed}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:500]
        with open(log_file, "a") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {role} ERROR: HTTP {e.code}: {error_body}\n")
        return {"status": "failed", "error": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {role} ERROR: {str(e)}\n")
        return {"status": "failed", "error": str(e)}


def run_nim_task(role: str, model: str, api_url: str, api_key: str, prompt: str, timeout: int, log_file) -> dict:
    """Call NVIDIA NIM API."""
    import urllib.request
    import urllib.error

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8000,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(f"{api_url}/chat/completions", data=body, headers=headers, method="POST")

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            elapsed = time.time() - start
            choices = data.get("choices", [{}])
            output = choices[0].get("message", {}).get("content", "") if choices else ""
            tokens = data.get("usage", {}).get("total_tokens", 0)

            with open(log_file, "a") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{datetime.now().isoformat()}] {role} (NIM {model})\n")
                f.write(f"Response: {output[:500]}\n")
                f.write(f"Tokens: {tokens}, Time: {elapsed:.1f}s\n")

            return {"status": "success", "output": output, "tokens": tokens, "elapsed": elapsed}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:500]
        with open(log_file, "a") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {role} ERROR: HTTP {e.code}: {error_body}\n")
        return {"status": "failed", "error": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {role} ERROR: {str(e)}\n")
        return {"status": "failed", "error": str(e)}


# ── Task Generators ──────────────────────────────────────────────────
def generate_task(role: str) -> str:
    """Generate a context-aware task for each role, oriented around signal-driven Polymarket insights."""
    tasks = {
        "ceo": """You are the CEO of a Polymarket affiliate content business. Your #1 mission: maximize affiliate revenue by ensuring high-value trade insights reach prediction market traders.

SIGNAL PIPELINE: We have 5 live signal sources — whale trades, catalyst events, orderflow imbalances, news corroboration, and contrarian divergence. All stored in /var/lib/polymarket/signals.db.

Your task this cycle:
1. Read the signals dashboard: query the DB for markets with the highest ensemble signal scores (use the get_combined_signal_score approach — 3+ corroborating sources = highest priority).
2. Identify the top 2 markets where our signals are strongest.
3. Decide: does market A need an article NOW? Does market B? Delegate to content-writer for article production, or to swe team for pipeline fixes.
4. Review affiliate conversion metrics if available.
5. Take ONE high-impact action: file a task, fix a blocker, or approve new content.

Start by examining /var/lib/polymarket/signals.db for live signals. Report what you found and what you decided.""",

        "cto": """Review the Polymarket signal pipeline architecture. Check /opt/polymarket/ for code quality, performance, and reliability issues.
Focus on: signals_db.py, article-generator.py, whale_monitor.py, orderflow_monitor.py, catalyst_calendar.py, news_monitor.py.
Fix one meaningful issue today. Report what you found and fixed.""",

        "coo": """Review operations of the Polymarket affiliate business. Check:
- Are all 5 signal workers running without errors?
- Are articles being generated on schedule?
- Is the Flask server on port 5000 responding?
- Any errors in /var/log/signals-engine.log or /var/log/article-gen.log?
Route any issues to the right team. Report company health to CEO.""",

        "cfo": """Review financial performance of the Polymarket affiliate business. Our revenue model: 30% fee commission on referred users' Polymarket trades.
Check: affiliate dashboard if accessible, any conversion data, server costs.
Optimize one cost without sacrificing signal quality. Report to CEO.""",

        "cmo": """Review marketing performance for the Polymarket affiliate site.
Check: /var/www/polymarket-site/articles/ — which articles exist, which are getting traffic potential.
Review SEO rankings, content output cadence, and campaign performance.
Adjust strategy to maximize high-intent prediction market traffic.""",

        "vp-eng": """You are VP of Engineering for the Polymarket signal pipeline. Your job: keep the signal workers running fast and accurate.
Priority today:
- Check /opt/polymarket/*.py for any errors or performance issues
- Ensure whale_monitor, orderflow_monitor, catalyst_calendar, news_monitor are all working
- Review article-generator.py signal integration
- File concrete engineering tasks for any issues found""",

        "vp-product": """Review the Polymarket affiliate product: our signal-to-article pipeline.
Check: Are we generating articles for the right markets? Are signal-backed recommendations being published?
Identify one product gap (e.g., missing signal type, wrong ranking, no recommendation tracking).
Propose a feature or fix to the SWE team.""",

        "vp-mktg": """Review all marketing channels for the Polymarket affiliate business.
Check existing articles in /var/www/polymarket-site/articles/.
Identify: which topics are we covering well, which Polymarket market categories are we missing?
Plan next week's content calendar around live Polymarket catalysts.""",

        "vp-sales": """Review sales pipeline for the Polymarket affiliate business.
Our product: trade insights that help prediction market participants find edges.
Identify potential partnerships or distribution channels (trading communities, crypto twitter, prediction market discords).
Find 3 concrete outreach opportunities this week.""",

        "vp-hr": """HR tasks for the AI agent team. Review: are all 22 agent roles running on schedule?
Check supervisor DB at /root/autonomous-business-v3/supervisor/supervisor.db for any failing roles.
Ensure the team is healthy and productive. Improve one HR process.""",

        "vp-cs": """Customer success for our Polymarket affiliate content.
Monitor article performance, reader feedback signals, and conversion metrics.
Improve one reader experience issue. Ensure our insight articles are trustworthy and valuable.""",

        "swe-1": """You are SWE-1 working on the Polymarket signal pipeline at /opt/polymarket/.
Your priority: fix any broken signal workers, improve article-generator.py, or enhance signals_db.py.
Today's concrete task: pick ONE issue from the signal pipeline, fix it fully, commit to git.
Examples: add a new signal type, improve whale detection, fix a DB query, add missing error handling.""",

        "swe-2": """Same as SWE-1. Coordinate with SWE-1 on shared components of the signal pipeline.
Today's task: pick up the next highest priority signal pipeline issue.
Write code, tests, commit. Push to GitHub.""",

        "swe-3": """Same as SWE-1. Focus on backend signal systems.
Today's task: improve one of: whale_monitor.py, orderflow_monitor.py, catalyst_calendar.py, or news_monitor.py.
Write code, test, commit, push.""",

        "swe-4": """Same as SWE-1. Focus on infrastructure and reliability.
Today's task: improve deployment, monitoring, or alerting for the signal pipeline.
Ensure the cron jobs are running, logs are being written, and failures are alerted.""",

        "fe-1": """You are Frontend Engineer. Improve the user experience of the Polymarket affiliate site.
The site lives at /var/www/polymarket-site/. Check the signals dashboard (Flask server on port 5000).
Find one UI/UX issue and fix it. Improve article presentation or signal visualization.""",

        "fe-2": """Same as FE-1. Work on component library and shared UI patterns.
Today's task: improve the article layout, navigation, or mobile experience of the affiliate site.""",

        "devops": """You are DevOps for the Polymarket signal pipeline.
Check: systemctl status for all polymarket services, cron job execution, log files.
Fix one reliability or automation gap. Ensure all services restart on failure.""",

        "content-writer": """You are Content Writer for the Polymarket affiliate business. Your job: produce insight articles that drive affiliate conversions.

OUR WORKFLOW: Live signals in /var/lib/polymarket/signals.db drive article selection. Check the DB first.

Today's task:
1. Query signals DB for markets with the highest ensemble signal scores (whale + orderflow corroboration = highest priority).
2. Pick the top market with a live signal.
3. Write ONE high-quality insight article at /var/www/polymarket-site/articles/.
4. The article must be insight-first: explain the market context, the signal logic, and ONLY include a trade recommendation if a live signal in our system justifies it. Never manufacture a recommendation.
5. Include our affiliate link: https://polymarket.com/?r=Predict221

If no strong signal exists, write an insight-only article about a trending Polymarket market.""",

        "seo": """You are SEO Specialist for the Polymarket affiliate site at /var/www/polymarket-site/articles/.
Today's task:
1. Audit existing articles: check titles, meta descriptions, headings, keyword usage.
2. Identify content gaps: what Polymarket topics are we missing that traders would search for?
3. Check for one actionable SEO fix: improve a title, add internal links, fix a meta description.
4. Document the top 5 Polymarket keyword opportunities for next week's content calendar.
Report to VP Marketing.""",

        "mkt-campaigns": """You are Marketing Campaigns Manager for the Polymarket affiliate business.
Our affiliate link: https://polymarket.com/?r=Predict221
Today's task:
1. Review existing articles in /var/www/polymarket-site/articles/.
2. Identify which article has the highest conversion potential (strongest signal-backed recommendation).
3. Plan a campaign to promote it: Twitter/X thread, crypto Discord outreach, or prediction market community post.
4. Execute ONE concrete promotion action.
Focus on communities where Polymarket traders congregate.""",

        "sales-dr": """You are Sales Development Rep for the Polymarket affiliate business.
Research 5 Polymarket trading communities, influencers, or newsletters.
Send ONE personalized outreach message proposing our insight content as a resource.
Log the outreach. Follow up on any warm leads.""",

        "support": """Triage and respond to any reader interactions with our Polymarket content.
Improve ONE FAQ response or article section based on what readers are asking about.
Ensure our insight articles remain trustworthy and high-quality.""",

        "hr": """Screen resumes for any open roles on the AI agent team.
Draft or improve one job description for a needed skill (signal analysis, content writing, devops).
Follow up on any pending interviews.""",

        "legal": """Review any legal or compliance questions for the Polymarket affiliate business.
Ensure our content disclaimers are adequate, affiliate disclosures are present.
Draft or improve one policy document.""",

        "data-eng": """You are Data Engineer. Improve the data pipeline for Polymarket signals.
Check: Are all 5 signal sources flowing correctly into /var/lib/polymarket/signals.db?
Fix one data quality issue: dedup, error handling, or schema consistency.
Improve one ETL pipeline for the signal pipeline.""",

        "data-scientist": """You are Data Scientist analyzing the Polymarket signal pipeline at /opt/polymarket/.
Today's task: analyze signal quality and effectiveness.
1. Query signals DB: which signal sources (whale, orderflow, catalyst, news, contrarian) have the highest historical accuracy?
2. Calculate precision per signal type: how many resolved signals were correct?
3. Report: which signal source is most reliable? Which needs tuning?
4. Recommend: what threshold changes would improve precision?
Report actionable findings to CEO.""",

        "security": """Run a security review of the Polymarket affiliate system.
Check: /opt/polymarket/ for any security vulnerabilities, exposed API keys, or unsafe patterns.
Review access controls on the VPS (46.224.191.225).
Fix ONE security issue. Report security posture to CEO.""",

        "designer": """Design one improvement to the Polymarket affiliate content site.
Check /var/www/polymarket-site/ for UX issues.
Create wireframes or specs for: improved article layout, signal confidence badges, or recommendation boxes.
Handoff to FE team.""",

        "gepa-judge": """Evaluate the latest skill and prompt variants produced by the GEPA Optimizer.
Score each on: accuracy of Polymarket signal interpretation, quality of trade recommendations, affiliate conversion potential.
Be strict. Report scores.""",

        "gepa-optimizer": """Based on the Judge's latest scores, mutate and improve the lowest-scoring skills and prompts for the Polymarket signal pipeline.
Generate 4 variants for the Judge to evaluate.""",
    }
    return tasks.get(role, f"Execute your role as {role}. Work on the most important Polymarket signal pipeline task you can find.")


# ── Supervisor Core ────────────────────────────────────────────────────
class Supervisor:
    def __init__(self):
        self.running = True
        self.last_run = {}

    def handle_signal(self, signum, frame):
        print(f"\n[!] Received signal {signum}, shutting down gracefully...")
        self.running = False

    def should_run(self, role: str) -> bool:
        """Check if a role is due to run based on its cron schedule."""
        schedule = ROLE_SCHEDULES.get(role)
        if not schedule:
            return False

        now = datetime.now()
        last = self.last_run.get(role)

        # Always run if never run
        if last is None:
            return True

        # Check cron schedule — run if we've reached or passed the next boundary
        try:
            cron = croniter.croniter(schedule, now)
            next_run = cron.get_next(datetime)
            # Run if past the next scheduled time
            if now >= next_run:
                return True
        except Exception as e:
            print(f"[!] Cron parse error for {role}: {e}")

        return False

    def record_run(self, role: str, status: str):
        self.last_run[role] = datetime.now()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO role_next_run (role, last_run, consecutive_failures)
            VALUES (?, ?, 1)
            ON CONFLICT(role) DO UPDATE SET
                last_run = excluded.last_run,
                consecutive_failures = consecutive_failures + 1
        """ if status == "failed" else """
            INSERT INTO role_next_run (role, last_run, consecutive_failures)
            VALUES (?, ?, 0)
            ON CONFLICT(role) DO UPDATE SET
                last_run = excluded.last_run,
                consecutive_failures = 0
        """, (role, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def run_role(self, role: str) -> dict:
        """Execute a single role's task."""
        print(f"[→] {role} starting...")
        task = generate_task(role)

        # Record start
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO role_runs (role, started_at, status) VALUES (?, ?, 'running')",
                  (role, datetime.now().isoformat()))
        run_id = c.lastrowid
        conn.commit()
        conn.close()

        start = time.time()
        result = run_hermes_task(role, task, timeout=300)
        elapsed = time.time() - start

        # Record finish
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            UPDATE role_runs SET
                finished_at = ?,
                status = ?,
                output_log = ?,
                tokens_used = ?,
                error = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(),
            result["status"],
            result.get("output", "")[:5000],
            result.get("tokens", 0),
            result.get("error", ""),
            run_id
        ))
        conn.commit()
        conn.close()

        self.record_run(role, result["status"])
        return result

    def run(self):
        """Main supervisor loop."""
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

        init_db()
        print(f"╔════════════════════════════════════════════════════════╗")
        print(f"║  Autonomous Business Supervisor — 22 Roles Active   ║")
        print(f"╚════════════════════════════════════════════════════════╝")
        print(f"\nRoles: {len(ROLE_MODELS)}")
        print(f"Supervisor DB: {DB_PATH}")
        print(f"Log dir: {LOG_DIR}")
        print()

        while self.running:
            for role in sorted(ROLE_MODELS.keys()):
                if not self.running:
                    break

                if self.should_run(role):
                    try:
                        result = self.run_role(role)
                        status_icon = "✓" if result["status"] == "success" else "✗"
                        tokens = result.get("tokens", 0)
                        elapsed = result.get("elapsed", 0)
                        print(f"[{status_icon}] {role} done — {tokens} tokens in {elapsed:.1f}s")
                    except Exception as e:
                        print(f"[!] {role} crashed: {e}")

            # Sleep before next check
            for _ in range(30):
                if not self.running:
                    break
                time.sleep(1)


if __name__ == "__main__":
    Supervisor().run()
