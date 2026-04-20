# Autonomous Business v3 — Full 22-Role AI Company

> **22 AI agents running 24/7** — C-Suite, Engineering, Marketing, Sales, Support, HR, Legal, Data, Security, Design + Self-Evolution Engine.

**Stack:** Paperclip (orchestration) · Hermes Agent (runtime) · MiniMax 2.7 (strategic brain) · NVIDIA NIM × 3 keys (specialist execution)
**Monthly cost:** ~$194/month (LLM inference + VPS + storage)
**Human role:** Board — approve strategy, set mission, override decisions

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PAPERCLIP ORCHESTRATION                           │
│          Scheduler · Org Chart · Issue Routing · Heartbeat · KPIs           │
└─────────────────────────────────────────────────────────────────────────────┘

        KEY 1: MINIMAX                  KEY 2: NIM CODE                   KEY 3: NIM CONTENT
   MiniMax Official API              NVIDIA NIM — Code Tier           NVIDIA NIM — Content Tier
   $11/month (~206M tokens)           $72/month (~179M tokens)         $35/month (~77M tokens)
  ┌─────────────────────┐            ┌─────────────────────┐         ┌─────────────────────┐
  │  CEO     [Text-01]  │            │  SWE ×4 [kimi-k2.5] │         │ Content [kimi-k2.5]│
  │  CTO     [Text-01]  │            │  FE ×2  [kimi-k2.5] │         │ SEO     [gemma-27b] │
  │  COO     [M2.5]     │            │  DevOps [nemotron-4]│         │ Campaigns [mistral] │
  │  CFO     [M2.5]     │            └─────────────────────┘         │ Sales DR [kimi-k2]  │
  │  CMO     [M2.5]     │                                            │ Support [llama-8b] │
  │  VP Eng  [M2.5]     │            KEY 4: NIM RESEARCH             │ HR       [mixtral]  │
  │  VP Prod [M2.5]     │         NVIDIA NIM — Research Tier         │ Legal    [mistral]  │
  │  VP Mktg [M2.5]     │            $54/month                       └─────────────────────┘
  │  VP Sales[M2.5]     │            ┌─────────────────────┐
  │  VP HR   [M2.5]     │            │ Data Eng  [kimi-k2.5]│
  │  VP CS   [M2.5]     │            │ Data Sci  [gemma-27b]│
  │  GEPA    [M2.5]     │            │ Security  [devstral] │
  └─────────────────────┘            │ Designer  [kimi-k2.5]│
                                    │ GEPA Judge[llama-70b] │
                                    └─────────────────────┘
