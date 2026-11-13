"""Versioned shared context, with explicit agent write access and optimistic edits.

Original sources are read-only. Agent changes have provenance and can be undone
locally; model-inferred facts never become confirmed user facts automatically.
"""
import copy,hashlib,json,secrets
from datetime import datetime,timezone
from .core import Denied,canonical

class SharedContext:
    def __init__(self,gateway,grant=None):self.g=gateway;self.grant=grant
    def status(self):
        rows=self.g.sources.library()
        fingerprint=hashlib.sha256(canonical(sorted((r['kind'],r['source_id'],r['text'],bool(r.get('device_only')),r.get('revision',0),r.get('package_digest','')) for r in rows))).hexdigest()
        with self.g.store.transaction() as d:
            state=d.setdefault('context_clock',{'revision':0})
            if state.get('fingerprint')!=fingerprint:state.update(fingerprint=fingerprint,revision=state['revision']+1,changed_at=self.g.clock())
            revision=state['revision']
        return {'revision':revision,'checked_at':datetime.fromtimestamp(self.g.clock(),timezone.utc).isoformat(),'counts':{k:sum(r['kind']==k for r in rows) for k in ('memories','skills')},'updates_enabled':bool(self.grant and self.grant.get('capabilities',{}).get('context_updates')),'coverage':'All agents read the same live library on each request. Linked files are refreshed when read; Gmail is queried live. This does not rewrite another app’s internal memory or watch its hidden chat history.'}
    def change(self,operation,kind,text,reference,expected_revision):
        from .agent_memory import AgentMemory
        if not self.grant:
            raise Denied('An agent connection is required.')
        return AgentMemory(self.g).propose(self.grant, operation, kind, text, reference, expected_revision)
    def owner_list(self):
        with self.g.store.transaction() as d:return {'items':[dict(reference=k,**v) for k,v in d.get('shared_context',{}).items() if not v.get('deleted')],'history':[{'reference':x['reference'],'operation':x['operation'],'revision':x['revision'],'at':x['at']} for x in reversed(d.get('context_changes',[]))]}
    def undo(self,reference,expected_revision):
        with self.g.store.transaction() as d:
            current=d.get('shared_context',{}).get(reference)
            if not current or current['revision']!=expected_revision:raise Denied('The note changed. Refresh before undoing.')
            previous=next((x for x in reversed(d.get('context_changes',[])) if x['reference']==reference and x['revision']==expected_revision),None)
            if not previous:raise Denied('The previous version is no longer available.')
            restored=copy.deepcopy(previous['before']) or {**current,'text':'','deleted':True}
            restored.update(revision=expected_revision+1,updated_at=self.g.clock(),agent='owner')
            d['shared_context'][reference]=restored
        return {'restored':True}
