# Autonomous Business v3 — Live on VPS

> **22 AI agents running 24/7 as cron-scheduled tasks** — C-Suite, Engineering, Marketing, Sales, Support, HR, Legal, Data, Security, Design + Self-Evolution Engine.

**Stack:** Python Supervisor · MiniMax API · NVIDIA NIM × 3 keys
**VPS:** Hetzner (4 vCPU / 7.6GB RAM)
**Cost:** ~$130/month (LLM inference only — no extra VPS cost, reusing your existing VPS)
**Status:** ✅ **LIVE** — CEO already generating company status reports

---

## What's Running

```
company-supervisor.service (systemd)
├── CEO          → MiniMax-M2.7  (every 15 min)
├── CTO          → MiniMax-M2.7  (every 15 min)
├── COO          → MiniMax-M2.5  (every 10 min)
├── CFO          → MiniMax-M2.5  (every 20 min)
├── CMO          → MiniMax-M2.5  (every 20 min)
├── VP Eng       → MiniMax-M2.5  (every 15 min)
├── VP Product   → MiniMax-M2.5  (every 20 min)
├── VP Mktg      → MiniMax-M2.5  (every 20 min)
├── VP Sales     → MiniMax-M2.5  (every 20 min)
├── VP HR        → MiniMax-M2.5  (every 30 min)
├── VP CS        → MiniMax-M2.5  (every 15 min)
├── SWE 1-4      → kimi-k2.5 (NIM) (every 12 min)
├── FE 1-2       → kimi-k2.5 (NIM) (every 15 min)
├── DevOps       → nemotron-4-mini (NIM) (every 15 min)
├── Content Writer → kimi-k2.5 (NIM) (every 20 min)
├── SEO          → gemma-3-27b-it (NIM) (every 30 min)
├── Mkt Campaigns → mistral-nemo-12b (NIM) (every 20 min)
├── Sales DR     → kimi-k2-instruct (NIM) (every 15 min)
├── Support      → llama-3.1-8b (NIM) (every 5 min) ← highest frequency
├── HR           → mixtral-8x7b (NIM) (every 30 min)
├── Legal        → mistral-nemo-12b (NIM) (every 4 hours)
├── Data Eng     → kimi-k2.5 (NIM) (every 20 min)
├── Data Scientist → gemma-3-27b-it (NIM) (every 25 min)
├── Security     → devstral-2-123b (NIM) (every 30 min)
├── Designer     → kimi-k2.5 (NIM) (every 25 min)
└── GEPA Judge   → llama-3.1-70b (NIM) (Sundays 2am)
```

---

## Quick Start on a New VPS

```bash
# 1. Clone
git clone https://github.com/jason221dev/autonomous-business-v3.git
cd autonomous-business-v3

# 2. Install Docker
curl -fsSL https://get.docker.com | sh

# 3. Configure keys
cp .env.example .env
# Edit .env with your API keys

# 4. Install supervisor
pip install croniter
cp supervisor/company-supervisor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable company-supervisor --now

# 5. Start infrastructure
docker compose up -d postgres redis

# 6. Watch logs
tail -f logs/ceo.log
```

---

## Project Structure

```
autonomous-business-v3/
├── supervisor/
│   ├── supervisor.py           # Python supervisor — manages all 22 roles
│   └── company-supervisor.service  # systemd service
├── worker-configs/            # Per-role YAML configs
├── docker-compose.yml         # postgres + redis
├── Dockerfile.minimax          # MiniMax container
├── Dockerfile.nim             # NIM container
├── role-runner.sh             # Multi-process role runner
├── scripts/
│   ├── bootstrap.sh
│   └── quickstart.sh
├── cron.d/                    # Cron job definitions
└── evolution/                 # GEPA evolution engine
```

---

## Logs

```bash
# Watch all role logs
ls -la /root/autonomous-business-v3/logs/

# Watch specific role
tail -f /root/autonomous-business-v3/logs/ceo.log

# Supervisor status
systemctl status company-supervisor

# Supervisor logs
journalctl -u company-supervisor -f
```

---

## Cost Breakdown

| Key | Provider | Roles | Est. Cost/mo |
|-----|----------|-------|-------------|
| Key 1 | MiniMax | CEO, CTO, COO, CFO, CMO + 6 VPs + GEPA Opt | ~$15 |
| Key 2 | NIM | SWE×4, FE×2, DevOps | ~$60 |
| Key 3 | NIM | Content, SEO, Campaigns, Sales, Support, HR, Legal | ~$35 |
| Key 4 | NIM | Data, Security, Design + GEPA Judge | ~$40 |
| | | **Total** | **~$150/mo** |

---

## Sample Output (CEO — Live)

```
### 🧪 Research Division — Dr. Elena Vasquez
- **Status:** ✅ On track
- **Outputs:**
  - Completed v2.5 of our core reasoning model — 18% improvement on MMLU
  - Breakthrough on "context compression" — can now run 500K token context
  - Drafted whitepaper on "Efficient Long-Context Attention Mechanisms"
- **Concerns:** Compute budget for next training run not confirmed

### ⚙️ Engineering — Marcus Chen, CTO
- **Status:** ⚠️ At risk
- **Outputs:**
  - API v3.0 launched to beta (200 enterprise customers)
  - 99.97% uptime this week
  - API latency p99 down from 340ms to 210ms
- **Blockers:**
  - Core model weight leak detected on GitHub — legal engaged
  - Two senior engineers on leave — sprint velocity dropped 30%
```

---

*github.com/jason221dev/autonomous-business-v3*