```

---

## Complete Role Assignments

| # | Role | Model | Provider | Key | Est. Cost/mo |
|---|------|-------|----------|-----|-------------|
| 1 | CEO | MiniMax-Text-01 (1M ctx) | MiniMax Official | 1 | $3.75 |
| 2 | CTO | MiniMax-Text-01 (1M ctx) | MiniMax Official | 1 | $3.30 |
| 3 | COO | MiniMax-M2.5 (1M ctx) | MiniMax Official | 1 | $0.19 |
| 4 | CFO | MiniMax-M2.5 (1M ctx) | MiniMax Official | 1 | $0.15 |
| 5 | CMO | MiniMax-M2.5 (1M ctx) | MiniMax Official | 1 | $0.18 |
| 6 | VP Engineering | MiniMax-M2.5 | MiniMax Official | 1 | $0.18 |
| 7 | VP Product | MiniMax-M2.5 | MiniMax Official | 1 | $0.18 |
| 8 | VP Marketing | MiniMax-M2.5 | MiniMax Official | 1 | $0.13 |
| 9 | VP Sales | MiniMax-M2.5 | MiniMax Official | 1 | $0.11 |
| 10 | VP HR | MiniMax-M2.5 | MiniMax Official | 1 | $0.09 |
| 11 | VP Customer Success | MiniMax-M2.5 | MiniMax Official | 1 | $0.12 |
| 12 | SWE ×4 | kimi-k2.5 (131K ctx) | NIM | 2 | $39.00 |
| 13 | Frontend Dev ×2 | kimi-k2.5 (131K ctx) | NIM | 2 | $16.00 |
| 14 | DevOps | nemotron-4-mini-hin-4b | NIM | 2 | $0.84 |
| 15 | Content Writer | kimi-k2.5 (131K ctx) | NIM | 3 | $10.00 |
| 16 | SEO Specialist | gemma-3-27b-it (131K ctx) | NIM | 3 | $9.00 |
| 17 | Marketing Campaigns | mistral-nemo-12b (128K ctx) | NIM | 3 | $5.51 |
| 18 | Sales Dev Rep | kimi-k2-instruct (131K ctx) | NIM | 3 | $4.50 |
| 19 | Customer Support | llama-3.1-8b-instruct (128K ctx) | NIM | 3 | $1.20 |
| 20 | HR Coordinator | mixtral-8x7b-instruct (32K ctx) | NIM | 3 | $2.16 |
| 21 | Legal | mistral-nemo-12b (128K ctx) | NIM | 3 | $3.15 |
| 22 | Data Engineer | kimi-k2.5 (131K ctx) | NIM | 4 | $9.00 |
| 23 | Data Scientist | gemma-3-27b-it (131K ctx) | NIM | 4 | $10.00 |
| 24 | Security Engineer | devstral-2-123b-instruct (32K ctx) | NIM | 4 | $5.40 |
| 25 | Product Designer | kimi-k2.5 (131K ctx) | NIM | 4 | $8.00 |
| — | GEPA Optimizer | MiniMax-M2.5 | MiniMax Official | 1 | $0.02 |
| — | GEPA Judge | llama-3.1-70b-instruct | NIM | 4 | $3.00 |
| — | Premium Judge | nemotron-4-340b-instruct | NIM | 4 | $1.00 |
| | **LLM Total** | | | | **$126/mo** |
| | **+ 1.3× overhead** | | | | **$164/mo** |
| | **+ Infrastructure** | | | | **~$30/mo** |
| | **Grand Total** | | | | **~$194/mo** |

---

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/jason221dev/autonomous-business-v3.git
cd autonomous-business-v3
cp .env.example .env
# Edit .env with your API keys

# 2. Deploy
docker-compose up -d

# 3. Bootstrap company structure
./scripts/bootstrap.sh

# 4. Monitor
docker-compose logs -f hermes-ceo
```

---

## Project Structure

```
autonomous-business-v3/
├── README.md                      # This file
├── docker-compose.yml             # Full 27-container deployment
├── Dockerfile.hermes              # Base image for all 22 agents
├── Dockerfile.hermes-evolution    # Self-evolution engine
├── .env.example                   # API key template
│
├── worker-configs/                # Per-agent YAML configs
│   ├── ceo/
│   ├── cto/
│   ├── coo/
│   ├── cfo/
│   ├── cmo/
│   ├── vp-eng/
│   ├── vp-product/
│   ├── vp-mktg/
│   ├── vp-sales/
│   ├── vp-hr/
│   ├── vp-cs/
│   ├── swe-1/  (×4 — swe-2, swe-3, swe-4)
│   ├── fe-1/   (×2 — fe-2)
│   ├── devops/
│   ├── content-writer/
│   ├── seo/
│   ├── mkt-campaigns/
│   ├── sales-dr/
│   ├── support/
│   ├── hr/
│   ├── legal/
│   ├── data-eng/
│   ├── data-scientist/
│   ├── security/
│   └── designer/
│
├── evolution/                     # Self-Evolution Engine
│   └── config.yaml
│
└── scripts/
    ├── bootstrap.sh               # Initialize company structure
    └── quickstart.sh              # 5-minute deploy script
```

---

## Key Design Decisions

### 1. MiniMax Official API for Strategic Tier (Key 1)
CEO and CTO run `MiniMax-Text-01` with 1M context — entire company history, all agent sessions, full quarter of KPIs in a single context window. All other Key 1 roles use `M2.5` at near-zero cost for volume operations.

### 2. Kimi K2.5 on All Code and Content Work (NIM Keys 2 & 3)
`moonshotai/kimi-k2.5` (131K context) is the best NIM model for both code and content. 131K context = entire feature branch + related modules, or full brand guidelines + competitor analysis + style guide in one window.

### 3. Automatic Model Routing on Every Agent
Every NIM agent has fallback routing — cheap fast models for simple tasks, expensive models only for complex tasks. This saves 30-40% on token costs automatically.

