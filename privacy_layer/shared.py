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
        if not self.grant or self.grant.get('mode')!='automatic' or self.grant.get('capabilities',{}).get('context_updates') is not True:raise Denied('Enable shared context updates for this connection in Airlock first.')
        kind={'memory':'memories','skill':'skills'}.get(kind,kind)
        if operation not in ('add','update','delete') or kind not in ('memories','skills') or type(expected_revision) is not int or expected_revision<0:raise Denied('Invalid context change.')
        if not isinstance(reference,str) or not isinstance(text,str) or len(text)>12000 or operation!='delete' and not text.strip():raise Denied('Use a short context note.')
        from .automatic import sanitize
        safe=sanitize(text,self.g.sources.protected()) if operation!='delete' else ''
        if operation!='delete' and not safe:raise Denied('This note is private or contains no shareable context. Add it locally in the control panel.')
        with self.g.store.transaction() as d:
            current=d['grants'].get(self.grant['id'],{})
            if current.get('revoked') or current.get('expires',0)<=self.g.clock() or current.get('mode')!='automatic' or current.get('policy_revision')!=self.grant.get('policy_revision') or current.get('capabilities',{}).get('context_updates') is not True:raise Denied('Context update permission changed.')
            notes=d.setdefault('shared_context',{})
            if operation=='add':
                if reference or expected_revision:raise Denied('A new note has no reference and uses revision zero.')
                active=[x for x in notes.values() if not x.get('deleted')]
                if len(active)>=2000:raise Denied('Manage old shared notes in the control panel before adding more.')
                # Retried adds do not create duplicates, even from another agent.
                previous=next(((k,v) for k,v in notes.items() if not v.get('deleted') and v['text']==safe and v['kind']==kind),None)
                if previous:return {'reference':previous[0],'revision':previous[1]['revision'],'changed':False,'text':safe,'status':'existing agent note, not independently verified'}
                reference='note_'+secrets.token_hex(12);old=None;revision=1
            else:
                old=notes.get(reference)
                if not old or old.get('deleted'):raise Denied('That shared note is unavailable. Original imported or linked sources cannot be edited here.')
                if old['revision']!=expected_revision:raise Denied('This note changed in another agent. Refresh the context and use its current revision before editing.')
                if old['kind']!=kind:raise Denied('A note cannot change its source type.')
                revision=old['revision']+1
            history=d.setdefault('context_changes',[])
            history.append({'reference':reference,'before':copy.deepcopy(old),'operation':operation,'revision':revision,'agent':self.grant['id'],'at':self.g.clock()});d['context_changes']=history[-200:]
            notes[reference]={'text':safe,'kind':kind,'revision':revision,'agent':current['agent'],'updated_at':self.g.clock(),'deleted':operation=='delete'}
        return {'reference':reference,'revision':revision,'changed':True,'text':safe,'status':'deleted' if operation=='delete' else 'agent-authored note; unverified until the owner confirms it','privacy':'Detected private details were filtered before this shared note was saved.'}
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
