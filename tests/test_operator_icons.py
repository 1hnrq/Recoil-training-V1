"""Local icon coverage, provenance, passive SVG and restricted static routes."""
import hashlib
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
from tools.serve_preview import PreviewHandler

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / 'frontend/assets/operators'


class OperatorIconTests(unittest.TestCase):
    def test_all_75_ids_have_their_own_integrity_checked_icon(self):
        operators = json.loads((ROOT/'data/profiles.json').read_text(encoding='utf-8'))['operators']
        manifest = json.loads((ROOT/'docs/operator-icons.json').read_text(encoding='utf-8'))
        ids = {op['id'] for op in operators}
        self.assertEqual(len(ids), 75)
        self.assertEqual(ids, {item['id'] for item in manifest['files']})
        self.assertEqual(ids, {file.stem for file in ICONS.glob('*.svg')})
        hashes = set()
        for item in manifest['files']:
            with self.subTest(operator=item['id']):
                payload = (ICONS/(item['id']+'.svg')).read_bytes()
                self.assertEqual(len(payload), item['bytes'])
                actual = hashlib.sha256(payload).hexdigest()
                self.assertEqual(actual, item['sha256'])
                hashes.add(actual)
        self.assertEqual(len(hashes), 75)

    def test_svg_files_are_passive_images_without_external_dependencies(self):
        for path in ICONS.glob('*.svg'):
            with self.subTest(operator=path.stem):
                svg = path.read_text(encoding='utf-8')
                self.assertNotRegex(svg, r'(?i)<!DOCTYPE|<!ENTITY|<script|<foreignObject|<image|<iframe')
                self.assertNotRegex(svg, r'(?i)javascript:|@import|data:|\\bon[a-z]+\\s*=')
                document = ET.fromstring(svg)
                self.assertEqual(document.tag, '{http://www.w3.org/2000/svg}svg')
                # Upstream uses 204-square for two updated icons and 350 for others.
                x, y, width, height = map(float, document.attrib['viewBox'].split())
                self.assertEqual((x, y), (0, 0))
                self.assertGreater(width, 0)
                self.assertEqual(width, height)
                for element in document.iter():
                    for name, value in element.attrib.items():
                        if name.split('}')[-1] == 'href':
                            self.assertTrue(value.startswith('#'))
                        for target in re.findall(r'url\\((.*?)\\)', value):
                            self.assertTrue(target.strip(' \\"\\\'').startswith('#'))

    def test_server_serves_only_catalog_icons_and_license(self):
        handler = object.__new__(PreviewHandler)
        for path in ICONS.glob('*.svg'):
            self.assertEqual(Path(handler.translate_path('/assets/operators/'+path.name)), path)
        self.assertEqual(Path(handler.translate_path('/assets/operators/LICENSE.txt')), ICONS/'LICENSE.txt')
        for route in ['/assets/operators/../LICENSE.txt', '/assets/operators/%2e%2e/app.js',
                      '/assets/operators/unknown.svg', '/assets/operators/', '/docs/operator-icons.json']:
            self.assertEqual(Path(handler.translate_path(route)), ROOT/'.preview/not-found')

    def test_upstream_license_and_notices_are_included(self):
        license_text = (ICONS/'LICENSE.txt').read_text(encoding='utf-8')
        self.assertIn('MIT License', license_text)
        self.assertIn('Copyright (c) 2021 Marco Vockner', license_text)
        self.assertIn('Copyright (c) 2026 Jose Roberto', license_text)
        self.assertIn('The above copyright notice', license_text)


if __name__ == '__main__':
    unittest.main()
