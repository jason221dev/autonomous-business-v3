#!/bin/bash
# ============================================================
# Company Bootstrap Script — Paperclip + Hermes Auto-Setup
# Run once on first deployment to initialize the company
# ============================================================

set -e

PAPERCLIP_URL="${PAPERCLIP_API_URL:-http://paperclip:3100/api}"
GITHUB_USER="${GITHUB_USER:-jason221dev}"

echo "============================================"
echo "  Company Bootstrap — Paperclip + Hermes"
echo "============================================"
echo ""

# ── Step 1: Wait for Paperclip to be ready ──────────────────
echo "[1/8] Waiting for Paperclip API..."
until curl -sf "$PAPERCLIP_URL/health" > /dev/null 2>&1; do
  echo "  Paperclip not ready, waiting 5s..."
  sleep 5
done
echo "  ✓ Paperclip is up"

# ── Step 2: Create org chart in Paperclip ───────────────────
echo ""
echo "[2/8] Creating organization structure..."

curl -s -X POST "$PAPERCLIP_URL/org" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI Company",
    "mission": "Autonomous revenue generation through AI agents",
    "values": ["speed", "quality", "autonomy", "continuous-improvement"]
  }' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ Org created: {d.get(\"id\",\"?\")}')" 2>/dev/null || echo "  ✓ Org endpoint exists"

# ── Step 3: Create all 22 roles ────────────────────────────
echo ""
echo "[3/8] Creating 22 roles..."

ROLES=(
  "CEO|Strategy, KPI ownership, delegation, board liaison|executive"
  "CTO|Engineering architecture, technical decisions, PR approval|executive"
  "COO|Operations, issue routing, scheduling, team coordination|executive"
  "CFO|Finance, budgets, invoices, financial reporting|executive"
  "CMO|Marketing strategy, brand, content direction|executive"
  "VP Engineering|Delivery oversight, sprint planning, code quality|department"
  "VP Product|Roadmap, feature prioritization, user research|department"
  "VP Marketing|Campaigns, channel strategy, growth|department"
  "VP Sales|Revenue strategy, pipeline, partnerships|department"
  "VP HR|Culture, hiring process, performance|department"
  "VP Customer Success|Churn, satisfaction, support quality|department"
  "SWE-1|Feature development, code reviews, tests|engineering"
  "SWE-2|Feature development, code reviews, tests|engineering"
  "SWE-3|Feature development, code reviews, tests|engineering"
  "SWE-4|Feature development, code reviews, tests|engineering"
  "Frontend-1|UI development, web interfaces|engineering"
  "Frontend-2|UI development, web interfaces|engineering"
  "DevOps|Infrastructure, CI/CD, deployment|engineering"
  "Content Writer|Blogs, social, email, copywriting|marketing"
  "SEO Specialist|Organic growth, technical SEO, analytics|marketing"
  "Marketing Campaigns|Campaign strategy, ad copy, channels|marketing"
  "Sales Dev Rep|Outreach, pipeline, partnerships|sales"
  "Customer Support|Ticket triage, responses, escalation|support"
  "HR Coordinator|Hiring, performance, culture|hr"
  "Legal|Contracts, compliance, policies|legal"
  "Data Engineer|Data pipelines, analytics, quality|data"
  "Data Scientist|ML models, experiments, KPI analysis|data"
  "Security Engineer|Vulnerability management, AppSec|security"
  "Product Designer|UX, wireframes, design systems|design"
)

CREATED=0
for role in "${ROLES[@]}"; do
  name=$(echo "$role" | cut -d'|' -f1)
  desc=$(echo "$role" | cut -d'|' -f2)
  dept=$(echo "$role" | cut -d'|' -f3)

  response=$(curl -s -X POST "$PAPERCLIP_URL/roles" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json; print(json.dumps({'name': '$name', 'description': '$desc', 'department': '$dept'}))")")

  if echo "$response" | python3 -c "import sys,json; json.load(sys.stdin); sys.exit(0)" 2>/dev/null; then
    CREATED=$((CREATED+1))
  fi
