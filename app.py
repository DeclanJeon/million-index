"""Local YouTube reference finder; Python standard library only."""
import json
import os
import re
import subprocess
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from urllib.error import HTTPError, URLError
from local_keys import load_keys
from jev import rank_candidates

def video_id(url):
    p = urlparse(url)
    parts = p.path.strip('/').split('/')
    vid = ''
    if p.scheme == 'https':
        if p.hostname == 'youtu.be':
            vid = parts[0]
        elif p.hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
            if p.path == '/watch':
                vid = parse_qs(p.query).get('v', [''])[0]
            elif len(parts) == 2 and parts[0] in {'shorts', 'embed', 'live'}:
                vid = parts[1]
    if not re.fullmatch(r'[\w-]{11}', vid, re.ASCII):
        raise ValueError('YouTube 영상 주소를 입력하세요.')
    return vid

def terms(s):
    s = re.sub(r'(?im)^.*-->.*$|https?://\S+|<[^>]*>', ' ', s)
    skip = {'webvtt','the','and','this','that','for','with','있는','하는','그리고','영상','정말'}
    words = re.findall(r'[^\W_]+', s.lower())
    return ' '.join(w for w, _ in Counter(w for w in words if w not in skip and not w.isdigit() and len(w)>1).most_common(6))

DEFAULT_MIN_VIEWS = 1_000_000
MAX_MIN_VIEWS = 9_007_199_254_740_991

def duration_seconds(value):
    if not isinstance(value,str):
        return None
    match = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?',value)
    if not match:
        return None
    return sum(int(n or 0)*unit for n,unit in zip(match.groups(),(86400,3600,60,1))) or None

def rows(items, q, source, min_views=DEFAULT_MIN_VIEWS):
    out = []
    for item in items:
        count = str(item.get('statistics', {}).get('viewCount'))
        if item['id'] == source or not count.isascii() or not count.isdigit() or int(count)<min_views:
            continue
        s = item['snippet']
        hay = (s['title']+' '+s.get('description','')).lower()
        out.append(dict(id=item['id'], title=s['title'], channel=s.get('channelTitle',''), views=int(count), publishedAt=s.get('publishedAt'), duration=duration_seconds(item.get('contentDetails',{}).get('duration')), matches=[w for w in q.lower().split() if w in hay]))
    return sorted(out, key=lambda r:-len(r['matches']))

def api(endpoint, **params):
    key = os.getenv('YOUTUBE_API_KEY')
    if not key:
        raise RuntimeError('서버에 YOUTUBE_API_KEY를 설정하고 다시 시작하세요.')
    req = Request('https://www.googleapis.com/youtube/v3/'+endpoint+'?'+urlencode(params), headers={'X-Goog-Api-Key':key})
    try:
        with urlopen(req, timeout=18) as res:
            return json.load(res)['items']
    except HTTPError as e:
        raise RuntimeError(f'YouTube API 요청 실패 ({e.code}). 키, API 활성화 및 할당량을 확인하세요.') from None
    except (URLError, TimeoutError):
        raise RuntimeError('YouTube 연결 실패. 네트워크 상태를 확인하세요.') from None

SOCIAL_PATHS = {
    'tiktok': re.compile(r'https://www\.tiktok\.com/@[\w.-]+/video/[0-9]+/?', re.ASCII),
    'instagram': re.compile(r'https://www\.instagram\.com/reel/[\w-]+/?', re.ASCII),
}
SOCIAL_SLOT = threading.BoundedSemaphore(1)

