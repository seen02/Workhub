"""Small standard-library HTTP client for local setup and verification scripts."""
import json
import urllib.request
import urllib.error
import urllib.parse
class Response:
    def __init__(self,status,raw):
        self.status_code=status; self.content=raw; self.text=raw.decode('utf-8',errors='replace'); self.is_error=status>=400
    def json(self): return json.loads(self.text)
    def raise_for_status(self):
        if self.is_error: raise RuntimeError(f'HTTP {self.status_code}: {self.text[:500]}')
class Client:
    def __init__(self,base_url='',timeout=60,headers=None): self.base_url=base_url;self.timeout=timeout;self.headers=headers or {}
    def request(self,method,path,json=None,params=None,data=None,headers=None):
        url=self.base_url+path
        if params: url+='?'+urllib.parse.urlencode(params)
        h={**self.headers,**(headers or {})}
        if json is not None:
            data=__import__('json').dumps(json,ensure_ascii=False).encode();h['Content-Type']='application/json'
        try:
            with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h,method=method),timeout=self.timeout) as r:return Response(r.status,r.read())
        except urllib.error.HTTPError as e:return Response(e.code,e.read())
    def get(self,path,**kw):return self.request('GET',path,**kw)
    def post(self,path,**kw):return self.request('POST',path,**kw)
