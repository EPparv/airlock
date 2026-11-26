"""Bounded, permission-filtered context pages. Retrieval runs on-device."""
import copy
import secrets
from .core import Denied, digest

PAGE_PREFIX='airlock-context-page:'
PAGE_CHARS=48000
PAGE_ITEMS=12
CORE_ITEMS=6
CORE_CHARS=4000


def select(gateway, grant, rows, query):
    """Caller supplies only authorized, filtered rows. Cursors are connection-bound."""
    from .automatic import ranked
    from .privacy_engine import minimize
    from .semantic import related_plan, related_rows
    fingerprint=digest(sorted(rows,key=lambda row:row['ref']))
    offset=0
    plan=None
    if query.startswith(PAGE_PREFIX):
        with gateway.store.transaction() as data:
            saved=copy.deepcopy(data.get('context_pages',{}).get(query[len(PAGE_PREFIX):]))
        if not saved or saved['grant']!=grant['id'] or saved['expires']<=gateway.clock():
            raise Denied('This context page expired or belongs to another connection. Search again.')
        if saved['fingerprint']!=fingerprint or saved['policy_revision']!=grant.get('policy_revision',0):
            raise Denied('Context or permissions changed. Repeat the original question for current context.')
        query,offset=saved['query'],saved['offset']
        # Older cursors used lexical ranking only. A continuation must keep the
        # original order even if the OS embedding becomes available mid-search.
        plan=saved.get('related', {'matches': [], 'model_passages': 0, 'model': None})
    core=[row for row in rows if row.get('core') and len(row['text'])<=CORE_CHARS][:CORE_ITEMS]
    core_refs={row['ref'] for row in core}
    ordered=ranked(rows,query) if query.strip() else rows
    if plan is None:
        plan=related_plan(rows,query,ordered)
    candidates=[row for row in ordered if row['ref'] not in core_refs]
    related=list(related_rows(rows,plan))
    candidates=candidates[:4]+related[:2]+candidates[4:]+related[2:]
    # Long records remain available in explicit consecutive parts, never discarded.
    parts=[]
    for row in candidates:
        text=row['text']; minimized=row.get('context_minimized',False)
        if row['kind']!='skills' and 'match_basis' not in row: text,minimized=minimize(text,query)
        total=max(1,(len(text)+11999)//12000)
        for i in range(total):
            parts.append({**row,'text':text[i*12000:(i+1)*12000],
                          'part':i+1,'parts':total,'text_complete':total==1 and not minimized,
                          'context_minimized':minimized})
    selected=[{**row,'part':1,'parts':1,'text_complete':True,'selection':'core profile'} for row in core]
    size=sum(len(row['text']) for row in selected);end=offset
    while end<len(parts) and len(selected)<PAGE_ITEMS:
        row=parts[end]
        if size+len(row['text'])>PAGE_CHARS:break
        selected.append({**row,'selection':'relevant context'});size+=len(row['text']);end+=1
    next_query=None
    if end<len(parts):
        token=secrets.token_urlsafe(24)
        with gateway.store.transaction() as data:
            pages={k:v for k,v in data.get('context_pages',{}).items() if v['expires']>gateway.clock()}
            if len(pages)>=500:pages=dict(sorted(pages.items(),key=lambda x:x[1]['expires'])[-499:])
            pages[token]={'grant':grant['id'],'fingerprint':fingerprint,'policy_revision':grant.get('policy_revision',0),
                          'query':query,'offset':end,'related':plan,'expires':min(grant['expires'],gateway.clock()+1800)}
            data['context_pages']=pages
        next_query=PAGE_PREFIX+token
    return {'items':selected,'context_fingerprint':fingerprint,'checked_at':gateway.clock(),
            'core_included':len(core),'core_overflow':max(0,sum(bool(r.get('core')) for r in rows)-len(core)),
            'recall':{'related_matches':len(plan['matches']),'sentence_model':plan['model'],
                      'passages_scored_by_model':plan['model_passages']},
            'next_query':next_query,'more_available':bool(next_query),
            'continuity':'Refresh context before substantive personalized answers and after session compaction. Follow next_query unchanged when more detail is needed. Do not treat a search miss as absence. Propose explicit durable corrections for owner review; do not silently overwrite facts.'}
