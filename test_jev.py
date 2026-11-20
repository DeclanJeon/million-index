import io
import json
import unittest
from unittest.mock import patch
from jev import rank_candidates

class JevTests(unittest.TestCase):
    def test_keeps_only_relevant_titles(self):
        candidates=[{'title':'Coffee shop'},{'title':'Pour-over coffee'}]
        payload={'answers':{'v0':{'noul':0.21},'v1':{'noul':0.94}}}
        with patch('jev.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as call:
            self.assertEqual(rank_candidates('핸드드립 커피',candidates,'test'),[candidates[1]])
            self.assertEqual(json.loads(call.call_args.args[0].data)['model'],'~typesafe/jev-latest')

    def test_invalid_response_is_not_treated_as_no_matches(self):
        with patch('jev.urlopen',return_value=io.BytesIO(b'{}')):
            with self.assertRaises(RuntimeError):
                rank_candidates('coffee',[{'title':'coffee'}],'test')
