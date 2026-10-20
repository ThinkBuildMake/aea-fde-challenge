"""S42 (criterion 4, GC-2): the walkthrough video runs 3:00 to 4:00 and covers the four PRD topics."""

import struct

import yaml

from tests.conftest import REPO

VIDEO = REPO / "docs" / "walkthrough.mp4"
SHOTLIST = REPO / ".demo" / "shotlist.yaml"
TOPICS = {
    "drivers": "drivers",
    "retrieval": "retrieval",
    "escalation": "escalation",
    "eval-numbers": "containment",
}


def mp4_duration(data: bytes) -> float:
    """Seconds from the movie header ('mvhd') inside the 'moov' box."""
    at = data.index(b"mvhd") + 4
    version = data[at]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", data[at + 20 : at + 32])
    else:
        timescale, duration = struct.unpack(">II", data[at + 12 : at + 20])
    return duration / timescale


def test_video_runs_three_to_four_minutes():
    seconds = mp4_duration(VIDEO.read_bytes())
    print(f"docs/walkthrough.mp4 runs {seconds:.1f} s ({int(seconds // 60)}:{seconds % 60:04.1f})")
    assert 180.0 <= seconds <= 240.0


def test_shotlist_covers_the_four_topics():
    scenes = {s["id"]: s for s in yaml.safe_load(SHOTLIST.read_text())["scenes"]}
    for scene_id, word in TOPICS.items():
        narration = " ".join(scenes[scene_id]["narration"].split())
        print(f"{scene_id}: {narration[:90]}...")
        assert word in narration.lower()
        assert "PENDING" not in narration
