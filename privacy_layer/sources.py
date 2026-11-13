"""Native, read-only adapters. The original app vault is never modified."""
import copy
import base64
import fcntl
import os
import secrets
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlencode

APP = Path(__file__).resolve().parents[1]/'vendor'
if not APP.exists():APP=Path(__file__).resolve().parents[2]/'Private_AI'
sys.path.insert(0,str(APP))
from private_ai.vault import Vault
from private_ai.device_access import MacKeychain, DeviceAccessError
from private_ai.google_connection import GoogleTransport, TOKEN, GMAIL, SCOPES, token_record, OAuthSession, EMAIL_SCOPE, USERINFO
from private_ai.google_app import bundled_client


def automatic_message_text(payload):
    """Prefer structural HTML over mangled plain-text newsletter alternatives."""
    plain=[];html=[];attachments=[];size=0
    def visit(part,depth=0):
        nonlocal size
        if depth>30:raise ValueError('Email MIME structure is too deep.')
        if part.get('filename') or any(h.get('name','').lower()=='content-disposition' and h.get('value','').lower().startswith('attachment') for h in part.get('headers',[])):
            attachments.append(True);return
        encoded=part.get('body',{}).get('data');mime=part.get('mimeType','')
        if encoded and mime in ('text/plain','text/html'):
            raw=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4));size+=len(raw)
            if size>2_000_000:raise ValueError('Email body is too large.')
            charset='utf-8'
            for header in part.get('headers',[]):
                if header.get('name','').lower()=='content-type':
                    match=re.search(r'charset=["\']?([\w-]+)',header.get('value',''),re.I)
                    if match:charset=match[1]
            (html if mime=='text/html' else plain).append(raw.decode(charset,errors='replace'))
        for child in part.get('parts',[]):visit(child,depth+1)
    visit(payload)
    if html:
        from .automatic import mail_text
        body=mail_text('\n'.join(html))
    else:body='\n'.join(plain)
    if len(body)>100000:raise ValueError('Email text is too large.')
    return body,attachments


