import unittest
from app import parse_instagram_metadata

class InstagramMetadataTests(unittest.TestCase):
    def test_matching_thumbnail_and_watch_count(self):
        html = """<meta content="https://www.instagram.com/author/reel/abc/" property="og:url">
        <meta property="og:image" content="https://cdn.example/cover.jpg?a=1&amp;b=2">
        <script type="application/ld+json">{"@type":"VideoObject","url":"https://www.instagram.com/reel/abc/",
        "interactionStatistic":[{"interactionType":{"@type":"LikeAction"},"userInteractionCount":100},
        {"interactionType":{"@type":"WatchAction"},"userInteractionCount":12345}]}</script>"""
        self.assertEqual(parse_instagram_metadata(html,'abc'),{'views':12345,'thumbnail':'https://cdn.example/cover.jpg?a=1&b=2'})
        self.assertEqual(parse_instagram_metadata(html,'other'),{})

    def test_does_not_borrow_count_from_other_reel(self):
        html = """<meta property="og:url" content="https://www.instagram.com/reel/abc/">
        <script type="application/ld+json">{"@type":"VideoObject","url":"https://www.instagram.com/reel/other/",
        "interactionStatistic":{"interactionType":"https://schema.org/WatchAction","userInteractionCount":12345}}</script>"""
        self.assertEqual(parse_instagram_metadata(html,'abc'),{})
