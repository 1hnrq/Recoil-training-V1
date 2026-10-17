import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from check_brand_icon import ico_frames, SIZES


class BrandIconTests(unittest.TestCase):
    def test_all_seven_rgba_resolutions_are_present(self):
        frames = ico_frames(ROOT / 'assets/branding/r6-rebuild.ico')
        self.assertEqual(tuple(sorted(frames)), SIZES)
        for frame in frames.values():
            self.assertEqual(frame[24:26], bytes([8, 6]))  # PNG: 8-bit RGBA

    def test_window_uses_explicit_brand_icon(self):
        tree = ast.parse((ROOT / 'src/r6_rebuild/desktop.py').read_text(encoding='utf-8'))
        starts = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and isinstance(n.func.value, ast.Name) and n.func.value.id == 'webview' and n.func.attr == 'start']
        self.assertEqual(len(starts), 1)
        keyword = next(k for k in starts[0].keywords if k.arg == 'icon')
        self.assertIn('assets/branding/r6-rebuild.ico', ast.unparse(keyword.value))

    def test_spec_embeds_only_final_icon_not_source_art(self):
        spec = (ROOT / 'packaging/R6-Rebuild.spec').read_text(encoding='utf-8')
        self.assertIn("icon=str(root / 'assets/branding/r6-rebuild.ico')", spec)
        self.assertIn("'assets/branding'),", spec)
        self.assertNotIn('logomouse.png', spec)
