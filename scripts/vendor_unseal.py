"""Open the fixed recipient's encrypted vendor grant to owner-only local files."""
import base64,json,os,re,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
def open_grant(src,key,out,vendor):
    if key.stat().st_mode & 0o077:
        raise ValueError('Private key must be owner-only')
    if src.suffix=='.zip':
        with ZipFile(src) as z:
            info=z.getinfo('sealed.json')
            if info.file_size>8192:raise ValueError('Unexpected envelope size')
            sealed=json.loads(z.read(info))
    else:sealed=json.loads(src.read_text())
    private=serialization.load_pem_private_key(key.read_bytes(),password=None)
    unwrap=private.decrypt(base64.b64decode(sealed['wrapped'],validate=True),
              padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    plain=AESGCM(unwrap).decrypt(base64.b64decode(sealed['iv'],validate=True),base64.b64decode(sealed['data'],validate=True),b'airlock-integration-v1')
    data=json.loads(plain)
    url=urlsplit(data['url'])
    if not (url.scheme=='https' and re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com',url.netloc)
            and data['origin']=='https://'+url.netloc and not url.query and not url.fragment and data['vendor']==vendor
            and url.path==('/openapi.json' if vendor=='muse' else '/mcp')
            and time.time()<data['expires']<=time.time()+620 and re.fullmatch(r'pal_[A-Za-z0-9_-]{43}',data['token'])):
        raise ValueError('Expired or mismatched grant')
    os.umask(0o077)
    out.mkdir(mode=0o700)
    (out/'connection.json').write_text(json.dumps({'url':data['url'],'credential':data['token']}))
    if vendor=='manus':
        (out/'manus-mcp.json').write_text(json.dumps({'mcpServers':{'airlock-status':{'url':data['url'],'headers':{'Authorization':'Bearer '+data['token']}}}}))
    for name in ['url','token','expires','nonce']:(out/name).write_text(str(data[name]))
if __name__=='__main__':
    open_grant(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4])
