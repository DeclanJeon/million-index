import re
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app import Handler, STATIC_FILES

ROOT = Path(__file__).resolve().parent

class SeoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def get(self, path, method='GET'):
        return urlopen(Request(self.base + path, method=method), timeout=5)

    def test_whitelisted_assets_with_types(self):
        for path, (_, mime) in STATIC_FILES.items():
            with self.subTest(path=path), self.get(path) as res:
                self.assertEqual(res.status, 200)
                self.assertTrue(res.headers['Content-Type'].startswith(mime))
                self.assertGreater(len(res.read()), 0)

    def test_head_has_no_body(self):
        with self.get('/og-image.png', 'HEAD') as res:
            self.assertEqual(res.status, 200)
            self.assertEqual(res.read(), b'')

    def test_no_traversal_or_secrets(self):
        for path in ['/.env', '/app.py', '/static/../.env', '/%2e%2e/.env', '/robots.txt/..']:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, 404)

    def test_head_metadata(self):
        html = (ROOT / 'index.html').read_text()
        for needle in ['<link rel="canonical" href="https://mi.ponslink.com/">',
                       'property="og:image" content="https://mi.ponslink.com/og-image.png"',
                       'name="twitter:card" content="summary_large_image"',
                       '<meta name="description"', 'application/ld+json']:
            self.assertIn(needle, html)
        description = re.search(r'<meta name="description" content="([^"]+)"', html)[1]
        self.assertTrue(50 <= len(description) <= 160, len(description))