def parse_tiktok_metadata(html, expected_id):
    match = re.search(r'<script\b[^>]*\bid="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        return {}
    try:
        detail = json.loads(match[1])['__DEFAULT_SCOPE__']['webapp.video-detail']
        item = detail['itemInfo']['itemStruct']
        if item['id'] != expected_id:
            return {}
        count = item.get('stats', {}).get('playCount')
        video = item.get('video', {})
        cover = video.get('cover')
        duration = video.get('duration')
        data = {}
        if type(duration) is int and 0 < duration <= MAX_MIN_VIEWS:
            data['duration'] = duration
        if type(count) is int and 0 <= count <= MAX_MIN_VIEWS:
            data['views'] = count
        if isinstance(cover, str) and cover.startswith('https://'):
            data['thumbnail'] = cover
        return data
    except (ValueError, TypeError, KeyError, AttributeError):
        return {}

def instagram_reel_id(url):
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != 'https' or parsed.netloc not in ('www.instagram.com', 'instagram.com'):
        return None
    match = re.fullmatch(r'/(?:[\w.]+/)?reel/([\w-]+)/?', parsed.path, re.ASCII)
    return match[1] if match else None

class InstagramPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.documents = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('property') in {'og:url', 'og:image', 'og:description', 'og:title'}:
            self.meta.setdefault(values['property'], values.get('content') or '')
        if tag == 'script' and values.get('type') == 'application/ld+json':
            self.active = []

    def handle_data(self, data):
        if self.active is not None:
            self.active.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.active is not None:
            try:
                self.documents.append(json.loads(''.join(self.active)))
            except (ValueError, RecursionError):
                pass
            self.active = None

def parse_instagram_metadata(html, expected_id):
    page = InstagramPage()
    page.feed(html)
    if instagram_reel_id(page.meta.get('og:url', '')) != expected_id:
        return {}
    data = {}
    cover = page.meta.get('og:image', '')
    if cover.startswith('https://'):
        data['thumbnail'] = cover
    nodes = list(page.documents)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        graph = node.get('@graph')
        if isinstance(graph, list):
            nodes.extend(graph)
        url = node.get('url')
        if node.get('@type') != 'VideoObject' or not isinstance(url, str) or instagram_reel_id(url) != expected_id:
            continue
        stats = node.get('interactionStatistic', [])
        for stat in stats if isinstance(stats, list) else [stats]:
            if not isinstance(stat, dict):
                continue
            action = stat.get('interactionType')
            if isinstance(action, dict):
                action = action.get('@type')
            count = stat.get('userInteractionCount')
            if action in ('WatchAction', 'https://schema.org/WatchAction', 'http://schema.org/WatchAction') and type(count) is int and 0 <= count <= MAX_MIN_VIEWS:
                data['views'] = count
                return data
    return data

def instagram_metadata(candidate):
    url = candidate['url']
    expected_id = instagram_reel_id(url)
    if not expected_id:
        return {}
    try:
        with urlopen(Request(url, headers={'Accept':'text/html'}), timeout=4) as response:
            if instagram_reel_id(response.geturl()) != expected_id:
                return {}
            return parse_instagram_metadata(response.read(2_000_000).decode('utf-8',errors='replace'), expected_id)
    except (OSError, ValueError):
        return {}

def tiktok_metadata(candidate):
    url = candidate['url']
    vid = url.rstrip('/').rsplit('/',1)[-1]
    try:
        request = Request(url, headers={'Accept':'text/html'})
        with urlopen(request, timeout=4) as response:
            if not SOCIAL_PATHS['tiktok'].fullmatch(response.geturl()):
                return {}
            return parse_tiktok_metadata(response.read(2_000_000).decode('utf-8', errors='replace'),vid)
    except (OSError, ValueError):
        return {}

def brave_social_search(platform, query, key):
    scope = 'instagram.com/reel/' if platform == 'instagram' else 'tiktok.com'
    params = urlencode({'q': f'site:{scope} {query}', 'count': 20})
    req = Request('https://api.search.brave.com/res/v1/web/search?' + params,
                  headers={'Accept':'application/json', 'X-Subscription-Token':key})
    try:
        with urlopen(req, timeout=15) as res:
            payload = json.load(res)
    except HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError('Brave Search API 키와 검색 권한을 확인하세요.') from None
        if e.code == 429:
            raise RuntimeError('Brave Search API 요청 한도에 도달했습니다.') from None
        raise RuntimeError(f'Brave Search API 요청에 실패했습니다 (HTTP {e.code}).') from None
    except (URLError, TimeoutError, ValueError):
        raise RuntimeError('Brave Search API에 연결하지 못했거나 응답을 읽지 못했습니다.') from None
    words = lambda text: re.findall(r'[^\W_]+', text.casefold())
    generic = {'the','how','to','for','with','video','recipe','tutorial','영상','레시피','방법'}
    raw_words = words(query)
    topical = [w for w in raw_words if w not in generic and len(w) > 1] or raw_words
    candidates = {}
    for item in payload.get('web', {}).get('results', []):
        url = urlparse(item.get('url', ''))
        if url.scheme != 'https' or url.netloc not in {scope.split('/')[0], 'www.' + scope.split('/')[0]}:
            continue
        canonical = f'https://www.{scope.split("/")[0]}{url.path.rstrip("/")}/'
        if not SOCIAL_PATHS[platform].fullmatch(canonical):
            continue
        title = item.get('title') or ''
        title_words = words(title)
        if not any(w == t or (re.fullmatch('[a-z]{3,}', w) and t == w+'s')
                   or (len(w) >= 2 and re.search('[가-힣]', w) and w in t)
                   for w in topical for t in title_words):
            continue
        candidates.setdefault(canonical, dict(url=canonical, title=title, channel='',
                                              views=None, publishedAt=None, matches=[]))
    return dict(query=query, results=[], unverified=list(candidates.values())[:10], source='Brave Search')

def instagram_search(query, key, judge=None, exclude=None):
    data = brave_social_search('instagram', query, key)
    initial = [item for item in data['unverified'] if item['url'] != exclude]
    seen = {item['url'] for item in initial}
    data['unverified'] = judge(initial) if judge else initial
    if judge and data.get('source'):
        data['source'] += ' · Jev 관련도 판정'
    if len(data['unverified']) >= 3:
        return data
    aliases = {'남친':'남자친구', '여친':'여자친구', '숏드라마':'상황극',
               '핸드드립':'pour-over', '홈카페':'home cafe', '릴스':'reels'}
    parts = query.split()
    variant = ' '.join(aliases.get(word, word) for word in parts)
    if variant == query and len(parts) >= 3:
        variant = ' '.join(parts[:2])
    if not variant or variant == query:
        return data
    try:
        extra = brave_social_search('instagram', variant, key)
        new = {}
        for item in extra['unverified']:
            if item['url'] != exclude and item['url'] not in seen:
                new.setdefault(item['url'], item)
        additional = list(new.values())
        if judge:
            additional = judge(additional)
    except RuntimeError:
        data['warning'] = '보강 검색에 실패해 첫 검색 결과만 표시합니다.'
        return data
    data['unverified'] = (data['unverified'] + additional)[:10]
    data['expandedQuery'] = variant
    return data

def partition_tiktok(candidates, minimum):
    verified, unknown = [], []
    for candidate in candidates:
        count = candidate['views']
        if count is None:
            unknown.append(candidate)
        elif count >= minimum:
            verified.append(candidate)
    return verified, unknown

def social_search(platform, query):
    key = os.getenv('BRAVE_SEARCH_API_KEY')
    if key:
        if platform == 'instagram':
            return instagram_search(query, key)
        return brave_social_search(platform, query, key)
    cli = Path(__file__).resolve().parent.parent / 'flucto/dist-electron/cli/index.js'
    env = {k: v for k, v in os.environ.items() if k not in {'YOUTUBE_API_KEY','BRAVE_SEARCH_API_KEY','OPENROUTER_API_KEY'}}
    if not SOCIAL_SLOT.acquire(blocking=False):
        raise RuntimeError('다른 소셜 검색이 진행 중입니다. 잠시 뒤 다시 시도하세요.')
    try:
        run = subprocess.run(['node', str(cli), 'search', '--platform', platform,
                              '--limit', '10', '--json', '--', query],
                             capture_output=True, text=True, timeout=45, env=env)
        payload = json.loads(run.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise RuntimeError('Flucto를 실행하지 못했거나 검색 시간이 초과됐습니다. 로컬 빌드와 연결 상태를 확인하세요.') from None
    finally:
        SOCIAL_SLOT.release()
    if run.returncode != 0 or payload.get('status') not in {'ok','empty'}:
        raise RuntimeError('Flucto 공개 검색에 실패했습니다. 안정적인 API 경로를 사용하려면 BRAVE_SEARCH_API_KEY를 설정하세요.')
    candidates = []
    for v in payload.get('videos', []):
        url = v.get('originalUrl','')
        if v.get('platform') != platform or not SOCIAL_PATHS[platform].fullmatch(url):
            continue
        candidates.append(dict(url=url, title=v.get('title') or url, channel=v.get('uploader') or '',
                               views=None, publishedAt=None, matches=[]))
    return dict(query=query, results=[], unverified=candidates, source='Flucto 공개 인덱스')

def tiktok_reference_url(url):
    parsed = urlparse(url)
    canonical = f'{parsed.scheme}://{parsed.netloc}{parsed.path}'
    return canonical if SOCIAL_PATHS['tiktok'].fullmatch(canonical) else None

class SameVideoRedirect(HTTPRedirectHandler):
    def __init__(self, accept):
        self.accept = accept

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.accept(newurl):
            raise HTTPError(req.full_url, code, 'Unexpected reference redirect', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

REFERENCE_GENRES = {
    'kdrama': ('상황극','skit'), 'aidrama': ('상황극','skit'),
    'skit': ('상황극','skit'), 'shortdrama': ('상황극','skit'),
    'recipe': ('레시피','recipe'), 'tutorial': ('튜토리얼','tutorial'),
}

def reference_terms(caption):
    opening = next((line.strip() for line in caption.splitlines() if line.strip()), '')
    raw = terms(re.sub(r'#\w+', '', opening)[:350]) or terms(caption[:350])
    if not raw:
        return ''
    tags = re.findall(r'#([\w]+)', caption.casefold())
    genres = [REFERENCE_GENRES[tag] for tag in tags if tag in REFERENCE_GENRES]
    words = raw.split()
    if genres and len(words) > 4:
        korean = bool(re.search('[가-힣]', opening))
        subject = words[0]
        genre = genres[0][0 if korean else 1]
        return ' '.join(dict.fromkeys((subject, genre)))
    return ' '.join(words[:4])

def social_reference(platform, url, source_id):
    if platform == 'instagram':
        accept = lambda target: instagram_reel_id(target) == source_id
    else:
        def accept(target):
            canonical = tiktok_reference_url(target)
            return canonical is not None and canonical.rstrip('/').rsplit('/',1)[-1] == source_id
    try:
        opener = build_opener(SameVideoRedirect(accept))
        with opener.open(Request(url, headers={'Accept':'text/html'}), timeout=8) as response:
            html = response.read(2_000_000).decode('utf-8',errors='replace')
    except (OSError, ValueError):
        raise ValueError('공개 영상 설명을 읽을 수 없습니다. 공개 링크인지 확인하거나 키워드로 검색하세요.') from None
    page = InstagramPage()
    page.feed(html)
    caption = ''
    if platform == 'instagram' and accept(page.meta.get('og:url','')):
        caption = page.meta.get('og:description') or ''
    if platform == 'tiktok':
        match = re.search(r'<script\b[^>]*\bid="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
        if match:
            try:
                item = json.loads(match[1])['__DEFAULT_SCOPE__']['webapp.video-detail']['itemInfo']['itemStruct']
                if item['id'] == source_id:
                    caption = item.get('desc') or ''
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
        if not caption and accept(page.meta.get('og:url','')):
            caption = page.meta.get('og:description') or ''
    if not caption.strip():
        raise ValueError('이 영상의 공개 설명을 확인할 수 없습니다. 키워드 검색을 사용해 주세요.')
    return reference_terms(caption)

def search(mode, value, min_views=DEFAULT_MIN_VIEWS, platform='youtube'):
    if platform not in ('youtube', 'tiktok', 'instagram'):
        raise ValueError('지원하지 않는 플랫폼입니다.')
    if type(min_views) is not int or not 0 <= min_views <= MAX_MIN_VIEWS:
        raise ValueError('최소 조회수는 0 이상의 정수로 입력하세요.')
    if not isinstance(value,str) or not value.strip():
        raise ValueError('검색할 내용을 입력하세요.')
    source = None
    source_platform = None
    if mode == 'url':
        url = value.strip()
        reel_id = instagram_reel_id(url)
        tiktok_url = tiktok_reference_url(url)
        if reel_id:
            source_platform, source = 'instagram', reel_id
            q = social_reference(source_platform, f'https://www.instagram.com/reel/{source}/', source)
        elif tiktok_url:
            source_platform, source = 'tiktok', tiktok_url.rstrip('/').rsplit('/',1)[-1]
            q = social_reference(source_platform, tiktok_url, source)
        else:
            try:
                source = video_id(url)
            except ValueError:
                raise ValueError('YouTube 영상, Instagram 릴스, 또는 TikTok의 전체 영상 주소를 입력하세요.') from None
            source_platform = 'youtube'
            ref = api('videos',part='snippet',id=source)
            if not ref: raise ValueError('공개 레퍼런스 영상을 찾을 수 없습니다.')
            s = ref[0]['snippet']
            q = terms((s['title']+' ')*3+s.get('description','')[:350])
    elif mode == 'file':
        q = terms(value)
    elif mode == 'keyword':
        q = value.strip()[:200]
    else:
        raise ValueError('지원하지 않는 입력입니다.')
    if not q: raise ValueError('검색어를 추출할 수 없습니다.')
    if platform != 'youtube':
        key = os.getenv('OPENROUTER_API_KEY')
        brave = os.getenv('BRAVE_SEARCH_API_KEY')
        ranked_in_search = platform == 'instagram' and bool(brave)
        if ranked_in_search:
            judge = (lambda items: rank_candidates(q, items, key)) if key else None
            excluded = f'https://www.instagram.com/reel/{source}/' if source_platform == 'instagram' else None
            data = instagram_search(q, brave, judge=judge, exclude=excluded)
        else:
            data = social_search(platform, q)
        candidates = data['unverified']
        if platform == source_platform:
            candidates = [item for item in candidates
                          if item['url'].rstrip('/').rsplit('/',1)[-1] != source]
        if key and candidates and not ranked_in_search:
            candidates = rank_candidates(q, candidates, key)
            data['source'] += ' · Jev 관련도 판정'
        if candidates:
            batch = candidates[:8 if platform == 'tiktok' else 5]
            enrich = tiktok_metadata if platform == 'tiktok' else instagram_metadata
            with ThreadPoolExecutor(max_workers=3) as pool:
                for candidate, metadata in zip(batch, pool.map(enrich, batch)):
                    candidate.update(metadata)
        data.pop('unverified')
        if platform == 'tiktok':
            data['candidates'], data['unverified'] = partition_tiktok(candidates, min_views)
        else:
            data['candidates'] = candidates
        return data
    candidates = api('search',part='id',type='video',order='relevance',maxResults=50,q=q)
    ids = ','.join(x['id']['videoId'] for x in candidates)
    details = api('videos',part='statistics,snippet,contentDetails',id=ids) if ids else []
    return dict(query=q, results=rows(details,q,source if source_platform == 'youtube' else None,min_views))

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data, mime='application/json'):
        body = data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type',mime+'; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path != '/': return self.send_error(404)
        self.reply(200, Path(__file__).with_name('index.html').read_bytes(),'text/html')
    def do_POST(self):
        if self.path != '/search': return self.send_error(404)
        if self.headers.get_content_type()!='application/json': return self.send_error(415)
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' and self.headers.get('Host') != f'localhost:{self.server.server_port}': return self.send_error(403)
        try:
            n = int(self.headers.get('Content-Length','0'))
            if not 0<n<=1048576: raise ValueError('최대 요청 크기는 1MB입니다.')
            data=json.loads(self.rfile.read(n))
            if not isinstance(data,dict): raise ValueError('잘못된 요청입니다.')
            self.reply(200,search(data.get('mode'),data.get('value'),data.get('minViews',DEFAULT_MIN_VIEWS),data.get('platform','youtube')))
        except ValueError as e: self.reply(400,dict(error=str(e)))
        except RuntimeError as e: self.reply(503,dict(error=str(e)))

if __name__=='__main__':
    try:
        load_keys()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from None
    port=int(os.getenv('PORT','8765'))
    print(f'http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
