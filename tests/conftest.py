import copy
import pytest
from privacy_layer.core import Gateway,EncryptedStore

class Sources:
    def __init__(self):
        self.data={('memories','m1'):{'text':'O-1 interview planned for October 15 in Hyderabad. Unshared balance: HIDDEN_FINANCE_CANARY.','device_only':False},
                   ('memories','m2'):{'text':'PRIVATE_MEDICAL_CANARY','device_only':True},
                   ('skills','s1'):{'text':'Lead with the answer. Be concise; separate evidence from assumptions.','device_only':False},
                   ('gmail','e1'):{'text':'October 21: Documents ready for pickup. Passport identifier: HIDDEN_PASSPORT_CANARY.','date':'2026-10-21','device_only':False}}
        self.secrets=['PRIVATE_CREDENTIAL_CANARY']
        self.hook=None
    def read(self,k,i):
        if self.hook:self.hook()
        return copy.deepcopy(self.data[k,i])
    def protected(self):return self.secrets
    def library(self):return [{'kind':k,'source_id':i,**v} for (k,i),v in self.data.items() if k!='gmail']
    def discover_gmail(self,q):return {'items':[{'kind':'gmail','source_id':'e1',**self.data['gmail','e1']}],'more_available':False}

@pytest.fixture
def bundle(tmp_path):
    s=Sources();now=[1800000000];g=Gateway(EncryptedStore(tmp_path/'test.enc',b'x'*32),s,lambda:now[0])
    views=[{'kind':'memories','source_id':'m1','title':'Interview background','text':'O-1 interview planned for October 15 in Hyderabad.'},
           {'kind':'skills','source_id':'s1','title':'Answer style','text':s.data['skills','s1']['text']},
           {'kind':'gmail','source_id':'e1','title':'Visa document pickup notice','text':'October 21, 2026: Documents are ready for pickup. No visa decision is stated.'}]
    def make(**kw):return g.create(agent='test',purpose='Interview preparation',views=views,approved=True,**kw)
    return g,s,now,views,make
