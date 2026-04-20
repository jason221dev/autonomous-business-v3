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
ROLE_MODELS = {
    # Key 1: MiniMax Official
    "ceo":             {"provider": "minimax", "model": "MiniMax-M2.7", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "cto":             {"provider": "minimax", "model": "MiniMax-M2.7", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "coo":             {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "cfo":             {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "cmo":             {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-eng":          {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-product":      {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-mktg":         {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-sales":        {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-hr":           {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    "vp-cs":           {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
    # Key 2: NIM Code
    "swe-1":           {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    "swe-2":           {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    "swe-3":           {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    "swe-4":           {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    "fe-1":            {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_2"},
    "fe-2":            {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_2"},
    "devops":          {"provider": "nvidia_nim", "model": "nvidia/nemotron-4-mini-hin-4b", "key": "NIM_KEY_2"},
    # Key 3: NIM Content
    "content-writer":  {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    "seo":             {"provider": "nvidia_nim", "model": "google/gemma-3-27b-it", "key": "NIM_KEY_3"},
    "mkt-campaigns":   {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    "sales-dr":        {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2-instruct", "key": "NIM_KEY_3"},
    "support":         {"provider": "nvidia_nim", "model": "meta/llama-3.1-8b-instruct", "key": "NIM_KEY_3"},
    "hr":              {"provider": "nvidia_nim", "model": "mistralai/mixtral-8x7b-instruct-v0.1", "key": "NIM_KEY_3"},
    "legal":           {"provider": "nvidia_nim", "model": "mistralai/mistral-nemo-12b-instruct", "key": "NIM_KEY_3"},
    # Key 4: NIM Research
    "data-eng":        {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_4"},
    "data-scientist":   {"provider": "nvidia_nim", "model": "google/gemma-3-27b-it", "key": "NIM_KEY_4"},
    "security":        {"provider": "nvidia_nim", "model": "mistralai/devstral-2-123b-instruct-2512", "key": "NIM_KEY_4"},
    "designer":        {"provider": "nvidia_nim", "model": "moonshotai/kimi-k2.5", "key": "NIM_KEY_4"},
    "gepa-judge":      {"provider": "nvidia_nim", "model": "meta/llama-3.1-70b-instruct", "key": "NIM_KEY_4"},
    "gepa-optimizer":   {"provider": "minimax", "model": "MiniMax-M2.5", "key": "MINIMAX", "api_url": "https://api.minimax.io/anthropic/v1"},
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
    """Generate a context-aware task for each role."""
    tasks = {
        "ceo": "Review company status. Check all department outputs since last run. Identify the top 3 priorities. Decide what to delegate and to whom. Take one high-impact action.",
        "cto": "Review recent PRs and code changes. Check for quality issues, security concerns, or technical debt. Approve good PRs, block bad ones. Plan next sprint's technical approach.",
        "coo": "Review operations dashboard. Check issue queue, team workloads, and bottlenecks. Route any stuck issues. Report to CEO on company health.",
        "cfo": "Review financial metrics: revenue, expenses, runway. Check all invoices and payments. Flag any anomalies. Optimize one cost this week.",
        "cmo": "Review marketing performance: campaign metrics, social engagement, SEO rankings, content output. Adjust strategy based on what is working.",
        "vp-eng": "Review sprint progress. Check CI/CD health, test coverage, and bug queue. Remove blockers for the engineering team. Report to CTO.",
        "vp-product": "Review product metrics: user feedback, feature adoption, roadmap progress. Prioritize next features based on impact. Align with marketing and engineering.",
        "vp-mktg": "Review all marketing channels: email, social, SEO, paid. Identify top-performing content. Plan next week's content calendar.",
        "vp-sales": "Review sales pipeline. Check new leads, follow-ups, and closed deals. Identify bottlenecks in the sales process.",
        "vp-hr": "Review hiring pipeline: open roles, candidate status, offer acceptances. Check team sentiment. Improve one HR process this week.",
        "vp-cs": "Review support queue: ticket volume, CSAT scores, response times. Identify systemic issues causing tickets. Improve one support process.",
        "swe-1": "Pick up the most important open issue from the backlog. Implement it fully: write code, tests, and documentation. Submit a PR when done.",
        "swe-2": "Pick up the next highest priority issue. Focus on code quality and test coverage. Coordinate with SWE-1 on any shared components.",
        "swe-3": "Review backend systems: APIs, databases, and data models. Fix one performance issue or security concern. Optimize one slow query.",
        "swe-4": "Review infrastructure: deployments, monitoring, and alerting. Fix one reliability issue. Improve deployment automation.",
        "fe-1": "Pick up the highest priority UI issue. Implement pixel-perfect, responsive components. Ensure design system consistency.",
        "fe-2": "Work on component library and shared UI patterns. Improve one area of technical debt in the frontend.",
        "devops": "Check CI/CD pipelines, server health, and deployment status. Fix one automation gap. Improve monitoring or alerting.",
        "content-writer": "Write one high-quality blog post or content piece. Focus on SEO value and engagement. Publish when ready.",
        "seo": "Run SEO audit: check rankings, backlinks, and technical SEO. Fix one actionable issue. Identify content gap opportunities.",
        "mkt-campaigns": "Review campaign performance. Optimize one underperforming campaign. Launch one new initiative based on data.",
        "sales-dr": "Research 10 new prospects. Send 5 personalized outreach messages. Follow up on 5 warm leads. Log all activity.",
        "support": "Triage and respond to all pending support tickets. Resolve what you can, escalate what needs escalation. Improve one FAQ response.",
        "hr": "Screen resumes for one open role. Draft or improve one job description. Follow up on any pending interviews or offers.",
        "legal": "Review any pending contracts or legal questions. Draft or improve one policy document. Ensure compliance with regulations.",
        "data-eng": "Check data pipeline health. Fix any broken or lagging data flows. Improve data quality in one area.",
        "data-scientist": "Analyze one key business metric. Build or update one data model. Report one actionable insight to the CEO.",
        "security": "Run security scan on codebase and infrastructure. Fix one vulnerability. Review and improve one security policy.",
        "designer": "Design one new feature or improvement based on user feedback. Create wireframes and specs. Handoff to FE team.",
        "gepa-judge": "Evaluate the latest skill and prompt variants produced by the GEPA Optimizer. Score each on quality, accuracy, and effectiveness. Report scores.",
        "gepa-optimizer": "Based on the Judge's latest scores, mutate and improve the lowest-scoring skills and prompts. Generate 4 variants for the Judge to evaluate.",
    }
    return tasks.get(role, f"Execute your role as {role}. Do the most important thing you can this cycle.")


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
