"""Browser fixture: disposable profile, fixed test key, no personal source access."""
import sys
from pathlib import Path
import uvicorn
from privacy_layer import clients, sources
from privacy_layer.safe_test import SafeTest

root=Path(__file__).resolve().parents[1]
state=Path(sys.argv[1]);profile=state/'profile';profile.mkdir(parents=True)
clients.ROOT=state/'app'
original=sources.LocalSources
sources.LocalSources=lambda **kw:original(key=b'b'*32,context_home=profile)
c=SafeTest(root,state/'state',profile_home=profile)
uvicorn.run(c.app('fictional-browser-owner',int(sys.argv[2])),host='127.0.0.1',port=int(sys.argv[2]),log_level='error')
