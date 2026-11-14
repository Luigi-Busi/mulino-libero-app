"""Run the actual Apps Script under Node, also available in Playwright's driver.

Included in the existing offline deployment unittest discovery; no Sheets access.
"""
from pathlib import Path
import shutil
import subprocess
import unittest


class EmailMatcherTests(unittest.TestCase):
    def test_apps_script_regressions(self):
        node = shutil.which("node")
        if not node:
            import playwright
            node = str(Path(playwright.__file__).parent / "driver" / "node")
        result = subprocess.run(
            [node, str(Path(__file__).with_name("emailmatcher.test.cjs"))],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
