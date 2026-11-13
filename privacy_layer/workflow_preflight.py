"""Check relevant live outputs locally before the requested full Codex run.

No model receives this replay. Personal evidence is saved only in the encrypted
owner store; terminal output and the report contain counts and check results.
"""
import argparse,json,re,time
from collections import Counter
from .sources import LocalSources
from .core import EncryptedStore,Gateway
from .setup import ROOT
from .import_live_check import inspect_text
from .automatic import EMAIL_OPAQUE,SEARCH_METADATA,private_identifiers,STREET,POSTAL_LINE,SOCIAL_HANDLE,POSTAL_BLOCK,BARE_DOMAIN,FORMATTED_REFERENCE,redact_loyalty_amounts,EMAIL_SIGNATURE,EMAIL_RECIPIENT_HEADER


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--replay-run');options=parser.parse_args()
    sources=LocalSources();store=EncryptedStore(ROOT/'.private/connections.enc',sources.key);sources.connection_store=store
    library=sources.library();protected=sources.protected();gateway=Gateway(store,sources)
    with store.transaction() as data:
        prior=[i for r in data.get('codex_native_checks',{}).values() for receipt in r.get('receipts',[]) for i in receipt['items']]
        replay=data.get('codex_native_checks',{}).get(options.replay_run) if options.replay_run else None
    contexts=['career partnerships recruiter introduction writing style','US visa interview travel plans status factual accuracy']
    queries=['{visa passport consulate "documents ready"} after:2026/09/01','{itinerary "boarding pass" "e-ticket" "flight confirmation"} after:2026/09/01']
    if options.replay_run:
        if not replay:raise ValueError('Requested local replay not found.')
        contexts=[];queries=[]
        for event in replay['events']:
            item=event.get('item',{})
            if event['type']!='item.completed' or item.get('type')!='mcp_tool_call':continue
            args=item['arguments'];args=json.loads(args) if isinstance(args,str) else args
            if item['tool']=='get_private_context':contexts.append(args['query'])
            elif item['tool']=='search_gmail' and not args['query'].startswith('page:'):queries.append(args['query'])
        assert 1<=len(contexts)<=3 and 1<=len(queries)<=2
    previously_exposed=set()
    for item in prior:
        text=item['title']+'\n'+item.get('text','')
        previously_exposed.update(private_identifiers(text))
        previously_exposed.update(m.group(0) for p in (STREET,POSTAL_LINE) for m in p.finditer(text))
    grant=gateway.create(agent='test',purpose='Local preflight for requested full Codex workflow',views=[],mode='automatic',approved=True,lifetime=900,max_calls=40)
    results=[];seen=set();run_id=str(time.time_ns())
    try:
        for query in contexts:
            results.append(gateway.call(grant['token'],'get_private_context',{'query':query}))
        for query in queries:
            result=gateway.call(grant['token'],'search_gmail',{'query':query});results.append(result)
            for item in result['items']:
                if item['citation'] in seen:continue
                seen.add(item['citation'])
                results.append(gateway.call(grant['token'],'read_gmail',{'reference':item['ref']}))
        items=[i for r in results for i in r.get('items',[])]
        text='\n'.join(i['title']+'\n'+i['text'] for i in items)
        with store.transaction() as data:
            ids=[v['source_id'] for v in data.get('automatic_refs',{}).values() if v['grant']==grant['id'] and v.get('source_id')]
        checks=inspect_text(text,protected,[i['source_id'] for i in library]+ids)
        email_items=[i for i in items if i['kind']=='gmail']
        email_text='\n'.join(i['title']+'\n'+i['text'] for i in email_items)
        checks.update(full_library_considered=all(r['library_counts']==dict(Counter(x['kind'] for x in library)) for r in results if 'library_counts' in r),
            live_email_bodies_checked=any(r['execution']['tool']=='read_gmail' and r['items'] for r in results),
            search_bodies_absent=all(i['body_not_shared'] and ' '.join(i['text'].split())==SEARCH_METADATA for r in results if r['execution']['tool']=='search_gmail' for i in r['items']),
            prior_exposed_values_absent=not any(x.casefold() in text.casefold() for x in previously_exposed),
            opaque_email_codes_absent=not any(m.group(0).rstrip('.:').upper() not in {'I-797','I-797A','I-797B','I-797C','DS-160','O-1','O-1A','O-1B'} for m in EMAIL_OPAQUE.finditer(email_text)),
            social_handles_absent=not bool(SOCIAL_HANDLE.search(text)),
            split_postal_blocks_absent=not bool(POSTAL_BLOCK.search(email_text)),
            email_domains_absent=not bool(BARE_DOMAIN.search(email_text)),
            loyalty_amounts_absent=redact_loyalty_amounts(text)==text,
            email_signature_blocks_absent=not bool(EMAIL_SIGNATURE.search(email_text)),
            personalized_recipient_headers_absent=not bool(EMAIL_RECIPIENT_HEADER.search(email_text)),
            private_case_reference_patterns_absent=not bool(FORMATTED_REFERENCE.search(text)),
            payment_suffixes_absent=not bool(re.search(r'\b(?:ending(?:\s+in)?|last\s*(?:four|4)(?:\s+digits)?)\s*[:#*=-]?\s*\d{4}\b',text,re.I)),
            html_tracking_absent=not bool(re.search(r'<(?:html|div|span|img)|@import|font-family\s*:|https?://',text,re.I)))
        if options.replay_run:
            checks.update(passport_return_evidence_found='ready to be returned' in email_text,
                          actual_travel_evidence_found='ultimately traveled' in email_text and 'November 2, 2026' in email_text)
        report={'run_id':run_id,'replayed_native_run':options.replay_run,'checks':checks,'library_counts':dict(Counter(x['kind'] for x in library)),
                'queries':len(queries),'emails_read_locally':len(seen),'tool_calls':len(results),'sent_to_model':False,'passed':all(checks.values())}
        with store.transaction() as data:data.setdefault('workflow_preflight_checks',{})[run_id]={'results':results,'report':report}
        (ROOT.parent/'outputs/privacy-layer/workflow-preflight.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)
        if not report['passed']:raise SystemExit(1)
    finally:gateway.revoke(grant['id'])


if __name__=='__main__':main()
