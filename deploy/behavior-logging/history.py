"""Read stored scene and person histories as JSON without loading any models."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from interactions import read_state


def utc_bound(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def query_history(database, collection, person_id=None, scene_id=None, camera_id=None,
                  since=None, until=None, limit=20, offset=0):
    if limit < 1 or offset < 0:
        raise ValueError('limit must be positive and offset must be zero or greater')
    since, until = utc_bound(since), utc_bound(until)
    if since is not None and until is not None and since >= until:
        raise ValueError('since must be earlier than until')
    if collection == 'state':
        if not person_id or scene_id or since or until:
            raise ValueError('state requires person-id and supports only camera-id, limit and offset filters')
        connection = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            records = read_state(connection, person_id, [camera_id] if camera_id else None, limit + 1, offset)
        finally:
            connection.close()
        for record in records:
            record.pop('payload', None)
        return {'collection': collection, 'records': records[:limit], 'returned': min(limit, len(records)),
                'limit': limit, 'offset': offset, 'next_offset': offset + limit if len(records) > limit else None}
    if collection == 'scenes':
        select = 'SELECT s.payload FROM scene_descriptions s'
        identity_filter = '''EXISTS (SELECT 1 FROM scene_persons sp
            WHERE sp.scene_id=s.scene_id AND sp.person_id=?)'''
        order = 's.observed_at DESC, s.scene_id DESC'
    elif collection == 'behaviors':
        select = '''SELECT b.payload, s.description AS scene_description,
                    s.analysis_status AS scene_analysis_status
                    FROM person_behaviors b JOIN scene_descriptions s ON b.scene_id=s.scene_id'''
        identity_filter = 'b.person_id=?'
        order = 'b.observed_at DESC, b.behavior_id DESC'
    elif collection == 'persons':
        select = '''SELECT DISTINCT p.person_id, p.first_seen, p.last_seen FROM persons p
                    JOIN scene_persons sp ON p.person_id=sp.person_id
                    JOIN scene_descriptions s ON sp.scene_id=s.scene_id'''
        identity_filter = 'p.person_id=?'
        order = 'p.last_seen DESC, p.person_id DESC'
    else:
        raise ValueError('collection must be scenes, behaviors, or persons')
    conditions, parameters = [], []
    for column, value in (('s.scene_id', scene_id), ('s.camera_id', camera_id)):
        if value is not None:
            conditions.append(column + '=?')
            parameters.append(value)
    if person_id is not None:
        conditions.append(identity_filter)
        parameters.append(person_id)
    if since is not None:
        conditions.append('s.observed_at>=?')
        parameters.append(since)
    if until is not None:
        conditions.append('s.observed_at<?')
        parameters.append(until)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    database = Path(database).resolve()
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(select + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
                                  [*parameters, limit + 1, offset]).fetchall()
    finally:
        connection.close()
    records = []
    for row in rows[:limit]:
        if collection == 'persons':
            record = dict(row)
        else:
            record = json.loads(row['payload'])
            if collection == 'behaviors':
                record['scene_description'] = row['scene_description']
                record['scene_analysis_status'] = row['scene_analysis_status']
        records.append(record)
    return {'collection': collection, 'records': records, 'returned': len(records),
            'limit': limit, 'offset': offset, 'next_offset': offset + limit if len(rows) > limit else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('collection', choices=('scenes', 'behaviors', 'persons', 'state'))
    parser.add_argument('--db', type=Path,
                        default=Path(os.environ.get('BEHAVIOR_LOG_DIR', '/logs')) / 'person-activities.sqlite3')
    parser.add_argument('--person-id')
    parser.add_argument('--scene-id')
    parser.add_argument('--camera-id')
    parser.add_argument('--since', help='Inclusive ISO-8601 timestamp; timestamps without an offset use UTC')
    parser.add_argument('--until', help='Exclusive ISO-8601 timestamp')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    try:
        result = query_history(args.db, args.collection, args.person_id, args.scene_id,
                               args.camera_id, args.since, args.until, args.limit, args.offset)
    except (sqlite3.Error, ValueError, OSError) as error:
        parser.exit(2, f'History query failed: {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
