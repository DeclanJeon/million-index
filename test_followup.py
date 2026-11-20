import unittest
from unittest.mock import patch
from app import partition_tiktok, instagram_search, search

class FollowupTests(unittest.TestCase):
    def test_count_boundary_and_unknown(self):
        values=[dict(views=x) for x in (None,0,99999,100000)]
        self.assertEqual(partition_tiktok(values,100000),([values[-1]],[values[0]]))
        self.assertEqual(partition_tiktok(values,0)[0],values[1:])

    def test_tiktok_checks_eight_candidates_and_keeps_the_rest_unknown(self):
        candidates=[{'url':f'https://www.tiktok.com/@test/video/{i}', 'views':None} for i in range(10)]
        with patch.dict('os.environ', {'OPENROUTER_API_KEY':''}), patch('app.social_search',return_value={'unverified':candidates}), patch('app.tiktok_metadata',return_value={'views':100000}) as metadata:
            data=search('keyword','coffee',100000,'tiktok')
        self.assertEqual(metadata.call_count,8)
        self.assertEqual(len(data['candidates']),8)
        self.assertEqual(len(data['unverified']),2)

    def test_expansion_deduplicates_results(self):
        a={'url':'a'}; b={'url':'b'}
        with patch('app.brave_social_search',side_effect=[{'unverified':[a]},{'unverified':[a,b]}]) as provider:
            self.assertEqual(instagram_search('남친 상황극','key')['unverified'],[a,b])
        self.assertEqual(provider.call_args.args[1],'남자친구 상황극')

    def test_expands_after_ranking_and_only_ranks_new_candidates(self):
        a,b,c,d=[{'url':url} for url in 'abcd']
        with patch('app.brave_social_search',side_effect=[{'unverified':[a,b,c]},{'unverified':[a,d]}]):
            ranked=[]
            def judge(items):
                ranked.append(items)
                return [item for item in items if item in (a,d)]
            result=instagram_search('남친 상황극','key',judge=judge)
        self.assertEqual(ranked,[[a,b,c],[d]])
        self.assertEqual(result['unverified'],[a,d])

    def test_expansion_failure_preserves_first_pass(self):
        with patch('app.brave_social_search',side_effect=[{'unverified':[{'url':'a'}]},RuntimeError('limit')]):
            result=instagram_search('남친 상황극','key')
        self.assertEqual(len(result['unverified']),1)
        self.assertTrue(result['warning'])
