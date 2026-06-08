# HDFS Rack-Aware File Placer 🗄️

> **Hackathon — Distributed Systems Track**
> Simulates HDFS rack-aware block placement across 2 racks × 3 nodes, with automatic re-replication after a full rack failure.

---

## Architecture

```
          ┌─────────────── HDFS CLUSTER ──────────────────┐
          │                                                │
          │   ┌─────── RACK 1 ────────┐  ┌── RACK 2 ────┐ │
          │   │  node1  node2  node3  │  │ node1  node2 │ │
          │   │   [B0]  [B0]          │  │  [B1]  [B1] │ │
          │   │   [B1]                │  │  [B2]  [B2] │ │
          │   └───────────────────────┘  └─────────────┘ │
          │                                                │
          │         NameNode (Block Map + Rack Table)      │
          └────────────────────────────────────────────────┘

  HDFS Rack-Aware Policy:
  ┌──────────┬──────────────────────────────────────────────────────┐
  │ Replica  │ Placement Rule                                       │
  ├──────────┼──────────────────────────────────────────────────────┤
  │  1st     │ Writer's rack (Rack 1) — least-loaded node           │
  │  2nd     │ Different rack (Rack 2) — least-loaded node          │
  │  3rd+    │ Same rack as 2nd, different node                     │
  └──────────┴──────────────────────────────────────────────────────┘
```

---

## Features

| Feature | Details |
|---|---|
| **Rack-aware placement** | HDFS policy: Replica 1 → Rack1, Replica 2 → Rack2, Replica 3+ → Rack2 |
| **Load balancing** | Least-loaded node selection per rack |
| **Rack failure simulation** | Kill any rack; all nodes marked dead instantly |
| **Auto rebalance** | Missing blocks re-replicated to surviving rack |
| **Persistence** | Cluster state saved to `data/hdfs_state.json` |
| **Docker Compose** | Real 6-node HDFS cluster for HDFS CLI demo |
| **Unit tests** | 20+ pytest tests covering placement, failure, recovery |

---

## Quick Start

### Option A — Python Simulator (No Docker)

```bash
# Clone
git clone https://github.com/<your-username>/hdfs-rack-aware.git
cd hdfs-rack-aware

# Install test deps
pip install -r requirements.txt

# Run the full demo
chmod +x demo.sh
./demo.sh
```

### Option B — Real HDFS via Docker Compose

```bash
# Start the cluster (NameNode + 6 DataNodes)
docker compose up -d

# Wait ~60s for all nodes to register
docker exec hdfs_namenode hdfs dfsadmin -report

# Run the HDFS CLI demo
chmod +x scripts/hdfs_demo.sh
./scripts/hdfs_demo.sh
```

---

## CLI Reference

```bash
python3 src/rack_placer.py <command> [options]
```

| Command | Description |
|---|---|
| `status` | Show live cluster topology + stored files |
| `upload <file> [-r RF]` | Upload file with rack-aware block placement |
| `show-file <filename>` | Show all block locations for a file |
| `kill-rack <1\|2>` | Simulate full rack failure + trigger rebalance |
| `reset` | Clear all cluster state |

### Examples

```bash
# Upload a 256 MB file with RF=2
python3 src/rack_placer.py upload mydata.csv --replication 2

# Upload with RF=3
python3 src/rack_placer.py upload archive.tar.gz -r 3

# See block placement
python3 src/rack_placer.py show-file mydata.csv

# Cluster health
python3 src/rack_placer.py status

# Kill Rack 1 → triggers auto-rebalance
python3 src/rack_placer.py kill-rack 1

# Kill Rack 2
python3 src/rack_placer.py kill-rack 2
```

---

## Sample Output

```
 ██╗  ██╗██████╗ ███████╗███████╗
 ...

╔══════════════════════════════════════════╗
║         CLUSTER TOPOLOGY                ║
╚══════════════════════════════════════════╝

  RACK 1  ● ONLINE
  ──────────────────────────────────────────
  ▶ rack1:node1  [████████░░░░░░░░░░░░]   512 MB / 4096 MB  (4 blocks)
  ▶ rack1:node2  [████░░░░░░░░░░░░░░░░]   256 MB / 4096 MB  (2 blocks)
  ▶ rack1:node3  [████░░░░░░░░░░░░░░░░]   256 MB / 4096 MB  (2 blocks)

  RACK 2  ● ONLINE
  ──────────────────────────────────────────
  ▶ rack2:node1  [████████░░░░░░░░░░░░]   512 MB / 4096 MB  (4 blocks)
  ▶ rack2:node2  [████░░░░░░░░░░░░░░░░]   256 MB / 4096 MB  (2 blocks)
  ▶ rack2:node3  [░░░░░░░░░░░░░░░░░░░░]     0 MB / 4096 MB  (0 blocks)
```

---

## Running Tests

```bash
# All tests with coverage
python3 -m pytest tests/ -v --cov=src

# Specific test class
python3 -m pytest tests/ -v -k "TestFailureAndRebalance"
```

---

## Project Structure

```
hdfs-rack-aware/
├── src/
│   └── rack_placer.py       ← Core simulator + CLI
├── tests/
│   └── test_rack_placer.py  ← 20+ unit tests
├── scripts/
│   └── hdfs_demo.sh         ← Real HDFS CLI demo
├── config/
│   ├── hadoop.env           ← Hadoop config for Docker
│   └── rack_topology.sh     ← IP → rack label mapping
├── data/                    ← State + sample files (git-ignored)
├── logs/                    ← Operation log (git-ignored)
├── .github/workflows/ci.yml ← GitHub Actions CI
├── docker-compose.yml       ← 6-node HDFS cluster
├── demo.sh                  ← End-to-end demo
├── requirements.txt
└── README.md
```

---

## How Rack-Aware Placement Works

```
File: video.mp4  (256 MB → 2 blocks)  RF=2

Block 0:
  Rack 1, Node 1  ← 1st replica (writer's rack)
  Rack 2, Node 1  ← 2nd replica (off-rack)

Block 1:
  Rack 1, Node 2  ← 1st replica
  Rack 2, Node 2  ← 2nd replica

RACK 1 DIES:
  Block 0: only Rack2:Node1 alive → needs 1 more copy
  Block 1: only Rack2:Node2 alive → needs 1 more copy

AUTO-REBALANCE:
  Block 0 → new copy at Rack2:Node3
  Block 1 → new copy at Rack2:Node2 (or Node3)

  ✓ All blocks back to RF=2 on surviving rack
```

---

## Team

Built for the **Distributed Systems Hackathon** — HDFS Architecture Track.

---

## License

MIT
