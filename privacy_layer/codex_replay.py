"""Local-only replay of all general Gmail queries used by requested native tests."""
import json,time
from .sources import LocalSources
from .core import EncryptedStore,Gateway,SECRET,EMAIL
from .automatic import private_identifiers,STREET,POSTAL_LINE,PRIVATE_DOCUMENT,EMAIL_OPAQUE,clean
from .setup import ROOT

def main():
    s=LocalSources();store=EncryptedStore(ROOT/'.private/connections.enc',s.key);s.connection_store=store;g=Gateway(store,s)
    with store.transaction() as d:runs=list(d['codex_native_checks'].values())
    exposed=set();queries=set()
    for run in runs:
        for receipt in run.get('receipts',[]):
            for item in receipt['items']:
                text=item['title']+'\n'+item['text'];exposed.update(private_identifiers(text))
                exposed.update(m.group(0) for m in STREET.finditer(text));exposed.update(m.group(0) for m in POSTAL_LINE.finditer(text))
        for event in run.get('events',[]):
            item=event.get('item',{})
            if event.get('type')=='item.completed' and item.get('tool')=='search_gmail':
                args=item['arguments'];args=json.loads(args) if isinstance(args,str) else args
                if not args['query'].startswith('page:'):queries.add(args['query'])
    grant=g.create(agent='test',purpose='Local replay of native Codex Gmail privacy regressions',views=[],mode='automatic',approved=True,lifetime=900,max_calls=30)
    results=[]
    try:
        for query in sorted(queries):
            for page in range(2):
                result=g.call(grant['token'],'search_gmail',{'query':query});results.append(result);query=result.get('next_query')
                if not query:break
    finally:g.revoke(grant['id'])
    items=[i for r in results for i in r['items']];text='\n'.join(i['title']+'\n'+i['text'] for i in items);protected=s.protected()
    checks={'prior_exposed_values_absent':not any(v.casefold() in text.casefold() for v in exposed),'known_protected_values_absent':not any(clean(v).casefold() in clean(text).casefold() for v in protected if len(v)>=6),'credential_patterns_absent':not bool(SECRET.search(text)),'contact_emails_absent':not bool(EMAIL.search(text)),'receipt_registration_documents_withheld':not any(PRIVATE_DOCUMENT.search(i['title']) for i in items),'postal_lines_absent':not bool(POSTAL_LINE.search(text))}
    report={'at':time.time(),'query_count':len(queries),'live_pages':len(results),'returned_items':len(items),'checks':checks}
    with store.transaction() as d:d['codex_replay_check']=report
    (ROOT.parent/'outputs/privacy-layer/codex-local-replay.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));assert all(checks.values())

if __name__=='__main__':main()
