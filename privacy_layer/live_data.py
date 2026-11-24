"""Owner-selected device files. Open by identity and isolate live SQLite reads from writers."""
from contextlib import ExitStack, closing, contextmanager
import csv
from io import StringIO
from itertools import islice
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import sys

from .core import Denied
from .data_view import MAX_BYTES, MAX_ROWS, field_names, project, select_fields

MAX_DATABASE = 32 * 1024 * 1024
CHANGED = 'The selected file changed identity or is unavailable. Select it again.'
BUSY = 'The database is changing. Try again after the current write finishes.'


def picker_available():
    return sys.platform == 'darwin' and os.path.isfile('/usr/bin/osascript')


def choose_file():
    if not picker_available():
        raise Denied('Enter the full local path to the file.')
    try:
        result = subprocess.run(['/usr/bin/osascript', '-e', 'POSIX path of (choose file with prompt "Choose a file for Airlock")'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120, check=False)
        if result.returncode:
            raise Denied('File selection closed. Choose again or enter the full path.')
        return os.fsdecode(result.stdout.removesuffix(b'\n'))
    except (OSError, subprocess.TimeoutExpired):
        raise Denied('The file picker is unavailable. Enter the full path.') from None


@contextmanager
def _source(path, *, append=False):
    if not isinstance(path, str) or not path.startswith('/') or len(path) > 4096 or any(ord(c) < 32 for c in path):
        raise Denied('Enter the full local path to the file.')
    parts = path[1:].split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise Denied('Use a full path without shortcuts or symbolic links.')
    with ExitStack() as stack:
        def keep(fd):
            stack.callback(os.close, fd)
            return fd
        directory_flags = os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW
        folder = keep(os.open('/', directory_flags))
        for part in parts[:-1]:
            folder = keep(os.open(part, directory_flags, dir_fd=folder))
        name = parts[-1]
        if not stat.S_ISREG(os.stat(name, dir_fd=folder, follow_symlinks=False).st_mode):
            raise Denied('Choose a regular file on this device.')
        flags = os.O_WRONLY | os.O_APPEND if append else os.O_RDONLY
        fd = keep(os.open(name, flags | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=folder))
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Denied('Choose a regular file on this device.')
        yield folder, name, fd


def _stamp(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _identity(fd):
    # Inode numbers can be reused after deletion. Birth time binds the pin to this incarnation.
    # Strings preserve filesystem precision through the owner's JSON round trip.
    info = os.fstat(fd)
    birth = getattr(info, 'st_birthtime_ns', None)
    if birth is None and hasattr(info, 'st_birthtime'):
        birth = info.st_birthtime
    if birth is None and sys.platform.startswith('linux'):
        import ctypes
        import struct
        statx = getattr(ctypes.CDLL(None), 'statx', None)
        buf = ctypes.create_string_buffer(256)
        # Linux statx(fd, "", AT_EMPTY_PATH, STATX_BTIME, ...); timestamps use a fixed ABI.
        if statx and statx(fd, b'', 0x1000, 0x800, ctypes.byref(buf)) == 0 and struct.unpack_from('=I', buf)[0] & 0x800:
            seconds, ns = struct.unpack_from('=qI', buf, 80)
            birth = seconds * 10**9 + ns
    if birth is None:
        raise Denied('This filesystem cannot pin a live file by creation time. Use a snapshot.')
    return [str(info.st_dev), str(info.st_ino), str(birth)]


def _read(fd, limit):
    size = os.fstat(fd).st_size
    if size > limit:
        raise Denied('Live CSV and JSON files support 1 MB. SQLite databases and their WAL support 32 MB combined.')
    with os.fdopen(os.dup(fd), 'rb') as inp:
        data = inp.read(limit + 1)
    if len(data) != size:
        raise Denied(BUSY)
    return data


def _sidecar(folder, name):
    try:
        info = os.stat(name, dir_fd=folder, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise Denied('The database uses an unsupported journal file.')
    return _stamp(info)


def _tables_and_rows(db, table, selected):
    db.execute('PRAGMA trusted_schema=OFF')
    db.execute('PRAGMA query_only=ON')
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_BYTES)
    tables = sorted(row[1] for row in db.execute('PRAGMA main.table_list')
                    if row[0] == 'main' and row[2] == 'table' and not row[1].startswith('sqlite_'))
    if not table:
        return tables, [], [], False
    if table not in tables:
        raise Denied('Choose an ordinary table from this file.')
    columns = [row[1] for row in db.execute('SELECT * FROM pragma_table_xinfo(?, ?)', (table, 'main'))
               if row[6] == 0 and 0 < len(row[1]) <= 80]
    if not selected:
        return tables, columns, [], False
    fields = select_fields(columns, selected)
    def quote(name):
        return '"' + name.replace('"', '""') + '"'
    query = 'SELECT ' + ', '.join('t.' + quote(c) for c in fields) + ' FROM main.' + quote(table) + ' AS t LIMIT ?'
    rows = []
    total = 0
    for values in db.execute(query, (MAX_ROWS + 1,)):
        if len(rows) == MAX_ROWS:
            return tables, columns, rows, True
        row = project([dict(zip(fields, values))], fields)[0]
        total += sum(len(value) for value in row.values())
        if total > 64000:
            raise Denied('Select fewer or shorter fields. A view supports up to 64,000 characters.')
        rows.append(row)
    return tables, columns, rows, False


def _database(folder, name, fd, table, selected):
    journal = name + '-journal'
    wal_name = name + '-wal'
    # A hot or changing rollback journal needs the database writer to settle first.
    before = os.fstat(fd)
    rollback = _sidecar(folder, journal)
    if rollback and rollback[2]:
        journal_fd = os.open(journal, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
        try:
            # PERSIST leaves the journal file in place and zeros its header after commit.
            if _stamp(os.fstat(journal_fd)) != rollback or any(os.read(journal_fd, 28)):
                raise Denied(BUSY)
        finally:
            os.close(journal_fd)
    wal = _sidecar(folder, wal_name)
    main = _read(fd, MAX_DATABASE)
    log = b''
    if wal:
        wal_fd = os.open(wal_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
        try:
            if _stamp(os.fstat(wal_fd)) != wal:
                raise Denied(BUSY)
            log = _read(wal_fd, MAX_DATABASE - len(main))
        finally:
            os.close(wal_fd)
    if (_stamp(os.fstat(fd)) != _stamp(before) or wal != _sidecar(folder, wal_name)
            or rollback != _sidecar(folder, journal)):
        raise Denied(BUSY)
    # SQLite replays committed WAL frames on a private copy. It never opens or writes the source files.
    with tempfile.TemporaryDirectory(prefix='airlock-view-') as tmp:
        local = Path(tmp) / 'view.sqlite'
        local.write_bytes(main)
        if log:
            local.with_name('view.sqlite-wal').write_bytes(log)
        with closing(sqlite3.connect(local.as_uri() + '?mode=ro', uri=True)) as db:
            return _tables_and_rows(db, table, selected)


def inspect_live(path, table='', identity=None, fields=None):
    if not isinstance(table, str) or len(table) > 255:
        raise Denied('Choose a table from this file.')
    try:
        with _source(path) as (folder, name, fd):
            start = os.fstat(fd)
            pinned = _identity(fd)
            if identity is not None and identity != pinned:
                raise Denied(CHANGED)
            if os.pread(fd, 16, 0) == b'SQLite format 3\x00':
                tables, columns, rows, truncated = _database(folder, name, fd, table, fields)
            else:
                if table:
                    raise Denied('This file has no selected table.')
                text = _read(fd, MAX_BYTES).decode('utf-8-sig')
                if name.lower().endswith('.csv'):
                    rows = list(islice(csv.DictReader(StringIO(text)), MAX_ROWS + 1))
                elif name.lower().endswith('.json'):
                    rows = json.loads(text)
                    if isinstance(rows, dict):
                        rows = [rows]
                else:
                    raise Denied('Choose a CSV, JSON or SQLite file.')
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows[:MAX_ROWS + 1]):
                    raise ValueError()
                truncated = len(rows) > MAX_ROWS
                rows = rows[:MAX_ROWS]
                columns, tables = field_names(rows), []
                rows = project(rows, select_fields(columns, fields)) if fields else []
            # Verify the current path still resolves to the file we inspected, including its ancestors.
            with _source(path) as (_, _, current):
                if _identity(current) != pinned:
                    raise Denied(CHANGED)
            if _stamp(os.fstat(fd)) != _stamp(start):
                raise Denied(BUSY)
            return dict(identity=pinned, tables=tables, fields=columns, rows=rows, truncated=truncated)
    except Denied:
        raise
    except OSError:
        raise Denied(CHANGED) from None
    except (sqlite3.Error, csv.Error, ValueError, UnicodeError, RecursionError):
        raise Denied('The selected file could not be read. Check the file format and selected table.') from None


def live_payload(values):
    if not isinstance(values, dict) or set(values) != {'path', 'table', 'identity', 'fields'} or not values['identity']:
        raise Denied('Load a file and choose its fields.')
    result = inspect_live(values['path'], values['table'], values['identity'], values['fields'])
    return dict(path=values['path'], table=values['table'], identity=result['identity'],
                fields=select_fields(result['fields'], values['fields']))


def append_payload(values):
    if not isinstance(values, dict) or set(values) != {'path', 'text'} or not isinstance(values['path'], str):
        raise Denied('Choose an existing text file and the text to append.')
    path, text = values['path'], values['text']
    if (Path(path).suffix.lower() not in ('.md', '.txt', '.log') or not isinstance(text, str)
            or not text or '\x00' in text or len(text.encode('utf-8', errors='replace')) > 32768):
        raise Denied('Choose an existing .md, .txt, or .log file and up to 32 KB of text.')
    try:
        text.encode('utf-8')
        with _source(path) as (_, _, fd):
            if os.fstat(fd).st_nlink != 1:
                raise Denied('Choose a file without hard links.')
            existing = _read(fd, MAX_BYTES).decode('utf-8-sig')
            if '\x00' in existing:
                raise Denied('Choose a plain UTF-8 text file.')
            return {'path': path, 'text': text, 'identity': _identity(fd)}
    except UnicodeError:
        raise Denied('Choose a plain UTF-8 text file.') from None
    except OSError:
        raise Denied(CHANGED) from None


def append_file(payload):
    body = payload['text'].encode('utf-8')
    with _source(payload['path'], append=True) as (folder, name, fd):
        info = os.fstat(fd)
        if (_identity(fd) != payload['identity'] or info.st_nlink != 1 or info.st_size + len(body) > MAX_BYTES
                or not os.path.samestat(info, os.stat(name, dir_fd=folder, follow_symlinks=False))):
            raise Denied(CHANGED)
        # One append syscall, never retried even for a short write.
        if os.write(fd, body) != len(body):
            return False
        os.fsync(fd)
        return True
