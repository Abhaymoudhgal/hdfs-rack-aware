# HDFS Rack-Aware File Placer

A Python-based simulation of HDFS rack-aware block placement and replication.

This project demonstrates how HDFS places replicas across multiple racks to improve fault tolerance and automatically re-replicates blocks after a rack failure.

## Problem Statement

Design a custom file uploader that:

* Accepts a file and replication factor.
* Places replicas across two simulated racks (3 nodes per rack).
* Survives a complete rack failure.
* Automatically restores replication through re-replication.
* Displays block placement and recovery information through a CLI.

## Features

* Rack-aware replica placement
* Two racks with three nodes each
* Configurable replication factor
* Load-balanced node selection
* Full rack failure simulation
* Automatic block re-replication
* Persistent cluster state
* Command-line interface
* Comprehensive unit tests

## Cluster Topology

```text
RACK 1
 ├── rack1:node1
 ├── rack1:node2
 └── rack1:node3

RACK 2
 ├── rack2:node1
 ├── rack2:node2
 └── rack2:node3
```

## Placement Policy

Replication Factor = 2

```text
Replica 1 → Rack 1
Replica 2 → Rack 2
```

Replication Factor = 3

```text
Replica 1 → Rack 1
Replica 2 → Rack 2
Replica 3 → Different node on Rack 2
```

This ensures that data survives the failure of an entire rack.

## Installation

```bash
git clone https://github.com/Abhaymoudhgal/hdfs-rack-aware.git

cd hdfs-rack-aware

pip install -r requirements.txt
```

## Usage

### Reset Cluster

```bash
python src/rack_placer.py reset
```

### Upload File

```bash
python src/rack_placer.py upload testfile.txt --replication 2
```

### View File Placement

```bash
python src/rack_placer.py show-file testfile.txt
```

### Simulate Rack Failure

```bash
python src/rack_placer.py kill-rack 1
```

### View Cluster Status

```bash
python src/rack_placer.py status
```

## Example Workflow

### Upload

```bash
python src/rack_placer.py upload testfile.txt --replication 2
```

Output:

```text
Block 0
→ rack1:node1
→ rack2:node1

Fault Tolerance:
✓ Survives full rack failure
```

### Rack Failure

```bash
python src/rack_placer.py kill-rack 1
```

Output:

```text
Dead replicas : rack1:node1
New replicas  : rack2:node2
Final locs    : rack2:node1 rack2:node2
```

### Verification

```bash
python src/rack_placer.py show-file testfile.txt
```

Output:

```text
Block 0
→ rack2:node1
→ rack2:node2
```

Replication factor is restored automatically.

## Running Tests

```bash
python -m pytest tests/ -v
```

Current test suite:

```text
21 passed
```

## Project Structure

```text
hdfs-rack-aware/
│
├── src/
│   └── rack_placer.py
│
├── tests/
│   └── test_rack_placer.py
│
├── data/
│   └── sample_data.txt
│
├── requirements.txt
├── README.md
└── demo.sh
```

## Technical Highlights

* Rack-aware replica placement
* Fault-tolerant storage simulation
* Re-replication after rack failure
* Persistent metadata management
* Python CLI implementation
* Automated testing

## License

MIT License
