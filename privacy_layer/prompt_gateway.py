"""Owner-enabled text gateway, with a separate in-memory credential per client."""
import asyncio
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math
import re
import secrets
import threading

import httpx
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .automatic import PHONE, clean, sanitize
from .core import Denied, EMAIL, URL
from .local_provider import LOCAL_BASE, LocalProvider
from .privacy_engine import ORGANIZATION, PERSON, PrivacyEngine, sensitive

DESTINATIONS = {
    'ollama': LOCAL_BASE + '/v1/chat/completions',
    'openai': 'https://api.openai.com/v1/chat/completions',
}
BODY_LIMIT = 128 * 1024
MAX_CALLS = 100
TTL = 24 * 3600
NO_STORE = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
MESSAGES_ERROR = 'Use 1–64 plain text messages. Files, tool calls and media are unsupported.'
# Also handle JSON/YAML snippets embedded inside otherwise plain text messages.
SECRET_LABEL = re.compile(
    r'''(?ix)(?<!\w)["']?(?:api[ _-]?key|authorization|password|passphrase|'''
    r'''client[ _-]?secret|access[ _-]?token|refresh[ _-]?token|private[ _-]?key)["']?'''
    r'''[ \t]*[:=][ \t]*(?:"([^"\r\n]+)"|'([^'\r\n]+)'|([^,;\s}]+))'''
)
GATEWAY_KEY = re.compile(r'(?<!\w)(?:alp|pal)_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])')
CONTACT_PHONE = re.compile(r'(?<!\w)(?:\+1[ .-]?)?\(\d{3}\)[ ]?\d{3}[ .-]?\d{4}(?!\w)')
PRIVATE_MATERIAL = re.compile(r'-----\s*(?:BEGIN|END)\b|\bdata:[^\s,]{0,128};base64,', re.I)
LOWERCASE_NAME = re.compile(r"(?:\b(?:full name|my name|contact name|patient name|name|employer|company|organization|organisation)\s*(?:is\b|:|=)\s*)([^\n.!?,;]{1,160})", re.I)


class ClientError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


@dataclass
class Client:
    id: str
    name: str
    provider: str
    model: str
    expires_at: int
    token_hash: bytes = field(repr=False)
    api_key: str = field(repr=False)
    aliases: dict = field(default_factory=dict, repr=False)
    calls: int = 0
    active: int = 0

    def public(self):
        return dict(id=self.id, name=self.name, model=self.model, provider=self.provider,
                    expires_at=self.expires_at, calls=self.calls, limit=MAX_CALLS)


def parse_messages(messages):
    if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
        raise ClientError(400, MESSAGES_ERROR)
    checked = []
    for entry in messages:
        if (not isinstance(entry, dict) or set(entry) != {'role','content'}
                or entry['role'] not in ('system','developer','user','assistant')):
            raise ClientError(400, MESSAGES_ERROR)
        content = entry['content']
        if isinstance(content, list):
            if not 1 <= len(content) <= 32 or any(
                not isinstance(part,dict) or set(part) != {'type','text'}
                or part['type'] != 'text' or not isinstance(part['text'],str) for part in content
            ):
                raise ClientError(400, MESSAGES_ERROR)
            content = ''.join(part['text'] for part in content)
        if not isinstance(content,str) or not content.strip() or len(content)>12000:
            raise ClientError(400, MESSAGES_ERROR)
        try:
            content.encode('utf-8', 'strict')
        except UnicodeEncodeError:
            raise ClientError(400, MESSAGES_ERROR) from None
        checked.append({'role':entry['role'], 'content':clean(content)})
    return checked


