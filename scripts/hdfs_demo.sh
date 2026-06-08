#!/bin/bash
# hdfs_demo.sh
# Runs actual HDFS CLI commands against the Docker Compose cluster.
# Prerequisites: docker compose up -d (wait for NameNode to be ready)

set -e

NAMENODE_CONTAINER="hdfs_namenode"
RED='\033[91m'; GREEN='\033[92m'; YELLOW='\033[93m'
CYAN='\033[96m'; BOLD='\033[1m'; RESET='\033[0m'

exec_nn() { docker exec -u root "$NAMENODE_CONTAINER" bash -c "$1"; }

wait_for_hdfs() {
  echo -e "${YELLOW}Waiting for HDFS NameNode to be ready…${RESET}"
  for i in $(seq 1 30); do
    if exec_nn "hdfs dfsadmin -report 2>/dev/null | grep -q 'Live datanodes'" 2>/dev/null; then
      echo -e "${GREEN}✓ HDFS ready!${RESET}"
      return 0
    fi
    echo -n "."
    sleep 5
  done
  echo -e "${RED}HDFS did not become ready in time.${RESET}"
  exit 1
}

header() {
  echo -e "\n${BOLD}${CYAN}═══════════════════════════════════════════"
  echo -e "  $1"
  echo -e "═══════════════════════════════════════════${RESET}\n"
}

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 1 — Cluster Report"
wait_for_hdfs
exec_nn "hdfs dfsadmin -report"

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 2 — Create test file + Upload to HDFS"
exec_nn "dd if=/dev/urandom bs=1M count=256 2>/dev/null | base64 > /tmp/testfile_256mb.txt"
exec_nn "hdfs dfs -mkdir -p /user/hackathon/data"
exec_nn "hdfs dfs -D dfs.replication=2 -put /tmp/testfile_256mb.txt /user/hackathon/data/"
echo -e "${GREEN}File uploaded with RF=2${RESET}"

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 3 — Show block locations (HDFS rack-aware placement)"
exec_nn "hdfs fsck /user/hackathon/data/testfile_256mb.txt -files -blocks -racks"

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 4 — Simulate Rack 1 failure (stop rack1 DataNodes)"
echo -e "${RED}Stopping rack1 DataNodes…${RESET}"
docker stop hdfs_r1n1 hdfs_r1n2 hdfs_r1n3 || true
echo -e "${YELLOW}Waiting 15s for NameNode to detect failures…${RESET}"
sleep 15

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 5 — Cluster report after rack failure"
exec_nn "hdfs dfsadmin -report"

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 6 — Check block health (under-replicated)"
exec_nn "hdfs fsck /user/hackathon/data/testfile_256mb.txt -files -blocks -racks" || true
echo -e "${YELLOW}Waiting for HDFS to auto-re-replicate…${RESET}"
sleep 30

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 7 — Post-recovery block report"
exec_nn "hdfs fsck /user/hackathon/data/testfile_256mb.txt -files -blocks -racks"
exec_nn "hdfs dfsadmin -report"

echo -e "\n${GREEN}${BOLD}HDFS CLI demo complete!${RESET}\n"
