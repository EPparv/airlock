"""Print fixed stage names and independently compare the vendor's actual response."""
import hashlib
import hmac
import json
from pathlib import Path
import re
import sys

if sys.argv[1] == 'progress':
    path = Path(sys.argv[2])
    if not path.is_file():
        print('No final vendor report was received.')
    else:
        result = json.loads(path.read_text())
        stages = result['stages']
        assert all(re.fullmatch(r'[a-z_]{1,60}(?:[0-9]{3})?', stage) for stage in stages)
        print('Official client stages:', ', '.join(stages))
        if not result['ok']:
            error = result.get('error','')
            print('Official client result:', error if re.fullmatch(r'[A-Za-z_]{1,60}', error) else 'failed')
else:
    base = Path(sys.argv[2])
    receipt = json.loads((base/'receipt'/'receipt.json').read_text())
    assert json.loads((base/'summary.json').read_text())['ok']
    assert receipt['revoked'] and receipt['closed'] and receipt['authenticated_status_call']
    code = (base/'observed').read_text().strip()
    nonce = (base/'private'/'nonce').read_text().strip()
    assert re.fullmatch('[0-9a-f]{32}', nonce)
    assert re.fullmatch('[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}', code)
    assert hmac.compare_digest(hashlib.sha256((nonce+code).encode()).hexdigest(),receipt['returned_code_hash'])
    print('Official IronClaw returned the matching tool proof. Airlock revoked the grant and closed the public bridge.')
