"""Explicit property choices, preference snapshots and auditable journey events."""
from datetime import datetime
import json
from uuid import uuid4
from agent_runtime import INDIA_TZ
from followup_service import _connect, FOLLOWUP_DB


def schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS customer_property_choices (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,conversation_id TEXT NOT NULL,
        property_key TEXT NOT NULL,property_title TEXT NOT NULL,source_url TEXT NOT NULL,
        preferences TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL,
        UNIQUE(user_id,conversation_id,property_key))""")
    c.execute("""CREATE TABLE IF NOT EXISTS customer_journey_events (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,conversation_id TEXT NOT NULL,
        property_key TEXT NOT NULL,visit_id TEXT NOT NULL,event TEXT NOT NULL,
        detail TEXT NOT NULL,at TEXT NOT NULL)""")
    if getattr(c,'shared',False):
        for table in ('customer_property_choices','customer_journey_events'):
            c.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')


def event(c, *, user_id, conversation_id='', property_key='', visit_id='', event, detail=''):
    schema(c)
    c.execute('INSERT INTO customer_journey_events VALUES(?,?,?,?,?,?,?,?)',
        (uuid4().hex,user_id,conversation_id,property_key,visit_id,event,detail[:2000],datetime.now(INDIA_TZ).isoformat(timespec='seconds')))


def preferences_json(preferences):
    # Only structured search fields; never persist arbitrary chat memory or contact credentials.
    allowed={'locations','location','property_types','property_type','listing_types','listing_type',
             'max_budget','min_budget','bhk','bedrooms','min_area','max_area','area','features',
             'include_auctions','include_ended_auctions','listing_kinds','budget_lakh','size_sqm',
             'min_area_sqm','status','listing_statuses','lift','parking','amenities','_property_type_cleared'}
    encoded=json.dumps({k:v for k,v in (preferences or {}).items() if k in allowed},ensure_ascii=False,default=str)
    if len(encoded)>8000: raise ValueError('Search preferences are too long. Please shorten them.')
    return encoded


def select_property(*, user_id,conversation_id,record,preferences,selected=True,db_path=FOLLOWUP_DB):
    from visit_service import property_key
    key=property_key(record);status='Selected' if selected else 'Removed'
    now=datetime.now(INDIA_TZ).isoformat(timespec='seconds')
    with _connect(db_path) as c:
        schema(c)
        previous=c.execute('SELECT status FROM customer_property_choices WHERE user_id=? AND conversation_id=? AND property_key=?',(user_id,conversation_id,key)).fetchone()
        c.execute("""INSERT INTO customer_property_choices VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id,conversation_id,property_key) DO UPDATE SET
            preferences=excluded.preferences,status=excluded.status,updated_at=excluded.updated_at""",
            (uuid4().hex,user_id,conversation_id,key,str(record.get('title') or 'Saved property')[:200],str(record.get('source_url') or '')[:1000],preferences_json(preferences),status,now))
        if not previous or previous['status']!=status:
            event(c,user_id=user_id,conversation_id=conversation_id,property_key=key,event='Property '+status.lower(),detail=str(record.get('title') or '')[:200])


def choices(user_id=None,db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        rows=c.execute('SELECT * FROM customer_property_choices'+(' WHERE user_id=?' if user_id is not None else '')+' ORDER BY updated_at DESC',(user_id,) if user_id is not None else ()).fetchall()
    return [dict(r) for r in rows]


def remove_choice(choice_id,user_id,db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        row=c.execute("SELECT * FROM customer_property_choices WHERE id=? AND user_id=? AND status='Selected'",(choice_id,user_id)).fetchone()
        if not row:return False
        c.execute("UPDATE customer_property_choices SET status='Removed',updated_at=? WHERE id=?",(datetime.now(INDIA_TZ).isoformat(),choice_id))
        event(c,user_id=user_id,conversation_id=row['conversation_id'],property_key=row['property_key'],event='Property removed',detail=row['property_title'])
    return True


def timeline(db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        rows=c.execute('SELECT * FROM customer_journey_events ORDER BY at DESC').fetchall()
    return [dict(r) for r in rows]
