import unittest
from unittest.mock import patch
from app import search, reference_terms

class ReferenceTests(unittest.TestCase):
    def test_reel_caption_keeps_subject_and_genre_not_entire_sentence(self):
        self.assertEqual(reference_terms('「남친 집에 갔는데, 방에서 은밀한 대화가 들린다면?\n#kdrama #aidrama #puppy」'), '남친 상황극')
        self.assertEqual(reference_terms('Iced coffee recipe\n#coffee #summer'), 'iced coffee recipe')

    def test_instagram_profile_reel_to_youtube(self):
        with patch('app.social_reference',return_value='강아지 산책'), patch('app.api',return_value=[]) as api:
            result=search('url','https://www.instagram.com/moongi_adventures/reel/Df6fsztP0zv/',platform='youtube')
        self.assertEqual(result['query'],'강아지 산책')
        self.assertEqual(api.call_args.kwargs['q'],'강아지 산책')

    def test_tiktok_removes_reference_from_results(self):
        url='https://www.tiktok.com/@dog/video/123/'
        with patch('app.social_reference',return_value='강아지 산책'), patch('app.social_search',return_value={'unverified':[{'url':url}]}):
            result=search('url',url+'?x=1',platform='tiktok')
        self.assertEqual(result['candidates'],[])

    def test_untrusted_url_is_not_fetched(self):
        with patch('app.social_reference') as fetch:
            with self.assertRaises(ValueError):
                search('url','https://www.instagram.com.evil.example/reel/ABC/')
            fetch.assert_not_called()