def parse_chat(body):
    allowed = {'model','messages','stream','temperature','max_tokens','max_completion_tokens'}
    if not isinstance(body,dict) or set(body) - allowed or body.get('model') != 'airlock':
        raise ClientError(400, 'Choose model airlock. Only basic text chat parameters are supported.')
    stream = body.get('stream', False)
    budget = body.get('max_completion_tokens', body.get('max_tokens', 1024))
    if (type(stream) is not bool or type(budget) is not int or not 1 <= budget <= 4096
            or 'max_tokens' in body and 'max_completion_tokens' in body):
        raise ClientError(400, 'Invalid streaming or output token setting.')
    params = {}
    if 'temperature' in body:
        t = body['temperature']
        if type(t) not in (int,float) or not 0 <= t <= 2 or not math.isfinite(t):
            raise ClientError(400, 'Invalid temperature.')
        params['temperature'] = t
    return parse_messages(body.get('messages')), params, budget, stream


def parse_responses(body):
    """Translate the stateless text subset into the same strict chat boundary."""
    allowed = {'model', 'input', 'instructions', 'max_output_tokens', 'temperature', 'store', 'stream'}
    if (not isinstance(body, dict) or set(body) - allowed or body.get('store', False) is not False):
        raise ClientError(400, 'Use a stateless text request. Tools, saved conversations and storage are unsupported.')
    messages = []
    if 'instructions' in body:
        if not isinstance(body['instructions'], str):
            raise ClientError(400, 'Instructions must be text.')
        messages.append({'role': 'system', 'content': body['instructions']})
    items = body.get('input')
    if isinstance(items, str):
        messages.append({'role': 'user', 'content': items})
    elif isinstance(items, list) and 1 <= len(items) <= 64:
        for item in items:
            if (not isinstance(item, dict) or set(item) - {'type', 'role', 'content'}
                    or item.get('type', 'message') != 'message' or 'content' not in item):
                raise ClientError(400, MESSAGES_ERROR)
            content, role = item['content'], item.get('role')
            if isinstance(content, list):
                parts = []
                for part in content:
                    if (not isinstance(part, dict) or set(part) != {'type', 'text'}
                            or part['type'] != 'input_text' and not (role == 'assistant' and part['type'] == 'output_text')):
                        raise ClientError(400, MESSAGES_ERROR)
                    parts.append({'type': 'text', 'text': part['text']})
                content = parts
            messages.append({'role': role, 'content': content})
    else:
        raise ClientError(400, MESSAGES_ERROR)
    chat = {k: body[k] for k in ('model', 'temperature', 'stream') if k in body}
    if 'max_output_tokens' in body:
        chat['max_completion_tokens'] = body['max_output_tokens']
    return parse_chat({**chat, 'messages': messages})


def responses_result(text, finish, created, budget, params, stream):
    status = 'incomplete' if finish == 'length' else 'completed'
    part = {'type': 'output_text', 'text': text, 'annotations': []}
    item = {'id': 'msg_' + secrets.token_hex(10), 'type': 'message', 'role': 'assistant',
            'status': status, 'content': [part]}
    result = {
        'id': 'resp_' + secrets.token_hex(10), 'object': 'response', 'created_at': created,
        'status': status, 'error': None, 'model': 'airlock', 'output': [item],
        'incomplete_details': {'reason': 'max_output_tokens'} if finish == 'length' else None,
        'instructions': None, 'max_output_tokens': budget, 'parallel_tool_calls': False,
        'previous_response_id': None, 'store': False, 'temperature': params.get('temperature'),
        'text': {'format': {'type': 'text'}}, 'tool_choice': 'none', 'tools': [], 'usage': None,
        'metadata': {},
    }
    if not stream:
        return JSONResponse(result, headers=NO_STORE)
    # Emit a single buffered text part using Responses SSE lifecycle event types.
    pending_item = {**item, 'status': 'in_progress', 'content': []}
    pending_part = {**part, 'text': ''}
    index = {'item_id': item['id'], 'output_index': 0, 'content_index': 0}
    events = [
        ('response.created', {'response': {**result, 'output': [], 'status': 'in_progress', 'incomplete_details': None}}),
        ('response.output_item.added', {'output_index': 0, 'item': pending_item}),
        ('response.content_part.added', {**index, 'part': pending_part}),
        ('response.output_text.delta', {**index, 'delta': text, 'logprobs': []}),
        ('response.output_text.done', {**index, 'text': text, 'logprobs': []}),
        ('response.content_part.done', {**index, 'part': part}),
        ('response.output_item.done', {'output_index': 0, 'item': item}),
        ('response.' + status, {'response': result}),
    ]
    chunks = []
    for seq, (kind, data) in enumerate(events):
        event = json.dumps({**data, 'type': kind, 'sequence_number': seq})
        chunks.append(f'event: {kind}\ndata: {event}\n\n')
    return Response(''.join(chunks), media_type='text/event-stream', headers=NO_STORE)


