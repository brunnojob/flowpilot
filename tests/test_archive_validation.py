import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from flowpilot.steps.archive import archive
from flowpilot.errors import StepConfigError


class ArchiveValidationTests(unittest.TestCase):
    def test_validation_precedes_filesystem_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text("content")
            context = SimpleNamespace(resolve_path=lambda value: root / value, log=logging.getLogger("test"))
            for options in ({"prefix": "../escape"}, {"prefix": "*"}, {"keep": 1.5}, {"keep": True}, {"keep": 0}):
                with self.assertRaises(StepConfigError):
                    archive(context, "source.txt", "backups", **options)
                self.assertFalse((root / "backups").exists())
            result = archive(context, "source.txt", "backups", prefix="source", keep=2)
            self.assertEqual(result["files"], 1)
            self.assertTrue(Path(result["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
