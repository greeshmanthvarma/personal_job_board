import tempfile
import unittest
from pathlib import Path
from applications.server import static_asset

class ReactAssetsTests(unittest.TestCase):
    def test_only_index_and_assets_are_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'assets').mkdir()
            (root/'index.html').write_text('<main>React</main>')
            (root/'assets/app.js').write_text('console.log(1)')
            self.assertEqual(static_asset(root,'/')[0], b'<main>React</main>')
            self.assertIn('javascript', static_asset(root,'/assets/app.js')[1])
            for path in ['/assets/../index.html','/assets/%2e%2e/index.html','/profile.md','/assets/missing.js']:
                self.assertIsNone(static_asset(root,path))

    def test_missing_build_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(static_asset(Path(tmp),'/'))
