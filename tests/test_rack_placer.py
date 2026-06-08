#!/usr/bin/env python3
"""
test_rack_placer.py — Unit tests for rack-aware placement logic
Run: python3 -m pytest tests/ -v
"""
import sys
import os
import json
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

# Patch STATE_FILE and LOG_FILE to temp dir before import
import rack_placer as rp


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    """Redirect state and log files to a temp directory."""
    monkeypatch.setattr(rp, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(rp, "LOG_FILE",   str(tmp_path / "placer.log"))
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def cluster():
    c = rp.Cluster()
    return c


# ─── Topology Tests ─────────────────────────────────────────────────────────

class TestTopology:
    def test_cluster_has_6_nodes(self, cluster):
        assert len(cluster.nodes) == 6

    def test_two_racks(self, cluster):
        racks = {n.rack_id for n in cluster.nodes.values()}
        assert racks == {1, 2}

    def test_three_nodes_per_rack(self, cluster):
        for rack in [1, 2]:
            assert len(cluster.nodes_in_rack(rack)) == 3

    def test_all_nodes_alive_initially(self, cluster):
        assert all(n.alive for n in cluster.nodes.values())


# ─── Placement Tests ─────────────────────────────────────────────────────────

class TestPlacement:
    def test_rf2_places_on_two_racks(self, cluster):
        locs = cluster.place_block("blk_test_0001", 2)
        racks = {cluster.nodes[l].rack_id for l in locs}
        assert len(racks) == 2, "RF=2 must span both racks"

    def test_rf3_has_exactly_3_replicas(self, cluster):
        locs = cluster.place_block("blk_test_0002", 3)
        assert len(locs) == 3

    def test_rf3_no_duplicate_nodes(self, cluster):
        locs = cluster.place_block("blk_test_0003", 3)
        assert len(set(locs)) == len(locs), "No duplicate node placements"

    def test_rf2_first_replica_on_rack1(self, cluster):
        locs = cluster.place_block("blk_test_0004", 2)
        first_rack = cluster.nodes[locs[0]].rack_id
        assert first_rack == 1, "First replica should be on rack1"

    def test_rf2_second_replica_on_rack2(self, cluster):
        locs = cluster.place_block("blk_test_0005", 2)
        second_rack = cluster.nodes[locs[1]].rack_id
        assert second_rack == 2, "Second replica should be on rack2"

    def test_blocks_registered_on_nodes(self, cluster):
        block_id = "blk_reg_test"
        locs = cluster.place_block(block_id, 2)
        for loc in locs:
            assert block_id in cluster.nodes[loc].blocks

    def test_node_usage_increases(self, cluster):
        node = list(cluster.nodes.values())[0]
        initial_usage = node.used_mb
        cluster.place_block("blk_usage_test", 2)
        assert node.used_mb == initial_usage + rp.BLOCK_SIZE_MB


# ─── File Upload Tests ────────────────────────────────────────────────────────

class TestFileUpload:
    def test_upload_creates_file_metadata(self, cluster, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello HDFS!")
        meta = cluster.upload_file(str(f), 2)
        assert "test.txt" in cluster.files
        assert meta["replication"] == 2
        assert meta["num_blocks"] >= 1

    def test_upload_nonexistent_file_raises(self, cluster):
        with pytest.raises(FileNotFoundError):
            cluster.upload_file("/no/such/file.dat", 2)

    def test_checksum_is_deterministic(self, cluster, tmp_path):
        f = tmp_path / "cksum.txt"
        f.write_text("deterministic content")
        meta1 = cluster.upload_file(str(f), 2)
        c1 = meta1["checksum"]
        # Reset and re-upload
        cluster2 = rp.Cluster()
        meta2 = cluster2.upload_file(str(f), 2)
        assert meta1["checksum"] == meta2["checksum"]


# ─── Rack Failure & Rebalance Tests ──────────────────────────────────────────

class TestFailureAndRebalance:
    def _upload_file(self, cluster, tmp_path, rf=2):
        f = tmp_path / "data.txt"
        f.write_bytes(b"x" * 1024 * 100)
        return cluster.upload_file(str(f), rf)

    def test_kill_rack_marks_nodes_dead(self, cluster, tmp_path):
        self._upload_file(cluster, tmp_path)
        cluster.kill_rack(1)
        dead = [n for n in cluster.nodes.values() if not n.alive]
        assert len(dead) == 3
        assert all(n.rack_id == 1 for n in dead)

    def test_rebalance_restores_replication(self, cluster, tmp_path):
        self._upload_file(cluster, tmp_path, rf=2)
        cluster.kill_rack(1)
        actions = cluster.rebalance()
        assert len(actions) > 0, "Should have re-replicated some blocks"

    def test_rebalanced_blocks_on_surviving_rack(self, cluster, tmp_path):
        self._upload_file(cluster, tmp_path, rf=2)
        cluster.kill_rack(1)
        cluster.rebalance()
        live = {n.name for n in cluster.live_nodes()}
        for meta in cluster.files.values():
            for blk in meta["blocks"]:
                for loc in blk["locations"]:
                    assert loc in live, f"Dead node {loc} still in block locations!"

    def test_rebalance_no_action_if_healthy(self, cluster, tmp_path):
        self._upload_file(cluster, tmp_path, rf=2)
        actions = cluster.rebalance()
        assert actions == [], "No rebalancing needed on healthy cluster"

    def test_post_rebalance_rf_maintained(self, cluster, tmp_path):
        self._upload_file(cluster, tmp_path, rf=2)
        cluster.kill_rack(1)
        cluster.rebalance()
        for meta in cluster.files.values():
            for blk in meta["blocks"]:
                assert len(blk["locations"]) == meta["replication"]


# ─── Persistence Tests ────────────────────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self, cluster, tmp_path):
        f = tmp_path / "persist.txt"
        f.write_text("persistence test")
        cluster.upload_file(str(f), 2)
        cluster.save()

        c2 = rp.Cluster()
        loaded = c2.load()
        assert loaded
        assert "persist.txt" in c2.files

    def test_load_returns_false_if_no_state(self, cluster):
        result = cluster.load()
        assert result == False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
