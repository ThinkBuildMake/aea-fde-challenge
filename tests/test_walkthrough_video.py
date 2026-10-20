"""S42 (criterion 4, GC-2): the walkthrough video runs 3:00 to 4:00 and covers the four PRD topics."""

import struct

from tests.conftest import REPO

VIDEO = REPO / "docs" / "walkthrough.mp4"
CAPTIONS = REPO / "docs" / "walkthrough.srt"
TOPICS = ("drivers", "retrieval", "escalation", "containment")


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
    print(
        f"docs/walkthrough.mp4 runs {seconds:.1f} s ({int(seconds // 60)}:{seconds % 60:04.1f})"
    )
    assert 180.0 <= seconds <= 240.0


def test_captions_cover_the_four_topics():
    text = CAPTIONS.read_text().lower()
    for word in TOPICS:
        assert word in text
    assert "pending" not in text
    assert "ay eye" not in text
    assert "pee dee eff" not in text
