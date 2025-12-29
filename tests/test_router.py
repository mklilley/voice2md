import unittest
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from voice2md.router import decide_route


class RouterTests(unittest.TestCase):
    def test_transcript_tokens_win(self) -> None:
        audio = Path("2025-12-29__Ignored__claims.m4a")
        transcript = "hello\nTOPIC: Spin\nMODE: brainstorming\nbye"
        decision = decide_route(audio_path=audio, transcript=transcript, inbox_topic="INBOX")
        self.assertEqual(decision.topic, "Spin")
        self.assertEqual(decision.mode, "brainstorming")
        self.assertEqual(decision.topic_source, "transcript")
        self.assertEqual(decision.mode_source, "transcript")

    def test_filename_fallback(self) -> None:
        audio = Path("2025-12-29__Spin__claims.m4a")
        transcript = "no tokens here"
        decision = decide_route(audio_path=audio, transcript=transcript, inbox_topic="INBOX")
        self.assertEqual(decision.topic, "Spin")
        self.assertEqual(decision.mode, "claims")
        self.assertEqual(decision.topic_source, "filename")
        self.assertEqual(decision.mode_source, "filename")

    def test_inbox_fallback(self) -> None:
        audio = Path("random_recording.m4a")
        transcript = "no tokens here"
        decision = decide_route(audio_path=audio, transcript=transcript, inbox_topic="INBOX")
        self.assertEqual(decision.topic, "INBOX")
        self.assertEqual(decision.mode, "unspecified")
        self.assertEqual(decision.topic_source, "fallback")
        self.assertEqual(decision.mode_source, "fallback")


if __name__ == "__main__":
    unittest.main()
