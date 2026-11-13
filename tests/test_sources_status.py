import copy
import time
import pytest
from privacy_layer.sources import LocalSources, SCOPES


def source():
    class Transport:
        fail=False
        def request(self,*args,**kwargs):
            if self.fail:raise ValueError('PRIVATE_PROVIDER_ERROR')
            return {'messagesTotal':1}
    s=LocalSources(key=b'k'*32,transport=Transport())
    config={'client_id':'example','revision':1,'email':'test@example.com','features':['mail_read'],'tokens':{'access_token':'fictional','refresh_token':'fictional-refresh','scopes':[SCOPES['mail_read']],'expires_at':time.time()+3600}}
    s.google_config=lambda:copy.deepcopy(config)
    return s,config


def test_gmail_status_tracks_actual_success_and_failure_without_provider_details():
    s,_=source()
    assert s.gmail_state()['sign_in']=='not_checked'
    s.google('/profile')
    assert s.gmail_state()['sign_in']=='connected'
    s.transport.fail=True
    with pytest.raises(ValueError):s.google('/profile')
    assert s.gmail_state()['sign_in']=='unavailable'
    assert 'PRIVATE_PROVIDER_ERROR' not in str(s.gmail_state())


def test_gmail_status_does_not_reuse_old_or_different_account_verification():
    s,c=source();s.google('/profile');s.gmail_health['at']-=601
    assert s.gmail_state()['sign_in']=='not_checked'
    s.google('/profile');c['revision']=2
    assert s.gmail_state()['sign_in']=='not_checked'
