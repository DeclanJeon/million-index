import unittest
from unittest.mock import patch
from app import rows, video_id, terms, search, parse_tiktok_metadata
class Tests(unittest.TestCase):
 def test_threshold(self):
  items=[dict(id=str(i),statistics={'viewCount':v},snippet={'title':'coffee'}) for i,v in enumerate(['999999','1000000',None,'1M','3000000'])]
  self.assertEqual([r['id'] for r in rows(items,'coffee','4')],['1'])
 def test_custom_minimum(self):
  items=[dict(id=str(v),statistics={'viewCount':str(v)},snippet={'title':'coffee'}) for v in [99999,100000,9999999,10000000]]
  for minimum, ids in [(100000,['100000','9999999','10000000']),(10000000,['10000000'])]:
   with self.subTest(minimum=minimum), patch('app.api',side_effect=[[{'id':{'videoId':'test'}}],items]):
    data=search('keyword','coffee',minimum)
    self.assertEqual([r['id'] for r in data['results']],ids)
 def test_invalid_minimum(self):
  for minimum in [-1,1.5,True,'100000']:
   with self.subTest(minimum=minimum), patch('app.api') as api:
    with self.assertRaises(ValueError): search('keyword','coffee',minimum)
    api.assert_not_called()
 def test_published_date(self):
  item={'id':'test','statistics':{'viewCount':'1000000'},'snippet':{'title':'coffee','publishedAt':'2024-04-02T00:00:00Z'}}
  self.assertEqual(rows([item],'coffee',None)[0]['publishedAt'],'2024-04-02T00:00:00Z')
  del item['snippet']['publishedAt']
  self.assertIsNone(rows([item],'coffee',None)[0]['publishedAt'])
 def test_social_candidates_are_not_verified_results(self):
  import json
  from types import SimpleNamespace
  payload={'status':'ok','videos':[{'platform':'tiktok','originalUrl':'https://www.tiktok.com/@test/video/123','title':'coffee','view_count':5000000},{'platform':'tiktok','originalUrl':'https://example.com/video/123'}]}
  with patch('app.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(payload),returncode=0)), patch('app.tiktok_metadata',return_value={}):
   data=search('keyword','coffee',1000000,'tiktok')
  self.assertEqual(data['results'],[])
  self.assertEqual(data['candidates'],[])
  self.assertEqual(len(data['unverified']),1)
  self.assertIsNone(data['unverified'][0]['views'])
 def test_brave_search_validates_links_and_relevance(self):
  import io
  import json
  import os
  payload={'web':{'results':[
   {'url':'https://www.instagram.com/reel/abc/?igsh=test','title':'Iced coffee tutorial'},
   {'url':'https://www.instagram.com/reel/abc/','title':'Iced coffee duplicate'},
   {'url':'https://www.instagram.com/reel/xyz/','title':'A love song cover'},
   {'url':'https://example.org/reel/abc/','title':'Coffee'},
  ]}}
  with patch.dict(os.environ,{'BRAVE_SEARCH_API_KEY':'test-key'}), patch('app.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as call, patch('app.subprocess.run') as cli, patch('app.instagram_metadata',return_value={}):
   result=search('keyword','iced coffee recipe',1000000,'instagram')
   cli.assert_not_called()
   self.assertIn('api.search.brave.com',call.call_args.args[0].full_url)
  self.assertEqual([v['url'] for v in result['candidates']],['https://www.instagram.com/reel/abc/'])
  self.assertIsNone(result['candidates'][0]['views'])
 def test_tiktok_metadata_matches_video_id(self):
  import json
  item={'id':'123','stats':{'playCount':747900},'video':{'cover':'https://cdn.example/cover.jpg'}}
  data={'__DEFAULT_SCOPE__':{'webapp.video-detail':{'itemInfo':{'itemStruct':item}}}}
  html='<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'+json.dumps(data)+'</script>'
  self.assertEqual(parse_tiktok_metadata(html,'123'),{'views':747900,'thumbnail':item['video']['cover']})
  self.assertEqual(parse_tiktok_metadata(html,'456'),{})
  self.assertEqual(parse_tiktok_metadata('<html>blocked</html>','123'),{})
 def test_url(self):
  self.assertEqual(video_id('https://youtu.be/abcdefghijk?t=3'),'abcdefghijk')
  with self.assertRaises(ValueError): video_id('https://example.org/watch?v=abcdefghijk')
 def test_caption(self):
  self.assertEqual(terms('WEBVTT\n00:00:01.000 --> 00:00:02.000\n커피 커피 필터'), '커피 필터')
