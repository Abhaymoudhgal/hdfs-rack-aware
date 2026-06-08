#!/bin/bash
# demo.sh — Full end-to-end hackathon demo
# Runs: upload → show placement → kill rack → auto-rebalance
set -e

PLACER="python3 src/rack_placer.py"
DEMO_FILE="data/sample_data.txt"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[91m'; GREEN='\033[92m'; YELLOW='\033[93m'
CYAN='\033[96m'; BOLD='\033[1m'; RESET='\033[0m'

pause() { echo -e "\n${YELLOW}▶  Press ENTER to continue…${RESET}"; read -r; }

header() {
  echo -e "\n${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo -e "  STEP $1 — $2"
  echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
}

# ─────────────────────────────────────────────────────────────────────────────
header "0" "Setup — Reset cluster + create sample file"
$PLACER reset

# Create a realistic sample file (~300 MB virtual; actual content for demo)
mkdir -p data
python3 -c "
import os, random, string
# Write 2 MB of random text (will simulate as 2 blocks of 128 MB each logically)
with open('$DEMO_FILE', 'w') as f:
    for _ in range(20000):
        f.write(''.join(random.choices(string.ascii_letters + ' ', k=100)) + '\n')
print('Sample file created:', os.path.getsize('$DEMO_FILE'), 'bytes')
"
pause

# ─────────────────────────────────────────────────────────────────────────────
header "1" "View initial cluster topology"
$PLACER status
pause

# ─────────────────────────────────────────────────────────────────────────────
header "2" "Upload file with RF=2 (rack-aware placement)"
$PLACER upload "$DEMO_FILE" --replication 2
pause

# ─────────────────────────────────────────────────────────────────────────────
header "3" "Upload second file with RF=3"
cp "$DEMO_FILE" data/config_backup.txt
$PLACER upload data/config_backup.txt --replication 3
pause

# ─────────────────────────────────────────────────────────────────────────────
header "4" "Show detailed placement for sample_data.txt"
$PLACER show-file sample_data.txt
pause

# ─────────────────────────────────────────────────────────────────────────────
header "5" "Cluster status (after uploads)"
$PLACER status
pause

# ─────────────────────────────────────────────────────────────────────────────
header "6" "SIMULATE RACK 1 FAILURE + AUTO REBALANCE"
echo -e "${RED}${BOLD}Killing Rack 1 (nodes: rack1:node1, rack1:node2, rack1:node3)…${RESET}"
$PLACER kill-rack 1
pause

# ─────────────────────────────────────────────────────────────────────────────
header "7" "Final cluster status (post-recovery)"
$PLACER status

echo -e "\n${GREEN}${BOLD}╔══════════════════════════════════════════════╗"
echo -e "║  DEMO COMPLETE  —  All blocks re-replicated  ║"
echo -e "╚══════════════════════════════════════════════╝${RESET}\n"
