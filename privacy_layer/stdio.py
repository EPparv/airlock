"""Forward one local client's MCP requests using its own scoped credential."""
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


LIMIT = 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def endpoint(session_file, port):
    if session_file is not None:
        value = json.loads(session_file.read_text(encoding='utf-8'))
        url = urlsplit(value['mcp_url'])
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path != '/mcp'
                or url.username or url.password or url.query or url.fragment or not url.port):
            raise ValueError('Invalid local gateway address')
        port = url.port
    return f'http://127.0.0.1:{port}/mcp'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--token-file', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8792)
    parser.add_argument('--session-file', type=Path)
    args = parser.parse_args()
    opener = build_opener(ProxyHandler({}), NoRedirect())
    version = None
    for line in sys.stdin.buffer:
        request = None
        message = None
        try:
            if len(line) > LIMIT:
                raise ValueError('Request too large')
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('Invalid client request')
            # Resolve both per request so reopening Airlock picks up the new
            # ephemeral port. A missing credential gets an actionable RPC error.
            headers = {'Authorization':'Bearer ' + args.token_file.read_text(encoding='utf-8').strip(),
                       'Content-Type':'application/json', 'Accept':'application/json, text/event-stream'}
            if version is not None and request.get('method') != 'initialize':
                headers['MCP-Protocol-Version'] = version
            gateway = Request(endpoint(args.session_file, args.port), data=line, headers=headers)
            with opener.open(gateway, timeout=90) as response:
                if 'id' not in request:
                    # A successful HTTP acknowledgment has no stdio counterpart.
                    continue
                raw = response.read(LIMIT + 1)
                if len(raw) > LIMIT:
                    raise ValueError('Response too large')
            reply = json.loads(raw)
            if not isinstance(reply, dict) or 'id' not in reply or reply['id'] != request['id']:
                raise ValueError('Invalid local gateway response')
            if request.get('method') == 'initialize' and 'result' in reply:
                version = reply['result']['protocolVersion']
                if not isinstance(version, str) or not version.isascii() or not version.replace('-', '').isdigit():
                    raise ValueError('Invalid negotiated MCP version')
            print(json.dumps(reply, separators=(',', ':')), flush=True)
        except HTTPError as error:
            if error.code in (401, 403):
                message = 'Airlock access is closed. Unlock the workspace on this Mac and check the connection’s expiry or revocation.'
            else:
                message = 'Airlock’s local gateway rejected the request. Open Airlock and reconnect this agent.'
        except (OSError, URLError, ValueError, KeyError, TypeError):
            message = 'Airlock’s local gateway or credential is unavailable. Open Airlock on the Mac running this agent and reconnect.'
        if message and isinstance(request, dict) and 'id' in request:
            print(json.dumps({'jsonrpc':'2.0', 'id':request['id'], 'error':{'code':-32000, 'message':message}}), flush=True)


if __name__ == '__main__':
    main()