def strict_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Duplicate field.')
        obj[key] = value
    return obj


class PromptGateway:
    def __init__(self, gateway, port, transport=None):
        self.gateway, self.port, self.transport = gateway, port, transport
        self.base_url = f'http://127.0.0.1:{port}/v1'
        self.clients = {}
        self.lock = threading.RLock()
        self.closed = False

    def prune(self):
        now = self.gateway.clock()
        for identifier in list(self.clients):
            if self.clients[identifier].expires_at <= now:
                del self.clients[identifier]

    def close(self):
        with self.lock:
            self.closed = True
            self.clients.clear()

    def owner(self, action, body):
        with self.lock:
            self.prune()
            if self.closed or getattr(self.gateway.sources,'demo_only',False) or getattr(self.gateway.sources,'memory_demo',False):
                raise Denied('Open the personal workspace again.')
            if action == 'prompt-status' and not body:
                return {'base_url':self.base_url,'clients':[c.public() for c in self.clients.values()]}
            if action == 'prompt-revoke' and set(body)=={'id'} and isinstance(body['id'],str):
                self.clients.pop(body['id'], None)
                return {'revoked':True}
            if (action != 'prompt-create' or set(body) - {'name','approved','model','provider','api_key'}
                    or body.get('approved') is not True):
                raise Denied('Confirm a text model connection and its destination.')
            provider = body.get('provider','ollama')
            name, model, key = body.get('name'), body.get('model'), body.get('api_key','')
            if not isinstance(name,str) or not 1 <= len(name.strip()) <= 64 or not name.isprintable():
                raise Denied('Use a client name of 1–64 characters.')
            if (provider not in ('ollama','openai') or not isinstance(model,str) or len(model)>120
                    or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)*(?::[A-Za-z0-9_.-]+)?',model)):
                raise Denied('Choose a supported provider and model name.')
            if provider == 'ollama' and (key != '' or 'cloud' in model.lower()):
                raise Denied('Use an installed local Ollama model without an API key.')
            if provider == 'openai' and (not isinstance(key,str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{12,512}',key)):
                raise Denied('Enter an OpenAI API key to enable sending filtered text to OpenAI.')
            if len(self.clients)>=24:
                raise Denied('Remove an existing model connection first.')
            token = 'alp_' + secrets.token_urlsafe(32)
            client = Client(secrets.token_hex(8),name.strip(),provider,model,int(self.gateway.clock()) + TTL,
                            hashlib.sha256(token.encode()).digest(),key)
            self.clients[client.id] = client
            return {'id':client.id,'token':token,'model':'airlock','base_url':self.base_url,'expires_at':client.expires_at}

    def authorize(self, client, *, budget=False):
        with self.lock:
            self.prune()
            if self.clients.get(client.id) is not client:
                raise ClientError(401, 'This model connection has expired or was revoked.')
            if budget and client.calls >= MAX_CALLS:
                raise ClientError(429, 'The connection has reached its call limit.')

    def identify(self, req):
        if (req.headers.getlist('host') not in ([f'127.0.0.1:{self.port}'],[f'localhost:{self.port}'])
                or 'origin' in req.headers):
            raise ClientError(403, 'Use the loopback endpoint from a local client.')
        auth = req.headers.getlist('authorization')
        if len(auth)!=1 or not re.fullmatch(r'Bearer alp_[A-Za-z0-9_-]{43}',auth[0]):
            raise ClientError(401, 'A model connection key is required.')
        digest = hashlib.sha256(auth[0][7:].encode()).digest()
        with self.lock:
            self.prune()
            for client in self.clients.values():
                if hmac.compare_digest(client.token_hash,digest):
                    self.authorize(client,budget=True)
                    return client
        raise ClientError(401, 'Invalid model connection key.')

    def screen(self, client, messages):
        # Local policy is read at each call. Only the per-connection identity
        # dictionary remains in process memory. No prompts are written to the vault.
        protected = [clean(v) for v in self.gateway.sources.protected() if isinstance(v,str) and v.strip()]
        if client.api_key:
            protected.append(client.api_key)
        for msg in messages:
            for match in SECRET_LABEL.finditer(msg['content']):
                protected.append(next(value for value in match.groups() if value is not None))
        if len(protected)>4096:
            raise ClientError(400,'Too many private values to screen this request safely.')
        protected = sorted(set(protected),key=len,reverse=True)
        engine = PrivacyEngine(self.gateway, {'id':client.id})
        with self.lock:
            self.authorize(client)
            identities = dict(client.aliases)
            for msg in messages:
                text = msg['content']
                if PRIVATE_MATERIAL.search(text):
                    raise ClientError(400, 'A key block or encoded attachment cannot be sent.')
                for kind, pattern in (('person', PERSON), ('organization',ORGANIZATION)):
                    for match in pattern.finditer(text):
                        value = match.group(1)
                        identities[value.casefold()] = engine.pseudonym(kind,value)
                # A lower-case label on one turn can identify an unlabelled
                # repeat on another. Retain only bounded, explicitly labelled names.
                for match in LOWERCASE_NAME.finditer(text):
                    candidate = match.group(1).strip()
                    if re.fullmatch(r"[^\W\d_][\w’'-]*(?:[ \t]+[^\W\d_][\w’'-]*){0,3}",candidate):
                        kind = 'organization' if re.match(r'employer|company|organi',match.group(0),re.I) else 'person'
                        identities.setdefault(candidate.casefold(),engine.pseudonym(kind,candidate))
            if len(identities)>256:
                raise ClientError(400, 'The connection reached its identity limit. Create a new connection.')
            client.aliases = identities
        match_alias = None
        if identities:
            match_alias = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(k) for k in sorted(identities,key=len,reverse=True)) + r')(?!\w)', re.I)
        checked = []
        for msg in messages:
            value = msg['content']
            value = SECRET_LABEL.sub('[credential withheld]',value)
            value = GATEWAY_KEY.sub('[credential withheld]',value)
            for phrase in protected:
                value = re.sub(re.escape(phrase),'[private value withheld]',value,flags=re.I)
            if match_alias:
                value = match_alias.sub(lambda m:identities.get(m.group().casefold(),'[identity withheld]'),value)
            # Withhold unrecognized/uncapitalized identity labels conservatively.
            value = LOWERCASE_NAME.sub(lambda m:m.group(0) if m.group(1).startswith(('[person-', '[organization-'))
                                       else '[identity withheld]',value)
            # Do not tokenize contact data inside URLs or keys before those rules run.
            value = URL.sub('[link withheld]',value)
            value = EMAIL.sub(lambda m:engine.pseudonym('email',m.group()),value)
            value = CONTACT_PHONE.sub(lambda m:engine.pseudonym('phone',m.group()),value)
            value = PHONE.sub(lambda m:engine.pseudonym('phone',m.group()),value)
            value = sanitize(value,protected)
            if not value or sensitive(value):
                value = '[private passage withheld]'
            checked.append({'role':msg['role'],'content':value})
        return checked

    async def upstream(self, client, messages, params, budget):
        body = dict(model=client.model,messages=messages,stream=False,**params)
        headers = {}
        if client.provider=='openai':
            body.update(max_completion_tokens=budget,store=False)
            headers['Authorization'] = 'Bearer ' + client.api_key
        else:
            body['max_tokens'] = budget
        local = LocalProvider(transport=self.transport,timeout=60)
        async with asyncio.timeout(65), local.client() as connection:
            if client.provider=='ollama':
                await local._preflight(connection,client.model)
            with self.lock:
                self.authorize(client,budget=True)
                client.calls += 1
            async with connection.stream('POST',DESTINATIONS[client.provider],json=body,headers=headers) as response:
                if response.status_code != 200:
                    raise ClientError(502,'The selected model declined the request.')
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk)>256*1024:
                        raise ClientError(502,'The model response exceeded the text limit.')
                    raw.extend(chunk)
        reply = json.loads(raw)
        choices = reply['choices']
        if not isinstance(choices,list) or len(choices)!=1:
            raise ValueError('Invalid model response.')
        choice = choices[0]
        message, finish = choice['message'], choice['finish_reason']
        text = message['content']
        if (message.get('role') != 'assistant' or message.get('tool_calls') or message.get('function_call')
                or not isinstance(text,str) or not 0 < len(text) <= 32768 or finish not in ('stop','length')):
            raise ClientError(502, 'The model did not return a supported text reply.')
        return text, finish

    async def handle(self, req):
        try:
            client = self.identify(req)
            if req.url.path == '/v1/models':
                return JSONResponse({'object':'list','data':[{'id':'airlock','object':'model',
                                    'created':0,'owned_by':'airlock'}]},headers=NO_STORE)
            if req.headers.get('content-type','').split(';')[0].strip().lower() != 'application/json' or req.headers.get('content-encoding','identity') != 'identity':
                raise ClientError(415,'Send an uncompressed JSON chat request.')
            data = bytearray()
            async for chunk in req.stream():
                if len(chunk) + len(data)>BODY_LIMIT:
                    raise ClientError(413,'Chat request exceeds 128 KB.')
                data.extend(chunk)
            try:
                body = json.loads(data.decode('utf-8'), object_pairs_hook=strict_object)
            except (ValueError, RecursionError):
                raise ClientError(400,'Invalid JSON chat request.') from None
            is_responses = req.url.path == '/v1/responses'
            parse = parse_responses if is_responses else parse_chat
            messages, params, budget, stream = parse(body)
            with self.lock:
                self.authorize(client,budget=True)
                if client.active>=2:
                    raise ClientError(429,'Two model requests are already running.')
                client.active+=1
            try:
                messages = await asyncio.to_thread(self.screen,client,messages)
                text, finish = await self.upstream(client,messages,params,budget)
                self.authorize(client)
            finally:
                with self.lock:
                    client.active-=1
            created = int(self.gateway.clock())
            if is_responses:
                return responses_result(text,finish,created,budget,params,stream)
            result = dict(id='chatcmpl-'+secrets.token_hex(10), created=created, model='airlock')
            assistant = {'role':'assistant','content':text}
            if stream:
                # Buffer the upstream reply. Emit only the permitted assistant text
                # and finish reason, never provider metadata or hidden fields.
                result['object']='chat.completion.chunk'
                events = []
                for delta,reason in ((assistant,None),({},finish)):
                    value = dict(result,choices=[{'index':0,'delta':delta,'finish_reason':reason}])
                    events.append('data: '+json.dumps(value)+'\n\n')
                return Response(''.join(events)+'data: [DONE]\n\n',media_type='text/event-stream',headers=NO_STORE)
            result.update(object='chat.completion',choices=[{'index':0,'message':assistant,'finish_reason':finish}])
            return JSONResponse(result,headers=NO_STORE)
        except ClientError as e:
            status, message = e.status, e.message
        except (TimeoutError,httpx.TimeoutException):
            status, message = 504,'The selected model timed out.'
        except Exception:
            status, message = 502,'The selected model or local filter is unavailable.'
        return JSONResponse({'error':{'message':message,'type':'airlock_error'}},status_code=status,headers=NO_STORE)

    def routes(self):
        return [Route('/v1/models',self.handle,methods=['GET']),
                Route('/v1/chat/completions',self.handle,methods=['POST']),
                Route('/v1/responses',self.handle,methods=['POST'])]