### 4. Nemotron Mini for DevOps
DevOps is 80% short shell scripts. `nemotron-4-mini-hin-4b` (4K context, $0.10/1M tokens) handles most tasks at near-zero cost. Complex infra routes to DeepSeek Coder 6.7B.

### 5. Llama 8B for Customer Support
Support is highest-volume (3,000 heartbeats/day), shortest-response task. `llama-3.1-8b-instruct` handles structured ticket responses at $1.20/month total.

### 6. Separate NIM Keys Per Tier
Each NIM key is dedicated to one tier (Code, Content, Research). This prevents collision and allows per-key budget control and rate limiting.

---

## Self-Evolution Engine (GEPA)

The self-evolution engine runs continuously, optimizing skills and prompts based on real task performance.

```
Skill Mutation → Generate 4 variants → Judge scores them → Best wins
                         ↓
                   Human review (optional)
                         ↓
                   Deploy to production
```

- **Optimizer:** MiniMax-M2.5 — mutates prompts and skill configs
- **Judge:** Llama-3.1-70B + Nemotron-4-340B for high-stakes evaluation
- **Schedule:** Full evolution every Sunday 2am, hotfix every 4 hours if skills degrade

---

## Model Routing — How It Works

Every NIM agent has a `routing` block in its config:

```yaml
model:
  name: moonshotai/kimi-k2.5   # Primary model
routing:
  fast_model: mistralai/codestral-22b-instruct-v0.1
  fast_threshold: 8000         # If task < 8K tokens, use fast model
  complex_model: deepseek-ai/deepseek-coder-6.7b-instruct
  complex_threshold: 32000      # If task > 32K tokens, use complex model
```

**Example — SWE agent:**
- Without routing: $16.20/month
- With routing (40% simple → Codestral @ $0.30/1M): $11.45/month
- **Savings: 29%**

---

## Skills Per Role

Each agent loads only the skills it needs:

| Agent | Skills |
|-------|--------|
| CEO | `plan`, `writing-plans`, `subagent-driven-development`, `github-pr-workflow`, `github-issues`, `memory` |
| CTO | `github-pr-workflow`, `github-code-review`, `test-driven-development`, `systematic-debugging`, `codebase-inspection` |
| SWE | `github-pr-workflow`, `test-driven-development`, `systematic-debugging`, `requesting-code-review`, `subagent-driven-development` |
| Content Writer | `xurl`, `youtube-content`, `ascii-art`, `blogwatcher`, `popular-web-designs` |
| Data Scientist | `jupyter-live-kernel`, `arxiv`, `polymarket`, `weights-and-biases`, `maps` |
| DevOps | `github-repo-management`, `github-pr-workflow` |

Full skill list: see `worker-configs/*/config.yaml`

---

## Rate Limits & Cost Management

| Key | Provider | Rate Limit | Budget |
|-----|----------|------------|--------|
| Key 1 | MiniMax Official | Tier depends on account | $11/month |
| Key 2 | NVIDIA NIM | ~100 req/min | $72/month |
| Key 3 | NVIDIA NIM | ~100 req/min | $35/month |
| Key 4 | NVIDIA NIM | ~100 req/min | $54/month |

---

## Deployment Requirements

- **VPS:** Hetzner AX41-NVMe (6 vCPU / 64GB RAM) — $25/month
- **Storage:** Cloudflare R2 (50GB) — $5/month
- **Docker:** 27 containers total (22 agents + Paperclip + Postgres + Redis + Evolution)
- **RAM usage:** ~48GB peak (each agent ~1-2GB depending on model)

---

## GitHub Integration

All agents have GitHub skills attached. They can:
- Create/read/close issues
- Submit and review PRs
- Manage repositories
- Trigger workflows

Token: stored in `~/.hermes/.env` as `GITHUB_TOKEN=jason221dev`

---

## Monitoring & Logs

```bash
# Watch all agent logs
docker-compose logs -f

# Watch specific agent
docker-compose logs -f hermes-ceo
docker-compose logs -f hermes-swe-1

# Check health
curl http://localhost:3100/api/health

# Agent status
curl http://localhost:3100/api/agents/ceo/status
```

---

## License

MIT — Use freely, customize per your company needs.

---

*Generated by Hermes Agent · April 20, 2026*
*github.com/jason221dev/autonomous-business-v3*
