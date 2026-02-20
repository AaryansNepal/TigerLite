#!/usr/bin/env bash
set -euo pipefail

# TigerLite Demo Script
# Usage: ./scripts/demo.sh

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# Check for .env file
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo -e "${YELLOW}No .env file found. Creating from .env.example...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}Please set your OPENAI_API_KEY in .env${NC}"
    fi
fi

# Clean start
echo -e "${BOLD}Step 1:${NC} Cleaning up previous containers..."
docker compose down -v 2>/dev/null || true

echo ""
echo -e "${BOLD}Step 2:${NC} Starting all services..."
docker compose up --build -d

echo ""
echo -e "${BOLD}Step 3:${NC} Waiting for services to be healthy..."

# Wait for backend health
for i in $(seq 1 60); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}Backend is healthy!${NC}"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo -e "${RED}Backend failed to start. Check logs: docker compose logs backend${NC}"
        exit 1
    fi
    sleep 2
done

echo ""
echo -e "${GREEN}${BOLD}All services are running!${NC}"
echo ""
echo -e "  ${BOLD}Dashboard:${NC}    http://localhost:5173"
echo -e "  ${BOLD}Backend API:${NC}  http://localhost:8000"
echo -e "  ${BOLD}MinIO Console:${NC} http://localhost:9001  (admin/password)"
echo ""
echo -e "${CYAN}The simulator is now generating telemetry for 10 customers.${NC}"
echo -e "${CYAN}After ~60 seconds, Wonka Industries will experience a bad deploy.${NC}"
echo ""
echo -e "${YELLOW}To trigger the bad deploy manually:${NC}"
echo -e "  curl -X POST http://localhost:8000/api/scenario/trigger-bad-deploy"
echo ""
echo -e "${YELLOW}To trigger the agent manually:${NC}"
echo -e "  curl -X POST http://localhost:8000/api/agent/run"
echo ""
echo -e "Press Ctrl+C to stop, then run: docker compose down -v"
echo ""

# Follow logs
docker compose logs -f
