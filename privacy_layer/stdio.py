"""Native MCP stdio bridge. Holds only one scoped agent token, never vault access."""
import argparse
import json
from pathlib import Path
import sys
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlsplit


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def main():
    p=argparse.ArgumentParser();p.add_argument('--token-file',required=True,type=Path);p.add_argument('--port',type=int,default=8792);p.add_argument('--session-file',type=Path);a=p.parse_args()
    token=a.token_file.read_text().strip()
    opener=build_opener(ProxyHandler({}),NoRedirect())
    for line in sys.stdin:
        request=None
        try:
            if len(line.encode())>1024*1024: raise ValueError()
            request=json.loads(line)
            port=a.port
            if a.session_file:
                session=json.loads(a.session_file.read_text());url=urlsplit(session['mcp_url'])
                if url.scheme!='http' or url.hostname!='127.0.0.1' or url.path!='/mcp' or url.username or url.password or url.query or url.fragment or not url.port:raise ValueError()
                port=url.port
            r=Request(f'http://127.0.0.1:{port}/mcp',data=line.encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
            with opener.open(r,timeout=90) as response: raw=response.read(1024*1024)
            if raw: print(raw.decode(),flush=True)
        except Exception:
            if isinstance(request,dict) and 'id' in request:
                print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32000,'message':'Privacy service unavailable or connection not authorized. Open Airlock to review access.'}}),flush=True)


if __name__=='__main__':main()

