"""Bounded public HTTPS retrieval. Every redirect and DNS answer is checked."""
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser
from ..core import DomainError, public_url
from ..research import PinnedHTTPS, validated_host

AGENT='StakeoutProspecting/1.0'

class PublicWeb:
    def __init__(self,cache_dir):
        self.cache=Path(cache_dir);self.cache.mkdir(parents=True,exist_ok=True)
        self.robots={}

    def raw(self,url,limit=2_000_000,redirects=3):
        for _ in range(redirects+1):
            code,ctype,raw,dest=self.response(url,limit)
            if code in (301,302,303,307,308):
                if not dest:raise DomainError('Redirect had no destination.')
                url=urljoin(url,dest);continue
            return code,url,ctype,raw
        raise DomainError('Source exceeded the redirect limit.')

    def response(self,url,limit):
        host,address=validated_host(url,{(urlsplit(url).hostname or '').lower().rstrip('.')})
        conn=PinnedHTTPS(host,address);parsed=urlsplit(url);started=time.monotonic()
        try:
            conn.request('GET',(parsed.path or '/')+('?' + parsed.query if parsed.query else ''),
                headers={'User-Agent':AGENT,'Accept-Encoding':'identity','Accept':'*/*'})
            res=conn.getresponse();ctype=res.getheader('Content-Type','').lower();dest=res.getheader('Location','')
            if res.status in (301,302,303,307,308):return res.status,ctype,b'',dest
            length=res.getheader('Content-Length')
            if length and int(length)>limit:raise DomainError('Source exceeds the download size limit.')
            chunks=[];size=0
            while True:
                if time.monotonic()-started>120:raise DomainError('Source exceeded the download time limit.')
                chunk=res.read1(min(65536,limit+1-size))
                if not chunk:break
                chunks.append(chunk);size+=len(chunk)
                if size>limit:raise DomainError('Source exceeds the download size limit.')
            return res.status,ctype,b''.join(chunks),dest
        finally:conn.close()

    def page(self,url):
        public_url(url,required=True)
        # We never weaken TLS or silently treat a failed HTTP-only site as absent.
        if url.startswith('http://'):url='https://'+url[7:]
        for _ in range(4):
            public_url(url,required=True)
            if urlsplit(url).scheme!='https':raise DomainError('Page redirected away from HTTPS.')
            origin='https://'+(urlsplit(url).hostname or '')
            hit=self.robots.get(origin)
            if not hit or time.time()-hit[0]>600:
                code,_,_,raw=self.raw(origin+'/robots.txt',200000)
                if code==404:policy=None
                elif code==200:
                    policy=RobotFileParser();policy.parse(raw.decode('utf-8','replace').splitlines())
                else:raise DomainError('Robots policy could not be checked.')
                hit=(time.time(),policy);self.robots[origin]=hit
            if hit[1] and not hit[1].can_fetch(AGENT,url):raise DomainError('Robots policy disallows this page.')
            code,ctype,raw,dest=self.response(url,2_000_000)
            if code in (301,302,303,307,308):
                if not dest:raise DomainError('Redirect had no destination.')
                url=urljoin(url,dest);continue
            if code!=200:raise DomainError(f'Page returned HTTP {code}.')
            if not any(v in ctype for v in ('text/html','text/plain','application/xhtml+xml','application/xml','text/xml')):
                raise DomainError('Page is not supported text; browser or PDF review is needed.')
            return url,raw.decode('utf-8','replace')
        raise DomainError('Page exceeded redirect limit.')

    def dataset(self,url,limit=30_000_000,days=30):
        path=self.cache/(hashlib.sha256(url.encode()).hexdigest()+'.data')
        if path.exists() and time.time()-path.stat().st_mtime<days*86400:return path
        code,_,_,raw=self.raw(url,limit)
        if code!=200:raise DomainError(f'Public dataset returned HTTP {code}. Retry later.')
        # The pilot's Railway volume is shared with SQLite. Cache files are disposable.
        others=sorted((p for p in self.cache.glob('*.data') if p!=path),key=lambda p:p.stat().st_mtime)
        total=sum(p.stat().st_size for p in others)+len(raw)
        for old in others:
            if total<=220_000_000:break
            total-=old.stat().st_size;old.unlink()
        temp=path.with_suffix('.part');temp.write_bytes(raw);temp.replace(path)
        return path

    def json(self,url):
        code,final,_,raw=self.raw(url)
        if code!=200:raise DomainError(f'Public data provider returned HTTP {code}.')
        return json.loads(raw),final
