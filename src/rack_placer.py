#!/usr/bin/env python3
"""
rack_placer.py — Rack-Aware HDFS File Placement Simulator
Simulates HDFS block placement with rack-awareness to survive full rack failure.
"""

import os
import sys
import json
import math
import hashlib
import argparse
import random
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ─── ANSI Colors ────────────────────────────────────────────────────────────
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    DIM     = "\033[2m"

# ─── Constants ───────────────────────────────────────────────────────────────
BLOCK_SIZE_MB   = 128          # HDFS default block size
STATE_FILE      = "data/hdfs_state.json"
LOG_FILE        = "logs/placer.log"


# ─── Logging ─────────────────────────────────────────────────────────────────
def log(msg: str):
    os.makedirs("logs", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


# ─── Topology ────────────────────────────────────────────────────────────────
class Node:
    def __init__(self, rack_id: int, node_id: int):
        self.rack_id  = rack_id
        self.node_id  = node_id
        self.name     = f"rack{rack_id}:node{node_id}"
        self.alive    = True
        self.blocks: List[str] = []      # block IDs stored on this node
        self.used_mb  = 0
        self.total_mb = 4096             # 4 GB per node

    def to_dict(self) -> dict:
        return {
            "rack_id":  self.rack_id,
            "node_id":  self.node_id,
            "name":     self.name,
            "alive":    self.alive,
            "blocks":   self.blocks,
            "used_mb":  self.used_mb,
            "total_mb": self.total_mb,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        n = cls(d["rack_id"], d["node_id"])
        n.alive    = d["alive"]
        n.blocks   = d["blocks"]
        n.used_mb  = d["used_mb"]
        n.total_mb = d["total_mb"]
        return n


class Cluster:
    """2 racks × 3 nodes each = 6 nodes total."""

    NUM_RACKS     = 2
    NODES_PER_RACK = 3

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.files: Dict[str, dict] = {}   # filename → file metadata
        self._init_nodes()

    # ── init ──────────────────────────────────────────────────────────────────
    def _init_nodes(self):
        for r in range(1, self.NUM_RACKS + 1):
            for n in range(1, self.NODES_PER_RACK + 1):
                node = Node(r, n)
                self.nodes[node.name] = node

    # ── persistence ───────────────────────────────────────────────────────────
    def save(self):
        os.makedirs("data", exist_ok=True)
        state = {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "files": self.files,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def load(self) -> bool:
        if not os.path.exists(STATE_FILE):
            return False
        with open(STATE_FILE) as f:
            state = json.load(f)
        self.nodes = {k: Node.from_dict(v) for k, v in state["nodes"].items()}
        self.files = state["files"]
        return True

    # ── helpers ───────────────────────────────────────────────────────────────
    def live_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.alive]

    def live_racks(self) -> List[int]:
        return sorted({n.rack_id for n in self.live_nodes()})

    def nodes_in_rack(self, rack_id: int, alive_only=True) -> List[Node]:
        return [
            n for n in self.nodes.values()
            if n.rack_id == rack_id and (not alive_only or n.alive)
        ]

    # ── rack-aware placement ──────────────────────────────────────────────────
    def place_block(self, block_id: str, replication: int) -> List[str]:
        """
        HDFS rack-aware policy:
          - 1st replica  → writer's rack  (rack1, least-loaded node)
          - 2nd replica  → different rack (rack2, least-loaded node)
          - 3rd+ replicas→ same rack as 2nd, different node (or random if RF>3)
        Returns list of node names where block is placed.
        """
        live_rack_ids = self.live_racks()
        if len(live_rack_ids) < 2:
            raise RuntimeError(
                "Only one rack alive — cannot satisfy rack-aware placement!"
            )

        placed: List[str] = []

        # Sort nodes by used_mb (least-loaded first)
        def best_node(rack_id: int, exclude: List[str]) -> Optional[Node]:
            candidates = [
                n for n in self.nodes_in_rack(rack_id)
                if n.name not in exclude
                and n.used_mb + BLOCK_SIZE_MB <= n.total_mb
            ]
            return min(candidates, key=lambda n: n.used_mb) if candidates else None

        rack1_id = live_rack_ids[0]
        rack2_id = live_rack_ids[1]

        # Replica 1 — rack1
        n1 = best_node(rack1_id, placed)
        if not n1:
            raise RuntimeError(f"No space on rack {rack1_id}")
        placed.append(n1.name)

        # Replica 2 — rack2
        n2 = best_node(rack2_id, placed)
        if not n2:
            raise RuntimeError(f"No space on rack {rack2_id}")
        placed.append(n2.name)

        # Replicas 3+ — same rack as replica 2, different node
        for _ in range(replication - 2):
            n_extra = best_node(rack2_id, placed) or best_node(rack1_id, placed)
            if not n_extra:
                raise RuntimeError("Not enough nodes for requested replication factor")
            placed.append(n_extra.name)

        # Commit
        for node_name in placed:
            node = self.nodes[node_name]
            node.blocks.append(block_id)
            node.used_mb += BLOCK_SIZE_MB

        return placed

    # ── file upload ───────────────────────────────────────────────────────────
    def upload_file(self, filepath: str, replication: int) -> dict:
        path    = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        size_bytes = path.stat().st_size
        size_mb    = size_bytes / (1024 * 1024)
        num_blocks = max(1, math.ceil(size_mb / BLOCK_SIZE_MB))

        # Checksum for block IDs
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()[:12]

        blocks_info: List[dict] = []
        for i in range(num_blocks):
            block_id  = f"blk_{sha256}_{i:04d}"
            locations = self.place_block(block_id, replication)
            blocks_info.append({"block_id": block_id, "locations": locations})

        file_meta = {
            "filename":    path.name,
            "filepath":    str(path),
            "size_bytes":  size_bytes,
            "size_mb":     round(size_mb, 2),
            "num_blocks":  num_blocks,
            "replication": replication,
            "checksum":    sha256,
            "uploaded_at": datetime.now().isoformat(),
            "blocks":      blocks_info,
        }
        self.files[path.name] = file_meta
        log(f"UPLOAD {path.name} | {num_blocks} blocks | RF={replication} | sha256={sha256}")
        return file_meta

    # ── rack failure ──────────────────────────────────────────────────────────
    def kill_rack(self, rack_id: int):
        killed = []
        for node in self.nodes_in_rack(rack_id, alive_only=False):
            node.alive = False
            killed.append(node.name)
        log(f"RACK_FAILURE rack{rack_id}: nodes {killed} marked dead")
        return killed

    # ── rebalance / re-replicate ──────────────────────────────────────────────
    def rebalance(self) -> List[dict]:
        """
        Find blocks with under-replication (some replicas on dead nodes).
        Re-replicate each under-replicated block to a live node not already hosting it.
        Returns list of recovery actions.
        """
        actions = []
        live_node_set = {n.name for n in self.live_nodes()}

        for filename, file_meta in self.files.items():
            target_rf = file_meta["replication"]
            for block in file_meta["blocks"]:
                block_id = block["block_id"]
                alive_locs = [l for l in block["locations"] if l in live_node_set]
                dead_locs  = [l for l in block["locations"] if l not in live_node_set]

                needed = target_rf - len(alive_locs)
                if needed <= 0:
                    continue

                # Find live nodes not already hosting this block, spread across racks
                # Rack-aware: prefer different rack from existing alive replicas
                existing_racks = {self.nodes[l].rack_id for l in alive_locs}
                candidates = sorted(
                    [
                        n for n in self.live_nodes()
                        if n.name not in alive_locs
                        and n.used_mb + BLOCK_SIZE_MB <= n.total_mb
                    ],
                    key=lambda n: (
                        1 if n.rack_id in existing_racks else 0,  # prefer new rack
                        n.used_mb,
                    ),
                )

                new_locs = []
                for node in candidates[:needed]:
                    node.blocks.append(block_id)
                    node.used_mb += BLOCK_SIZE_MB
                    alive_locs.append(node.name)
                    new_locs.append(node.name)

                block["locations"] = alive_locs
                action = {
                    "block_id":   block_id,
                    "filename":   filename,
                    "dead_locs":  dead_locs,
                    "new_locs":   new_locs,
                    "final_locs": alive_locs,
                }
                actions.append(action)
                log(f"REBALANCE {block_id}: dead={dead_locs} -> new={new_locs}")

        return actions


# ─── Pretty Printers ─────────────────────────────────────────────────────────

def banner():
    print(f"""
{C.CYAN}{C.BOLD}
 ██╗  ██╗██████╗ ███████╗███████╗
 ██║  ██║██╔══██╗██╔════╝██╔════╝
 ███████║██║  ██║█████╗  ███████╗
 ██╔══██║██║  ██║██╔══╝  ╚════██║
 ██║  ██║██████╔╝██║     ███████║
 ╚═╝  ╚═╝╚═════╝ ╚═╝     ╚══════╝

 {C.YELLOW}Rack-Aware File Placement Simulator{C.RESET}
 {C.DIM}Hackathon — Distributed Systems Track{C.RESET}
""")


def print_cluster(cluster: Cluster):
    print(f"\n{C.BOLD}{C.BLUE}╔══════════════════════════════════════════╗")
    print(f"║         CLUSTER TOPOLOGY                ║")
    print(f"╚══════════════════════════════════════════╝{C.RESET}")

    for rack_id in range(1, Cluster.NUM_RACKS + 1):
        rack_nodes = [n for n in cluster.nodes.values() if n.rack_id == rack_id]
        rack_alive = any(n.alive for n in rack_nodes)
        status = f"{C.GREEN}● ONLINE{C.RESET}" if rack_alive else f"{C.RED}✖ DEAD{C.RESET}"
        print(f"\n  {C.BOLD}RACK {rack_id}{C.RESET}  {status}")
        print(f"  {'─'*42}")
        for node in rack_nodes:
            icon   = f"{C.GREEN}▶{C.RESET}" if node.alive else f"{C.RED}✖{C.RESET}"
            pct    = int(node.used_mb / node.total_mb * 100)
            bar    = "█" * (pct // 5) + "░" * (20 - pct // 5)
            blocks = len(node.blocks)
            print(
                f"  {icon} {C.CYAN}{node.name:<16}{C.RESET} "
                f"[{C.YELLOW}{bar}{C.RESET}] "
                f"{node.used_mb:>5} MB / {node.total_mb} MB  "
                f"{C.DIM}({blocks} blocks){C.RESET}"
            )
    print()


def print_file_placement(file_meta: dict):
    print(f"\n{C.BOLD}{C.GREEN}╔══════════════════════════════════════════════════╗")
    print(f"║   FILE PLACEMENT REPORT                          ║")
    print(f"╚══════════════════════════════════════════════════╝{C.RESET}")
    print(f"  {C.BOLD}File      :{C.RESET} {file_meta['filename']}")
    print(f"  {C.BOLD}Size      :{C.RESET} {file_meta['size_mb']} MB  ({file_meta['size_bytes']:,} bytes)")
    print(f"  {C.BOLD}Blocks    :{C.RESET} {file_meta['num_blocks']}  ×  {BLOCK_SIZE_MB} MB")
    print(f"  {C.BOLD}Replication:{C.RESET} {file_meta['replication']}×")
    print(f"  {C.BOLD}Checksum  :{C.RESET} {C.DIM}{file_meta['checksum']}{C.RESET}")
    print(f"  {C.BOLD}Uploaded  :{C.RESET} {file_meta['uploaded_at']}")
    print(f"\n  {C.BOLD}Block Locations:{C.RESET}")
    print(f"  {'─'*52}")

    for i, blk in enumerate(file_meta["blocks"]):
        locs_str = "  ".join(
            f"{C.CYAN}{l}{C.RESET}" for l in blk["locations"]
        )
        racks = sorted({l.split(":")[0] for l in blk["locations"]})
        rack_tag = f"{C.GREEN}[✓ {','.join(racks)}]{C.RESET}"
        print(f"  Block {i:>3}  {C.DIM}{blk['block_id'][:20]}…{C.RESET}")
        print(f"           → {locs_str}  {rack_tag}")

    # Rack-survival summary
    racks_used = set()
    for blk in file_meta["blocks"]:
        for l in blk["locations"]:
            racks_used.add(l.split(":")[0])
    survival = f"{C.GREEN}✓ Survives full rack failure{C.RESET}" if len(racks_used) >= 2 else f"{C.RED}✗ SINGLE RACK — no fault tolerance!{C.RESET}"
    print(f"\n  Rack Coverage : {' + '.join(sorted(racks_used))}")
    print(f"  Fault Tolerance: {survival}\n")


def print_rebalance(actions: List[dict]):
    if not actions:
        print(f"\n  {C.GREEN}✓ All blocks healthy — no rebalancing needed.{C.RESET}\n")
        return

    print(f"\n{C.BOLD}{C.YELLOW}╔══════════════════════════════════════════════════╗")
    print(f"║   REBALANCE / RE-REPLICATION REPORT             ║")
    print(f"╚══════════════════════════════════════════════════╝{C.RESET}")
    print(f"  {len(actions)} block(s) required re-replication:\n")

    for a in actions:
        dead_str = "  ".join(f"{C.RED}{l}{C.RESET}" for l in a["dead_locs"])
        new_str  = "  ".join(f"{C.GREEN}{l}{C.RESET}" for l in a["new_locs"])
        fin_str  = "  ".join(f"{C.CYAN}{l}{C.RESET}" for l in a["final_locs"])
        print(f"  {C.BOLD}{a['block_id'][:24]}…{C.RESET}  [{a['filename']}]")
        print(f"    Dead replicas : {dead_str}")
        print(f"    New  replicas : {new_str}")
        print(f"    Final locs    : {fin_str}")
        print()


# ─── CLI Commands ────────────────────────────────────────────────────────────

def cmd_status(cluster: Cluster, _args):
    print_cluster(cluster)
    if cluster.files:
        print(f"{C.BOLD}Stored Files:{C.RESET}")
        for fname, meta in cluster.files.items():
            rf = meta["replication"]
            nb = meta["num_blocks"]
            print(f"  {C.CYAN}{fname}{C.RESET}  {meta['size_mb']} MB  {nb} block(s)  RF={rf}")
    else:
        print(f"  {C.DIM}No files uploaded yet.{C.RESET}")
    print()


def cmd_upload(cluster: Cluster, args):
    rf = args.replication
    print(f"\n{C.BOLD}Uploading{C.RESET} {C.CYAN}{args.file}{C.RESET}  RF={rf} …\n")
    try:
        meta = cluster.upload_file(args.file, rf)
        print_cluster(cluster)
        print_file_placement(meta)
        cluster.save()
    except Exception as e:
        print(f"{C.RED}Error: {e}{C.RESET}")
        sys.exit(1)


def cmd_kill_rack(cluster: Cluster, args):
    rack_id = args.rack_id
    print(f"\n{C.RED}{C.BOLD}⚠  SIMULATING RACK {rack_id} FAILURE …{C.RESET}\n")
    time.sleep(0.5)
    killed = cluster.kill_rack(rack_id)
    print(f"  Killed nodes: {', '.join(f'{C.RED}{k}{C.RESET}' for k in killed)}\n")
    print_cluster(cluster)

    print(f"\n{C.YELLOW}{C.BOLD}▶  Running automatic re-replication …{C.RESET}\n")
    time.sleep(0.5)
    actions = cluster.rebalance()
    print_rebalance(actions)
    print_cluster(cluster)
    cluster.save()


def cmd_show_file(cluster: Cluster, args):
    fname = args.filename
    if fname not in cluster.files:
        print(f"{C.RED}File '{fname}' not found in namespace.{C.RESET}")
        sys.exit(1)
    print_file_placement(cluster.files[fname])


def cmd_reset(cluster: Cluster, _args):
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    print(f"{C.GREEN}Cluster state reset.{C.RESET}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    banner()

    parser = argparse.ArgumentParser(
        prog="rack_placer",
        description="Rack-Aware HDFS File Placement Simulator",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub.add_parser("status", help="Show cluster topology and stored files")

    # upload
    p_up = sub.add_parser("upload", help="Upload a file with rack-aware placement")
    p_up.add_argument("file",        help="Path to local file to upload")
    p_up.add_argument("-r", "--replication", type=int, default=2,
                      help="Replication factor (default: 2)")

    # kill-rack
    p_kill = sub.add_parser("kill-rack", help="Simulate full rack failure + rebalance")
    p_kill.add_argument("rack_id", type=int, choices=[1, 2], help="Rack to kill (1 or 2)")

    # show-file
    p_sf = sub.add_parser("show-file", help="Show block placement of a specific file")
    p_sf.add_argument("filename", help="Filename (as stored)")

    # reset
    sub.add_parser("reset", help="Reset cluster state")

    args = parser.parse_args()

    cluster = Cluster()
    cluster.load()

    dispatch = {
        "status":    cmd_status,
        "upload":    cmd_upload,
        "kill-rack": cmd_kill_rack,
        "show-file": cmd_show_file,
        "reset":     cmd_reset,
    }
    dispatch[args.command](cluster, args)


if __name__ == "__main__":
    main()
