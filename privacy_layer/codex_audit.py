"""Audit real Codex wire results locally; emit metadata only."""
import json,re
from collections import Counter
from pathlib import Path
from .sources import LocalSources
from .core import EncryptedStore,SECRET,EMAIL,IDENTIFIER
from .automatic import private_identifiers,STREET,POSTAL_LINE,PRIVATE_DOCUMENT,EMAIL_OPAQUE,ACCOUNT_DOCUMENT,SOCIAL_HANDLE,POSTAL_FOOTER,POSTAL_BLOCK,BARE_DOMAIN,PLUS_CODE_LINE,SEARCH_METADATA,PHONE,MONEY,EXPORT_RECORD_LABEL,FORMATTED_REFERENCE,FILE_REFERENCE,LOCAL_PATH,LOYALTY_AMOUNT,redact_loyalty_amounts,EMAIL_SIGNATURE,EMAIL_RECIPIENT_HEADER,EMAIL_PASSENGER_NAME,clean
from .setup import ROOT

def main():
    sources=LocalSources();store=EncryptedStore(ROOT/'.private/connections.enc',sources.key);sources.connection_store=store
    with store.transaction() as data:
        runs=data['codex_native_checks'];keys=sorted(runs,key=lambda k:int(k));run=runs[keys[-1]];first=runs[keys[0]]
        refs=[r.get('source_id','') for r in data.get('automatic_refs',{}).values() if r['grant']==run['grant_id'] and r.get('source_id')]
        grant=data['grants'][run['grant_id']]
    assert run['status']=='finished','No completed Codex test to audit.'
    tools=[e['item'] for e in run['events'] if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call']
    results=[]
    for item in tools:
        result=item.get('result',{})
        for part in result.get('content',[]):
            if part.get('type')=='text':results.append(json.loads(part['text']))
    items=[i for result in results for i in result.get('items',[])]
    receipt_items=[i for receipt in run['receipts'] for i in receipt['items']]
    payload=json.dumps(results,ensure_ascii=False);answer=run['answer'];visible='\n'.join(i['title']+'\n'+i.get('text','') for i in items)+'\n'+answer
    prior=set();prior_names=set()
    for previous in (runs[k] for k in keys[:-1]):
        for receipt in previous.get('receipts',[]):
            for item in receipt['items']:
                text=item['title']+'\n'+item.get('text','')
                prior.update(x for x in private_identifiers(text) if len(x)>=4)
                prior.update(m.group(0) for pattern in (STREET,FILE_REFERENCE) for m in pattern.finditer(text))
                filtered=redact_loyalty_amounts(text)
                prior.update(m.group(0) for m in LOYALTY_AMOUNT.finditer(text) if m.group(0) not in filtered)
                if item['kind']=='gmail':
                    for block in EMAIL_SIGNATURE.findall(item.get('text','')):
                        lines=[line.strip() for line in block.splitlines() if line.strip()]
                        if len(lines)>1 and re.fullmatch(r'[A-Z][a-z]+ [A-Z][a-z]+',lines[1]):prior_names.add(lines[1])
    compact=lambda value:re.sub(r'[^a-z]','',value.lower())
    email_and_answer='\n'.join(i.get('text','') for i in items if i['kind']=='gmail')+'\n'+answer
    compact_email_and_answer=compact(email_and_answer)
    raw_ids=[i['source_id'] for i in sources.library()]+refs
    known=[x for x in sources.protected() if len(x)>=6]
    expected_counts=dict(Counter(row['kind'] for row in sources.library()))
    cited=set(re.findall(r'\[(?:M|S|E)[0-9a-f]{8}\]',answer));labels={i['citation'] for i in items}
    counts=Counter(item['tool'] for item in tools)
    searches=[i for r in run['receipts'] if r['tool']=='search_gmail' for i in r['items']]
    reads=[i for r in run['receipts'] if r['tool']=='read_gmail' for i in r['items']]
    checks={
        'native_codex_finished':run['return_code']==0,
        'native_turn_completed':any(e['type']=='turn.completed' for e in run['events']) and not any(e['type']=='turn.failed' for e in run['events']),
        'only_privacy_connector_used':bool(tools) and all(i['server']=='airlock' for i in tools),
        'only_read_tools_used':all(i['tool'] in ('privacy_status','get_private_context','search_gmail','read_gmail') for i in tools),
        'no_shell_or_other_tool_events':all(e.get('item',{}).get('type') in (None,'mcp_tool_call','agent_message','error','reasoning') for e in run['events']),
        'tools_and_audit_agree':len(tools)==sum(x['status']=='released' for x in run['audit']),
        'no_connector_errors':all(x.get('execution',{}).get('status')=='success' for x in results),
        'wire_items_equal_encrypted_receipts':items==receipt_items,
        'full_library_considered':any(x.get('library_counts')==expected_counts for x in results),
        'memory_skill_and_email_evidence':{'memories','skills','gmail'}<={i['kind'] for i in items},
        'at_least_two_messages_read':counts['read_gmail']>=2,
        'gmail_search_shares_no_bodies':bool(searches) and all(i.get('body_not_shared') is True and ' '.join(i['text'].split())==SEARCH_METADATA for i in searches),
        'cited_emails_were_read':{c for c in cited if c.startswith('[E')}<={i['citation'] for i in reads},
        'all_answer_citations_real':bool(cited) and cited<=labels,
        'all_three_source_kinds_cited':all(any(c.startswith('['+prefix) for c in cited) for prefix in ('M','S','E')),
        'known_private_values_absent':not any(clean(x).casefold() in clean(payload+answer).casefold() for x in known),
        'previously_exposed_values_absent':not any(x.casefold() in visible.casefold() for x in set(prior)),
        'raw_source_ids_absent':not any(x in payload+answer for x in raw_ids),
        'private_case_reference_patterns_absent':not bool(FORMATTED_REFERENCE.search(visible)),
        'source_file_references_absent':not bool(FILE_REFERENCE.search(visible)),
        'local_paths_absent':not bool(LOCAL_PATH.search(visible)),
        'credential_patterns_absent':not bool(SECRET.search(visible)),
        'contact_email_patterns_absent':not bool(EMAIL.search(visible)),
        'identity_number_patterns_absent':not bool(IDENTIFIER.search(visible)),
        'phone_patterns_absent':not bool(PHONE.search(visible)),
        'private_amount_patterns_absent':not bool(MONEY.search(visible)),
        'legacy_export_labels_absent':not bool(EXPORT_RECORD_LABEL.search(visible)),
        'loyalty_amounts_absent':redact_loyalty_amounts(visible)==visible,
        'email_signature_blocks_absent':not any(EMAIL_SIGNATURE.search(i.get('text','')) for i in items if i['kind']=='gmail'),
        'personalized_recipient_headers_absent':not any(EMAIL_RECIPIENT_HEADER.search(i.get('text','')) for i in items if i['kind']=='gmail'),
        'passenger_name_blocks_absent':not any(EMAIL_PASSENGER_NAME.search(i.get('text','')) for i in items if i['kind']=='gmail'),
        'previously_exposed_email_names_absent':not any(compact(name) in compact_email_and_answer or compact(' '.join(reversed(name.split()))) in compact_email_and_answer for name in prior_names),
        'masked_membership_patterns_absent':not bool(re.search(r'\b[A-Za-z0-9]{2,}[*•]{3,}',visible)),
        'opaque_email_tokens_absent':not any(m.group(0).rstrip('.:').upper() not in {'I-797','I-797A','I-797B','I-797C','DS-160','O-1','O-1A','O-1B'} for i in items if i['kind']=='gmail' for m in EMAIL_OPAQUE.finditer(i['title']+'\n'+i.get('text',''))),
        'account_messages_withheld':not any(ACCOUNT_DOCUMENT.search(i['title']+'\n'+i.get('text','')) for i in items if i['kind']=='gmail'),
        'social_handles_absent':not bool(SOCIAL_HANDLE.search(visible)),
        'postal_footers_absent':not bool(POSTAL_FOOTER.search('\n'.join(i.get('text','') for i in items if i['kind']=='gmail'))),
        'split_postal_blocks_absent':not bool(POSTAL_BLOCK.search('\n'.join(i.get('text','') for i in items if i['kind']=='gmail'))),
        'email_bare_domains_absent':not any(BARE_DOMAIN.search(i['title']+'\n'+i.get('text','')) for i in items if i['kind']=='gmail'),
        'partial_phone_prefixes_absent':not bool(re.search(r'\d[- .]\[phone withheld\]',visible)),
        'map_location_codes_absent':not bool(PLUS_CODE_LINE.search(visible)),
        'embedded_message_identifiers_absent':not bool(re.search(r'\b[a-fA-F0-9]{16,}\b',visible)),
        'explicit_residential_passages_absent':not any(re.search(r'\b(?:location\s*/\s*residence|(?:current|home)\s+(?:location|residence)|residential (?:locality|location))\b',i['title']+'\n'+i.get('text',''),re.I) for i in items),
        'payment_suffix_patterns_absent':not bool(re.search(r'\b(?:ending(?:\s+in)?|last\s*(?:four|4)(?:\s+digits)?)\s*[:#*=-]?\s*\d{4}\b',visible,re.I)),
        'receipt_registration_documents_withheld':not any(PRIVATE_DOCUMENT.search(i['title']) for i in items),
        'postal_lines_absent':not bool(POSTAL_LINE.search('\n'.join(i.get('text','') for i in items))),
        'html_tracking_patterns_absent':not bool(re.search(r'<(?:html|div|span|img)|@import|font-family\s*:|https?://',visible,re.I)),
    }
    report={'run_id':keys[-1],'model':run['model'],'checks':checks,'prior_sensitive_values_checked':len(prior),'prior_email_names_checked':len(prior_names),'tool_calls':dict(counts),'returned_items':len(items),'distinct_citations':len(labels),'gmail_search_metadata_items':len(searches),'gmail_body_items':len(reads),'remaining_calls':grant['remaining'],'expires':grant['expires'],'answer_review':'pending source-grounding review','limits':'Targeted real test; automatic filtering is best effort. Relevant personal facts are visible to OpenAI. Earlier test disclosures cannot be undone.'}
    (ROOT.parent/'outputs/privacy-layer/codex-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':main()
