import unittest
from app import duration_seconds, rows

class FormatTests(unittest.TestCase):
    def test_youtube_duration(self):
        for value, expected in [('PT3M',180),('PT3M1S',181),('PT1H2M3S',3723),('P1DT2H',93600),('PT0S',None),('bad',None),(None,None)]:
            self.assertEqual(duration_seconds(value),expected)

    def test_result_carries_seconds(self):
        item={'id':'test','statistics':{'viewCount':'1000000'},'snippet':{'title':'Test'},'contentDetails':{'duration':'PT3M'}}
        self.assertEqual(rows([item],'test',None)[0]['duration'],180)
