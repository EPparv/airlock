"""Read a bounded, owner-selected snapshot and keep only explicitly selected fields."""
import base64
import csv
from io import StringIO
import json
from itertools import islice
import re
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request
import sqlite3

from .core import Denied

MAX_ROWS = 100
MAX_BYTES = 1024 * 1024


def _sqlite_rows(content, table):
    with sqlite3.connect(':memory:') as db:
        db.deserialize(content)
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_BYTES)
        # PRAGMA table_list distinguishes ordinary tables from views and virtual tables.
        tables = sorted(row[1] for row in db.execute('PRAGMA table_list')
                        if row[0] == 'main' and row[2] == 'table' and not row[1].startswith('sqlite_'))
        if not table:
            return tables, []
        if table not in tables:
            raise Denied('Choose one of the listed tables.')
        name = '"' + table.replace('"', '""') + '"'
        db.row_factory = sqlite3.Row
        cursor = db.execute(f'SELECT * FROM {name} LIMIT ?', (MAX_ROWS + 1,))
        return tables, [dict(row) for row in cursor]


def inspect_file(name, encoded, table=''):
    if not isinstance(name, str) or not isinstance(encoded, str) or len(encoded) > 1400000 or not isinstance(table, str):
        raise Denied('Choose a JSON, CSV or SQLite file up to 1 MB.')
    try:
        content = base64.b64decode(encoded, validate=True)
        if len(content) > MAX_BYTES:
            raise Denied('Choose a file up to 1 MB.')
        tables = []
        if content.startswith(b'SQLite format 3\x00'):
            tables, rows = _sqlite_rows(content, table)
        elif name.lower().endswith('.csv'):
            rows = list(islice(csv.DictReader(StringIO(content.decode('utf-8-sig'))), MAX_ROWS + 1))
        else:
            rows = json.loads(content.decode('utf-8-sig'))
            if isinstance(rows, dict):
                rows = [rows]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError()
        fields = field_names(rows[:MAX_ROWS])
        return tables, fields, rows[:MAX_ROWS], len(rows) > MAX_ROWS
    except Denied:
        raise
    except (ValueError, OverflowError, TypeError, csv.Error, sqlite3.Error, UnicodeError, RecursionError):
        raise Denied('Use an array of JSON objects, a CSV with headers, or an ordinary SQLite table.') from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def api_settings(url, credential, array_key):
    if not all(isinstance(v, str) for v in (url, credential, array_key)):
        raise Denied('Check the API settings.')
    if len(url) > 2048 or len(credential) > 4096 or len(array_key) > 80 or any(ord(c) < 32 for c in url + credential + array_key):
        raise Denied('Check the API settings.')
    try:
        parts = urlsplit(url)
        if (not parts.hostname or parts.username is not None or parts.password is not None or parts.fragment or
                not (parts.scheme == 'https' or parts.scheme == 'http' and parts.hostname in ('127.0.0.1', '::1', 'localhost'))):
            raise ValueError()
        _ = parts.port
    except ValueError:
        raise Denied('Use an HTTPS endpoint or an HTTP endpoint on localhost.') from None
    return dict(url=url, credential=credential, array_key=array_key)


def fetch_api(settings):
    request = Request(settings['url'], headers={'Accept':'application/json'}, method='GET')
    if settings['credential']:
        request.add_header('Authorization', 'Bearer ' + settings['credential'])
    # Only this exact destination receives the owner's stored credential.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=8) as reply:
            body = reply.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise Denied('The API response exceeds 1 MB.')
        rows = json.loads(body.decode('utf-8-sig'))
        if settings['array_key']:
            rows = rows[settings['array_key']]
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows[:MAX_ROWS + 1]):
            raise ValueError()
        return rows[:MAX_ROWS], len(rows) > MAX_ROWS
    except (URLError, OSError, ValueError, KeyError, TypeError, RecursionError, UnicodeError):
        raise Denied('The endpoint must return JSON objects. Check the address, token and array field.') from None


def select_fields(fields, selected):
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 20 or
            any(not isinstance(k, str) or k not in fields for k in selected)):
        raise Denied('Choose one to twenty visible fields.')
    return list(dict.fromkeys(selected))


def field_names(rows):
    return sorted({k for row in rows for k, v in row.items()
                   if isinstance(k, str) and 0 < len(k) <= 80 and isinstance(v, (str, int, float, bool))})


def project(rows, fields):
    projected = [{k:str(row[k]) for k in fields if isinstance(row.get(k), (str, int, float, bool))} for row in rows]
    if any(len(v) > 12000 for row in projected for v in row.values()) or sum(len(v) for row in projected for v in row.values()) > 64000:
        raise Denied('Select fewer or shorter fields. A view supports up to 64,000 characters.')
    return projected


def screened_view(engine, fields, rows, truncated):
    from .automatic import clean, sanitize
    from .core import EMAIL, PHONE
    from .privacy_engine import sensitive
    hidden = re.compile(r'\b(?:password|passphrase|secret|token|key|ssn|social security|passport|diagnosis|diagnoses|medical|address|salary|income|balance|birth|dob|iban|routing|account number|credit card|card number)\b', re.I)
    person = re.compile(r'\b(?:name|recipient|sender|contact|attendee)\b', re.I)
    protected = engine.g.sources.protected()
    def category(field):
        # Match both database conventions such as api_key and camelCase vendor schemas.
        return re.sub(r'([a-z])([A-Z])', r'\1 \2', field).replace('_', ' ').replace('-', ' ').casefold()
    def token(kind):
        return lambda m: engine.pseudonym(kind, m.group())
    def safe_text(value):
        value = PHONE.sub(token('phone'), EMAIL.sub(token('email'), clean(value)))
        return sanitize(value, protected) or '[withheld]'
    def cell(field, value):
        key = category(field)
        if hidden.search(key) or sensitive(value):
            return '[withheld]'
        if EMAIL.fullmatch(value):
            return engine.pseudonym('email', value)
        if person.search(key):
            return engine.pseudonym('person', value)
        if key in ('id','user id','account id','customer id','member id'):
            return engine.pseudonym('id', value)
        if re.search(r'\b(?:phone|mobile|telephone)\b', key):
            return engine.pseudonym('phone', value)
        return safe_text(value)
    # Recognize the same named person in another approved free-text column.
    identities = {clean(row[field]).casefold():engine.pseudonym('person', row[field])
                  for row in rows for field in fields if field in row and person.search(category(field))
                  and 2 <= len(row[field]) <= 120 and not EMAIL.search(row[field]) and not hidden.search(category(field))}
    filtered = [[cell(field, row[field]) if field in row else None for field in fields] for row in rows]
    visible_fields = [safe_text(f) for f in fields]
    engine.learn(visible_fields + [value for row in filtered for value in row if value])
    aliases = engine.alias_filter()
    matching = re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(k) for k in sorted(identities,key=len,reverse=True))+r')(?!\w)',re.I) if identities else None
    def finish(value):
        if value is None:
            return None
        if matching:
            value = matching.sub(lambda m: identities.get(m.group().casefold(),'[identity withheld]'),value)
        return aliases(value)[:400]
    return dict(fields=[finish(f) for f in visible_fields], rows=[[finish(v) for v in row] for row in filtered],
                limited_to_100_rows=truncated)