class LocalSources:
    def __init__(self, path=None, key=None, transport=None, context_home=None):
        legacy=Path(context_home or Path.home())/'.private-ai/vault.enc'
        self.path = Path(path) if path else legacy if legacy.exists() else None
        self.key = key or self.device_key()
        self.transport = transport or GoogleTransport()
        self.lock = threading.RLock()
        self.access = None
        self.discovered = set()
        self.connection_store = None
        self.oauth = None
        self.gmail_health = None
        self.context_home = context_home

    def device_key(self):
        # Existing vaults are read-only sources. A fresh installation has its
        # own Keychain key and encrypted library; no prior app is required.
        if self.path:
            key=MacKeychain(self.path).get()
            if key is None:raise DeviceAccessError('Open the original app for your existing library once to enable automatic access to its saved library.')
            return key
        from .setup import ROOT
        state=ROOT/'.private';state.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(state/'key.lock',os.O_RDWR|os.O_CREAT,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            store=MacKeychain(state/'connections.enc');key=store.get()
            if key is None:
                if (state/'connections.enc').exists():raise DeviceAccessError('The key for your saved library is missing from Keychain. Your data has not been reset.')
                key=secrets.token_bytes(32);store.set(key)
                if store.get()!=key:raise DeviceAccessError('macOS could not remember the encryption key. Allow Keychain access, then open the app again.')
            return key
        finally:os.close(fd)

    def google_config(self):
        if self.connection_store:
            with self.connection_store.transaction() as d:
                if 'google' in d:return copy.deepcopy(d['google'])
        legacy=self.snapshot().get('workspace',{}).get('google',{})
        if legacy.get('client_id'):return legacy
        config,error=bundled_client()
        if error:raise DeviceAccessError('This download has an invalid Google setup. Download the app again.')
        return config or {}

    def connect_gmail(self):
        if not self.connection_store:raise ValueError('Encrypted connection storage unavailable.')
        config=self.google_config()
        if not config.get('client_id') or not config.get('client_secret'):raise ValueError('This download is missing its Google setup. Download the complete Mac app again.')
        config={k:config[k] for k in ('client_id','client_secret')}
        if self.oauth:self.oauth.cancel()
        def finish(tokens):
            # Verify the Google identity; never infer the account from the old connection.
            info=self.transport.request(USERINFO,token=tokens['access_token'])
            if not info.get('verified_email') or not info.get('email'):raise ValueError('Google account could not be verified.')
            value={k:config[k] for k in ('client_id','client_secret')}
            value.update(tokens=tokens,features=['mail_read'],email=info['email'],revision=time.time())
            with self.connection_store.transaction() as d:d['google']=value
            with self.lock:self.access=None
        self.oauth=OAuthSession(config,[EMAIL_SCOPE,SCOPES['mail_read']],self.transport,finish)
        self.oauth.start()
        return {'url':self.oauth.url}

    def gmail_state(self):
        config=self.google_config()
        health=self.gmail_health
        signature=(config.get('revision'),config.get('tokens',{}).get('refresh_token'))
        recent=health and health['signature']==signature and time.time()-health['at']<600
        status=('connected' if health['ok'] else 'unavailable') if recent else self.oauth.status if self.oauth else 'not_checked'
        return {'configured':bool(config.get('client_id')),'account':config.get('email',''),
                'sign_in':status,
                'error':'The latest Gmail check failed. Try checking the connection again.' if recent and not health['ok'] else self.oauth.error if self.oauth else ''}

    def snapshot(self):
        if self.path is None:return {'memories':[],'skills':[],'settings':{},'workspace':{}}
        v=Vault(self.path); v.unlock_key(self.key)
        try: return copy.deepcopy(v.data)
        finally: v.lock()

    def protected(self):
        d=self.snapshot(); s=d['settings']; google=d.get('workspace',{}).get('google',{})
        values=list(s.get('sensitive_strings',[]))
        def collect(obj):
            if isinstance(obj,dict):
                for k,v in obj.items():
                    if any(x in k.lower() for x in ('token','secret','password','passphrase','api_key','venice_key','openai_key')) and isinstance(v,str) and v: values.append(v)
                    elif isinstance(v,(dict,list)): collect(v)
            elif isinstance(obj,list):
                for x in obj: collect(x)
        collect(s);collect(google);collect(self.google_config());collect(d.get('telegram',{}));collect(d.get('whatsapp',{}))
        if self.connection_store:
            with self.connection_store.transaction() as data:
                values.extend(data.get('automatic_private_phrases',[]))
                runtime_key=data.get('dot_tunnel',{}).get('runtime_key')
                if runtime_key:values.append(runtime_key)
        return list(set(values))

    def library(self):
        d=self.snapshot()
        rows=[{'kind':kind,'source_id':x['id'],'text':x['text'],'device_only':self.private(x),'origin':'Existing local library'} for kind in ('memories','skills') for x in d[kind]]
        if self.connection_store:
            from .context import ContextHub,identity
            unique={}
            for row in rows:unique.setdefault(identity(row),[]).append(row)
            for row in ContextHub(self.connection_store,self.context_home).rows():
                signature=identity(row)
                if signature in unique:
                    for existing in unique[signature]:existing['device_only']|=row.get('device_only',False)
                else:unique[signature]=[row];rows.append(row)
        return rows

    @staticmethod
    def private(x):
        meta=x.get('meta',{})
        return x.get('privacy') in ('device','local','local_only','private_only') or meta.get('privacy') in ('local_only','private_only') or bool(meta.get('sensitive')) or meta.get('status','active')!='active'

    def google(self,path):
        with self.lock:
            google=self.google_config()
            tokens=google.get('tokens',{})
            if 'mail_read' not in google.get('features',[]) or SCOPES['mail_read'] not in tokens.get('scopes',[]):
                raise ValueError('Connect read-only Gmail in the desktop app first.')
            signature=(google.get('revision'),tokens.get('refresh_token'))
            try:
                if not self.access or self.access[0]!=signature or self.access[1]['expires_at']<time.time()+60:
                    if tokens.get('expires_at',0)<time.time()+60:
                        value=self.transport.request(TOKEN,form=True,data={'client_id':google['client_id'],'client_secret':google['client_secret'],'refresh_token':tokens['refresh_token'],'grant_type':'refresh_token'})
                        tokens=token_record(value,tokens['scopes'],tokens)
                    self.access=(signature,tokens)
                result=self.transport.request(GMAIL+path,token=self.access[1]['access_token'])
            except Exception:
                self.gmail_health={'signature':signature,'at':time.time(),'ok':False}
                raise
            self.gmail_health={'signature':signature,'at':time.time(),'ok':True}
            return result

    def discover_gmail(self,query):
        if not isinstance(query,str) or not 1<=len(query)<=500: raise ValueError('Use a short Gmail search.')
        result=self.google('/messages?'+urlencode({'q':query,'maxResults':8}))
        items=[]
        for x in result.get('messages',[]):
            if not re.fullmatch(r'[a-f0-9]{1,32}',x['id']): continue
            self.discovered.add(x['id'])
            items.append({'kind':'gmail','source_id':x['id'],**self.read('gmail',x['id'])})
        return {'items':items,'more_available':bool(result.get('nextPageToken'))}

    def search_gmail_page(self,query,cursor=None):
        if not isinstance(query,str) or not 1<=len(query)<=2000:raise ValueError('Invalid Gmail query.')
        if cursor is not None and (not isinstance(cursor,str) or len(cursor)>2000):raise ValueError('Invalid Gmail page.')
        params={'q':query,'maxResults':12,'includeSpamTrash':'true'}
        if cursor:params['pageToken']=cursor
        result=self.google('/messages?'+urlencode(params))
        items=[]
        for value in result.get('messages',[]):
            identifier=value.get('id','')
            if not re.fullmatch(r'[a-f0-9]{1,32}',identifier):continue
            items.append({'kind':'gmail','source_id':identifier,**self.read('gmail',identifier,automatic=True)})
        return {'items':items,'next_cursor':result.get('nextPageToken')}

    def read_automatic_gmail(self,identifier):
        return self.read('gmail',identifier,automatic=True)

    def read(self,kind,identifier,automatic=False):
        if kind in ('memories','skills'):
            x=next((x for x in self.library() if x['kind']==kind and x['source_id']==identifier),None)
            if not x: raise ValueError('Source no longer available.')
            return {'text':x['text'],'device_only':bool(x.get('device_only'))}
        if kind!='gmail' or not re.fullmatch(r'[a-f0-9]{1,32}',identifier): raise ValueError('Invalid source.')
        m=self.google('/messages/'+identifier+'?format=full')
        h={h['name'].lower():h['value'] for h in m.get('payload',{}).get('headers',[])}
        body,attachments=automatic_message_text(m.get('payload',{}))
        return {'text':body,'title':h.get('subject','Email'),'date':h.get('date',''),'from':h.get('from',''),'attachments_unread':bool(attachments),'device_only':False}

