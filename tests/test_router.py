import unittest
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from voice2md.router import decide_route


class RouterTests(unittest.TestCase):
    def test_filename_wins_when_present(self) -> None:
        audio = Path("2025-12-29 Spin notes.m4a")
        transcript = "hello\nTOPIC: Something else\nThis proves the point.\nbye"
        decision = decide_route(audio_path=audio, transcript=transcript)
        self.assertEqual(decision.topic, "Spin notes")
        self.assertEqual(decision.mode, "claims")
        self.assertEqual(decision.topic_source, "filename")
        self.assertEqual(decision.mode_source, "inferred")

    def test_infers_topic_when_filename_missing(self) -> None:
        audio = Path("random_recording.m4a")
        transcript = "This is about Quantum Spin measurement."
        decision = decide_route(audio_path=audio, transcript=transcript)
        self.assertEqual(decision.topic, "Quantum Spin measurement")
        self.assertEqual(decision.mode, "brainstorming")
        self.assertEqual(decision.topic_source, "inferred")
        self.assertEqual(decision.mode_source, "inferred")


if __name__ == "__main__":
    unittest.main()
