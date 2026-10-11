"""Non-destructive demonstration storage and JSONL reset checkpoints."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid


class SessionConflict(ValueError):
    pass


def active_database(base):
    base = Path(base).resolve()
    pointer = base.with_suffix(base.suffix + '.active.json')
    if not pointer.exists():
        return base
    saved = json.loads(pointer.read_text(encoding='utf-8'))
    session_id = str(uuid.UUID(saved['session_id']))
    active = base.parent / (base.stem + '_sessions') / (session_id + '.sqlite3')
    if not active.is_file():
        raise RuntimeError('Active demonstration database is missing: ' + str(active))
    return active


def select_database(base, session_id):
    pointer = base.with_suffix(base.suffix + '.active.json')
    temporary = pointer.with_suffix(pointer.suffix + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as output:
            json.dump({'session_id': session_id}, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, pointer)
    finally:
        temporary.unlink(missing_ok=True)


def watch_key(watch):
    return 'watch_cursor:' + hashlib.sha256(str(watch).encode()).hexdigest()


def checkpoint_watch(old_db, connection, watch):
    """Ignore old IDs even if an append-only source later rewrites its file."""
    connection.execute('CREATE TABLE IF NOT EXISTS reset_ignored_posts(id TEXT PRIMARY KEY)')
    with closing(sqlite3.connect(old_db)) as old:
        connection.executemany('INSERT OR IGNORE INTO reset_ignored_posts VALUES(?)',
                               old.execute('SELECT id FROM posts').fetchall())
        if old.execute("SELECT 1 FROM sqlite_master WHERE name='reset_ignored_posts'").fetchone():
            connection.executemany('INSERT OR IGNORE INTO reset_ignored_posts VALUES(?)',
                                   old.execute('SELECT id FROM reset_ignored_posts').fetchall())
    if not watch:
        return
    content = watch.read_bytes()
    for line in content.splitlines():
        try:
            item = json.loads(line.decode('utf-8-sig'))
            if isinstance(item, dict) and isinstance(item.get('id'), str):
                connection.execute('INSERT OR IGNORE INTO reset_ignored_posts VALUES(?)', (item['id'],))
        except (ValueError, UnicodeError):
            pass
    cursor = {'offset': len(content), 'prefix_sha256': hashlib.sha256(content).hexdigest(),
              'skip_partial': bool(content and not content.endswith(b'\n'))}
    connection.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',
                       (watch_key(watch), json.dumps(cursor)))
