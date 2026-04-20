#!/bin/bash
# ============================================================
# Quick-Start — Deploy Full 22-Role AI Company in 5 Minutes
# ============================================================

set -e

echo "╔══════════════════════════════════════════════════════╗"
echo "║   Autonomous Business — Quick Start                ║"
echo "║   22 AI Agents · Paperclip · Hermes · MiniMax     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Check prerequisites ──────────────────────────────────────
echo "[1/5] Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "  ✗ Docker not found. Install Docker first."; exit 1; }
command -v docker-compose >/dev/null 2>&1 || { echo "  ✗ docker-compose not found."; exit 1; }
echo "  ✓ Docker & docker-compose found"

# ── Setup environment ────────────────────────────────────────
echo ""
echo "[2/5] Setting up environment..."
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "  ✓ Created .env from .env.example"
  echo ""
  echo "  ⚠  IMPORTANT: Edit .env and add your API keys:"
  echo "     - MINIMAX_API_KEY"
  echo "     - NVIDIA_NIM_KEY_2, NVIDIA_NIM_KEY_3, NVIDIA_NIM_KEY_4"
  echo "     - GITHUB_TOKEN"
  echo ""
  echo "  Press Enter when ready..."
  read -r
else
  echo "  ✓ .env already exists"
fi

# Validate keys are set
source .env
MISSING=""
[ -z "$MINIMAX_API_KEY" ] && MISSING="$MISSING MINIMAX_API_KEY"
[ -z "$NVIDIA_NIM_KEY_2" ] && MISSING="$MISSING NVIDIA_NIM_KEY_2"
[ -z "$NVIDIA_NIM_KEY_3" ] && MISSING="$MISSING NVIDIA_NIM_KEY_3"
[ -z "$NVIDIA_NIM_KEY_4" ] && MISSING="$MISSING NVIDIA_NIM_KEY_4"

if [ -n "$MISSING" ]; then
  echo "  ✗ Missing keys:$MISSING"
  echo "  Please edit .env and add all required API keys."
  exit 1
fi
echo "  ✓ All API keys present"

# ── Build Docker images ──────────────────────────────────────
echo ""
echo "[3/5] Building Docker images (first run ~5-10 min)..."
docker-compose build --parallel
echo "  ✓ Images built"

# ── Start services ───────────────────────────────────────────
echo ""
echo "[4/5] Starting services..."
docker-compose up -d
echo "  ✓ Services started"

# ── Verify ───────────────────────────────────────────────────
echo ""
echo "[5/5] Verifying deployment..."
sleep 10
PAPERCLIP_URL="${PAPERCLIP_API_URL:-http://localhost:3100/api}"
if curl -sf "$PAPERCLIP_URL/health" > /dev/null 2>&1; then
  echo "  ✓ Paperclip API is healthy"
else
  echo "  ⚠ Paperclip not responding yet — may take 30s more"
fi

RUNNING=$(docker-compose ps --services --filter "status=running" 2>/dev/null | wc -l)
TOTAL=$(docker-compose ps --services 2>/dev/null | wc -l)
echo "  ✓ $RUNNING/$TOTAL containers running"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   ✓ Deployment complete!                            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Dashboard: http://localhost:3100"
echo ""
echo "Key containers:"
echo "  docker-compose logs -f hermes-ceo     # Watch CEO"
echo "  docker-compose logs -f hermes-swe-1   # Watch SWE-1"
echo "  docker-compose logs -f paperclip       # Watch orchestrator"
echo ""
echo "Run bootstrap to create company structure:"
echo "  ./scripts/bootstrap.sh"
echo ""
