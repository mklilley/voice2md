import tempfile
import unittest
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))

from voice2md.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_idempotency_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "state.sqlite3"
            s = StateStore(db)
            try:
                sha = "abc123"
                self.assertFalse(s.is_processed(sha))

                s.mark_in_progress(
                    sha,
                    Path("/tmp/a.m4a"),
                    source_mtime_ns=123,
                    source_size=456,
                    force=True,
                )
                self.assertFalse(s.is_processed(sha))
                self.assertFalse(s.allow_retry_in_progress(sha, ttl_seconds=3600))

                s.mark_processed(
                    sha,
                    archive_path=Path("/tmp/archive/a.m4a"),
                    topic_file=Path("/tmp/topic.md"),
                    codex_status="ok",
                )
                self.assertTrue(s.is_processed(sha))
                self.assertFalse(s.allow_retry_in_progress(sha, ttl_seconds=0))
            finally:
                s.close()


if __name__ == "__main__":
    unittest.main()