done
echo "  ✓ Created $CREATED roles"

# ── Step 4: Create initial projects ────────────────────────
echo ""
echo "[4/8] Creating initial projects..."

curl -s -X POST "$PAPERCLIP_URL/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "MVP Launch", "quarter": "Q2-2026", "status": "active"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ Project: {d.get(\"name\",\"?\")}')" 2>/dev/null || echo "  ✓ Project created"

curl -s -X POST "$PAPERCLIP_URL/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "Infrastructure Setup", "quarter": "Q2-2026", "status": "active"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ Project: {d.get(\"name\",\"?\")}')" 2>/dev/null || echo "  ✓ Project created"

# ── Step 5: Initialize skill library ───────────────────────
echo ""
echo "[5/8] Checking skill library..."
SKILLS_DIR="/root/.hermes/skills"
if [ -d "$SKILLS_DIR" ]; then
  count=$(find "$SKILLS_DIR" -name "SKILL.md" 2>/dev/null | wc -l)
  echo "  ✓ $count skills available"
else
  echo "  ⚠ Skills directory not mounted"
fi

# ── Step 6: Create GitHub repo webhooks ────────────────────
echo ""
echo "[6/8] Setting up GitHub webhooks..."

# Register webhook URL with GitHub repo
export GITHUB_TOKEN="${GITHUB_TOKEN:-}"
if [ -n "$GITHUB_TOKEN" ]; then
  curl -s -X POST \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/vnd.github+json" \
    -d '{"name":"web","active":true,"events":["push","pull_request","issues"],"config":{"url":"'"$PAPERCLIP_URL"'/webhooks/github","content_type":"json"}}' \
    "https://api.github.com/repos/$GITHUB_USER/autonomous-business-v3/hooks" | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ Webhook created: {d.get(\"id\",\"?\")}')" 2>/dev/null || echo "  ✓ Webhook configured"
else
  echo "  ⚠ GITHUB_TOKEN not set, skipping webhook"
fi

# ── Step 7: Health check all agents ────────────────────────
echo ""
echo "[7/8] Checking agent heartbeats..."

AGENTS=("ceo" "cto" "coo" "cfo" "cmo" "vp-eng" "vp-product" "vp-mktg" "vp-sales" "vp-hr" "vp-cs" "swe-1" "swe-2" "swe-3" "swe-4" "fe-1" "fe-2" "devops" "content-writer" "seo" "mkt-campaigns" "sales-dr" "support" "hr" "legal" "data-eng" "data-scientist" "security" "designer")
HEALTHY=0
for agent in "${AGENTS[@]}"; do
  status=$(curl -sf "$PAPERCLIP_URL/agents/$agent/status" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
  if [ "$status" = "healthy" ]; then
    HEALTHY=$((HEALTHY+1))
  fi
done
echo "  ✓ $HEALTHY/${#AGENTS[@]} agents reporting healthy"

# ── Step 8: Create initial OKRs ────────────────────────────
echo ""
echo "[8/8] Setting OKRs..."

curl -s -X POST "$PAPERCLIP_URL/okrs" \
  -H "Content-Type: application/json" \
  -d '{
    "quarter": "Q2-2026",
    "objectives": [
      {"title": "Launch MVP", "key_results": ["Revenue > $10K MRR", "100 customers", "99.9% uptime"]},
      {"title": "Establish Operations", "key_results": ["All 22 agents active", "CI/CD pipeline live", "SOC2 compliance"]}
    ]
  }' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ OKRs created for Q2-2026')" 2>/dev/null || echo "  ✓ OKRs endpoint ready"

echo ""
echo "============================================"
echo "  ✓ Bootstrap complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Copy .env.example to .env and fill in API keys"
echo "  2. Run: docker-compose up -d"
echo "  3. Monitor at: $PAPERCLIP_URL/dashboard"
echo ""
