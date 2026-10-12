"""Private CRM workflow linked to conversations; never enrolls messaging."""
from datetime import datetime
from uuid import uuid4
from agent_runtime import INDIA_TZ
from followup_service import FOLLOWUP_DB, _connect
from storage_backend import _redact
import re
from decimal import Decimal, InvalidOperation

STAGES = ('New', 'Contacted', 'Qualified', 'Visit planned', 'Negotiating', 'Closed won', 'Closed lost')
PRIORITIES = ('Normal', 'High', 'Low')
DEAL_STAGES = ('Discovery', 'Viewing', 'Offer', 'Negotiation', 'Won', 'Lost')
TASK_STATUSES = ('Open', 'In progress', 'Completed', 'Cancelled')


def schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS crm_leads (
        id TEXT PRIMARY KEY, conversation_id TEXT UNIQUE, customer_name TEXT NOT NULL,
        location TEXT NOT NULL DEFAULT '', property_type TEXT NOT NULL DEFAULT '',
        budget TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT 'New',
        priority TEXT NOT NULL DEFAULT 'Normal', assigned_to TEXT NOT NULL DEFAULT '',
        next_action TEXT NOT NULL DEFAULT '', due_at TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS crm_activity (
        id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, actor TEXT NOT NULL,
        kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)""")
    for column in ('email','phone','source'):
        if getattr(c,'shared',False):
            c.execute(f"ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS {column} TEXT NOT NULL DEFAULT ''")
        elif column not in {r[1] for r in c.execute('PRAGMA table_info(crm_leads)')}:
            c.execute(f"ALTER TABLE crm_leads ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    c.execute("""CREATE TABLE IF NOT EXISTS crm_deals (
        id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, title TEXT NOT NULL,
        property_reference TEXT NOT NULL DEFAULT '', value_inr TEXT NOT NULL DEFAULT '0',
        stage TEXT NOT NULL DEFAULT 'Discovery', assigned_to TEXT NOT NULL DEFAULT '',
        expected_close TEXT NOT NULL DEFAULT '', loss_reason TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS crm_tasks (
        id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, title TEXT NOT NULL,
        assigned_to TEXT NOT NULL DEFAULT '', due_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Open', priority TEXT NOT NULL DEFAULT 'Normal',
        updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0)""")
    if getattr(c,'shared',False):
        for table in ('crm_leads','crm_activity','crm_deals','crm_tasks'):
            c.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')


def _stamp():
    return datetime.now(INDIA_TZ).isoformat(timespec='seconds')


def _audit(c, lead_id, actor, kind, detail):
    c.execute('INSERT INTO crm_activity VALUES(?,?,?,?,?,?)',
              (uuid4().hex,lead_id,_redact(actor)[:200],kind,_redact(detail)[:4000],_stamp()))


def _require_lead(c, lead_id):
    if not c.execute('SELECT id FROM crm_leads WHERE id=?',(lead_id,)).fetchone():
        raise ValueError('Lead not found.')


def _profile(name,email,phone):
    if not name.strip():
        raise ValueError('Enter a customer name.')
    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email.strip()):
        raise ValueError('Enter a valid email address.')
    if phone:
        from whatsapp_followup import normalize_phone
        phone=normalize_phone(phone)
    return _redact(name.strip())[:200],email.strip()[:254],phone


def create_lead(name, *, email='', phone='', location='', property_type='', budget='', source='Manual', actor='Owner', db_path=FOLLOWUP_DB):
    name,email,phone=_profile(name,email,phone)
    key=uuid4().hex
    with _connect(db_path) as c:
        schema(c)
        c.execute("""INSERT INTO crm_leads(id,conversation_id,customer_name,email,phone,location,property_type,budget,source,created_at,updated_at)
            VALUES(?,NULL,?,?,?,?,?,?,?,?,?)""",(key,name,email,phone,_redact(location)[:500],_redact(property_type)[:200],_redact(budget)[:500],_redact(source)[:200],_stamp(),_stamp()))
        _audit(c,key,actor,'Lead created',source)
    return key


def save_profile(lead_id, *, version, name, email='', phone='', location='', property_type='', budget='', source='', actor='Owner',db_path=FOLLOWUP_DB):
    name,email,phone=_profile(name,email,phone)
    with _connect(db_path) as c:
        schema(c)
        if c.execute("""UPDATE crm_leads SET customer_name=?,email=?,phone=?,location=?,property_type=?,budget=?,source=?,updated_at=?,version=version+1
            WHERE id=? AND version=?""",(name,email,phone,_redact(location)[:500],_redact(property_type)[:200],_redact(budget)[:500],_redact(source)[:200],_stamp(),lead_id,version)).rowcount!=1:
            raise ValueError('This lead changed. Reload before saving.')
        _audit(c,lead_id,actor,'Profile updated','Customer contact and property preferences updated')


def list_records(kind, db_path=FOLLOWUP_DB):
    if kind not in ('deals','tasks'):
        raise ValueError('Unknown CRM record type.')
    with _connect(db_path) as c:
        schema(c)
        return [dict(r) for r in c.execute(f'SELECT * FROM crm_{kind} ORDER BY updated_at DESC').fetchall()]


def save_task(lead_id, title, due_at, *, assigned_to='', priority='Normal', status='Open', record_id=None, version=0, actor='Owner',db_path=FOLLOWUP_DB):
    if not title.strip() or status not in TASK_STATUSES or priority not in PRIORITIES:
        raise ValueError('Enter a title and valid task status/priority.')
    when=datetime.fromisoformat(due_at)
    if when.tzinfo is None:
        raise ValueError('Task due time needs a timezone.')
    due_at=when.astimezone(INDIA_TZ).isoformat(timespec='minutes')
    with _connect(db_path) as c:
        schema(c); _require_lead(c,lead_id)
        values=(_redact(title.strip())[:500],_redact(assigned_to)[:200],due_at,status,priority,_stamp())
        if record_id:
            if c.execute('UPDATE crm_tasks SET title=?,assigned_to=?,due_at=?,status=?,priority=?,updated_at=?,version=version+1 WHERE id=? AND lead_id=? AND version=?',(*values,record_id,lead_id,version)).rowcount!=1:
                raise ValueError('This task changed. Reload before saving.')
        else:
            record_id=uuid4().hex
            c.execute('INSERT INTO crm_tasks(id,lead_id,title,assigned_to,due_at,status,priority,updated_at) VALUES(?,?,?,?,?,?,?,?)',(record_id,lead_id,*values))
        _audit(c,lead_id,actor,'Task saved',f'{title}; {status}; due {due_at}; {assigned_to}')
    return record_id


def save_deal(lead_id,title, *, property_reference='', value_inr='0', stage='Discovery', assigned_to='', expected_close='',loss_reason='',record_id=None,version=0,actor='Owner',db_path=FOLLOWUP_DB):
    from datetime import date
    try:
        value=Decimal(str(value_inr))
    except InvalidOperation:
        raise ValueError('Enter a valid deal value in INR.') from None
    if not value.is_finite() or value<0 or value>Decimal('100000000000000') or value.as_tuple().exponent < -2:
        raise ValueError('Enter a nonnegative INR value with at most two decimal places.')
    if not title.strip() or stage not in DEAL_STAGES or (stage=='Lost' and not loss_reason.strip()):
        raise ValueError('Enter a deal title, valid stage and reason for lost deals.')
    if expected_close:
        date.fromisoformat(expected_close)
    with _connect(db_path) as c:
        schema(c); _require_lead(c,lead_id)
        values=(_redact(title)[:500],_redact(property_reference)[:1000],str(value),stage,_redact(assigned_to)[:200],expected_close,_redact(loss_reason)[:1000] if stage=='Lost' else '',_stamp())
        if record_id:
            if c.execute('UPDATE crm_deals SET title=?,property_reference=?,value_inr=?,stage=?,assigned_to=?,expected_close=?,loss_reason=?,updated_at=?,version=version+1 WHERE id=? AND lead_id=? AND version=?',(*values,record_id,lead_id,version)).rowcount!=1:
                raise ValueError('This deal changed. Reload before saving.')
        else:
            record_id=uuid4().hex
            c.execute('INSERT INTO crm_deals(id,lead_id,title,property_reference,value_inr,stage,assigned_to,expected_close,loss_reason,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(record_id,lead_id,*values))
        _audit(c,lead_id,actor,'Deal saved',f'{title}; {stage}; INR {value}')
    return record_id


def report(leads,deals,tasks,now=None):
    now=now or datetime.now(INDIA_TZ)
    closed=[r for r in deals if r['stage'] in ('Won','Lost')]
    won=[r for r in deals if r['stage']=='Won']
    return dict(leads=len(leads),open_deals=sum(r['stage'] not in ('Won','Lost') for r in deals),
                pipeline_inr=sum((Decimal(r['value_inr']) for r in deals if r['stage'] not in ('Won','Lost')),Decimal(0)),
                won_inr=sum((Decimal(r['value_inr']) for r in won),Decimal(0)),
                win_rate=100*len(won)/len(closed) if closed else None,
                overdue_tasks=sum(r['status'] not in ('Completed','Cancelled') and datetime.fromisoformat(r['due_at'])<=now for r in tasks))


def sync_inquiries(rows, db_path=FOLLOWUP_DB):
    from inquiry_log import customer_summary_rows
    count = 0
    stamp = datetime.now(INDIA_TZ).isoformat(timespec='seconds')
    with _connect(db_path) as c:
        schema(c)
        for row in customer_summary_rows(rows):
            conversation = str(row.get('Conversation ID') or '').strip()
            if not conversation:
                continue
            values = [_redact(str(row.get(k) or ''))[:500] for k in ('Customer name','Location','Property type','Budget')]
            result = c.execute("""INSERT INTO crm_leads
                (id,conversation_id,customer_name,location,property_type,budget,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(conversation_id) DO NOTHING""",
                (uuid4().hex,conversation,values[0] or 'Unnamed customer',*values[1:],stamp,stamp))
            count += result.rowcount
    return count


def list_leads(db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        return [dict(r) for r in c.execute('SELECT * FROM crm_leads ORDER BY updated_at DESC').fetchall()]


def save_lead(lead_id, *, version, stage, priority, assigned_to='', next_action='', due_at='', actor='Owner', db_path=FOLLOWUP_DB):
    if stage not in STAGES or priority not in PRIORITIES:
        raise ValueError('Choose a valid stage and priority.')
    if due_at:
        when = datetime.fromisoformat(due_at)
        if when.tzinfo is None:
            raise ValueError('Next-action time must include its timezone.')
        due_at = when.astimezone(INDIA_TZ).isoformat(timespec='minutes')
        if not next_action.strip():
            raise ValueError('Describe the next action when setting a due time.')
    stamp = datetime.now(INDIA_TZ).isoformat(timespec='seconds')
    fields = [_redact(str(v).strip())[:1000] for v in (assigned_to,next_action)]
    with _connect(db_path) as c:
        schema(c)
        if c.execute("""UPDATE crm_leads SET stage=?,priority=?,assigned_to=?,next_action=?,due_at=?,
            updated_at=?,version=version+1 WHERE id=? AND version=?""",
            (stage,priority,*fields,due_at,stamp,lead_id,version)).rowcount != 1:
            raise ValueError('This lead changed in another session. Reload the CRM before saving.')
        c.execute('INSERT INTO crm_activity VALUES(?,?,?,?,?,?)',
                  (uuid4().hex,lead_id,actor[:200],'Lead updated',_redact(f'{stage}; {priority}; Assigned: {fields[0]}; Next: {fields[1]}; Due: {due_at}'),stamp))


def add_note(lead_id, note, actor='Owner', db_path=FOLLOWUP_DB):
    if not note.strip():
        raise ValueError('Enter a note.')
    with _connect(db_path) as c:
        schema(c)
        if not c.execute('SELECT id FROM crm_leads WHERE id=?',(lead_id,)).fetchone():
            raise ValueError('Lead not found.')
        c.execute('INSERT INTO crm_activity VALUES(?,?,?,?,?,?)',
                  (uuid4().hex,lead_id,actor[:200],'Note',_redact(note.strip())[:4000],datetime.now(INDIA_TZ).isoformat(timespec='seconds')))


def activities(lead_id, db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        return [dict(r) for r in c.execute('SELECT actor,kind,detail,created_at FROM crm_activity WHERE lead_id=? ORDER BY created_at DESC',(lead_id,)).fetchall()]


def journey_summary(visit, *, now=None):
    """Customer evidence only: agreement to attend is not actual attendance."""
    from datetime import timedelta
    now=now or datetime.now(INDIA_TZ)
    at=datetime.fromisoformat(visit['visit_at'])
    status=visit['status']
    attended=visit.get('attended','')
    attendance='Visited' if attended=='Yes' else 'Did not visit' if attended=='No' else 'Awaiting response' if now>=at and status=='Confirmed' else 'Not yet due'
    from visit_attendance import attendance_state
    dual=attendance_state(visit)
    readiness='Insufficient evidence'
    evidence=[]
    if visit.get('purchase_outcome')=='Purchased':
        readiness='Purchase recorded by owner'; evidence.append(visit.get('outcome_note') or 'Owner verified outcome')
    elif visit.get('customer_purchase_confirmed_at'):
        readiness='Purchase reported — verification pending'
    elif visit.get('purchase_intent')=='Not interested':
        readiness='Declined this property'; evidence.append(visit.get('reason') or 'Customer declined')
    elif visit.get('purchase_intent')=='Interested':
        readiness='High interest' if attended=='Yes' and visit.get('satisfied')=='Yes' else 'Interest expressed'
        evidence.append('Customer stated purchase interest')
    elif attended=='Yes':
        readiness='Visited — purchase intent undecided'
    if attended=='Yes': evidence.append('Customer reports visit completed')
    if visit.get('satisfied')=='Yes': evidence.append('Property met preferences')
    if visit.get('advisor_consent')=='Yes': evidence.append('Assistance requested with consent')
    next_step = ('Review requested new slot' if status=='Requested' else
                 'Visit cancelled / declined' if status in ('Cancelled','Declined') else
                 'Request attendance and property feedback' if attendance=='Awaiting response' else
                 'Assist with revised preferences' if visit.get('explore_consent')=='Yes' else
                 'Follow up on requested assistance' if visit.get('advisor_consent')=='Yes' else
                 'Ask whether further assistance is needed' if visit.get('purchase_intent')=='Interested' else
                 'Review decline reason and offer assistance or more properties' if visit.get('purchase_intent')=='Not interested' else
                 'Check attendance after the visit' if attendance=='Not yet due' else 'Review customer feedback')
    if visit.get('explore_consent')=='Yes' and readiness=='Insufficient evidence': readiness='Exploring alternatives'
    if visit.get('followup_paused')=='Yes': readiness='Paused'; next_step='Customer paused visit emails'
    elif dual=='Attendance conflict': next_step='Review conflicting customer and advisor attendance before follow-up'
    elif now>=at and dual in ('Awaiting customer','Awaiting advisor','Awaiting both'): next_step='Collect missing attendance confirmation'
    return {'Visit ID':visit['visit_id'],'Property':visit['property_title'],'Visit time':visit['visit_at'],
            'Booking status':status,'Attendance':attendance,'Verified attendance':dual,
            'Assistance details':visit.get('assistance_details',''),'Callback preference':visit.get('callback_preference',''),'Assistance acknowledgment':visit.get('assistance email','Not sent'),'Customer clarification':visit.get('clarification_note',''),'Customer arrival':visit.get('arrival_time',''),'Customer met':visit.get('met_person',''),'Clarified at':visit.get('clarified_at',''),'Clarification email':visit.get('clarification email','Not sent'),'Customer attendance':attended or 'Pending','Advisor attendance':visit.get('agent_attended') or 'Pending','Property advisor':visit.get('agent_name',''),'Advisor observation':visit.get('agent_note',''),'Emails paused':visit.get('followup_paused',''),'Satisfaction':visit.get('satisfied') or 'Awaiting response',
            'Purchase interest':visit.get('purchase_intent') or 'Awaiting response','Reason':visit.get('reason',''),
            'Assistance':visit.get('assistance') or 'Not answered','Advisor status':visit.get('advisor_status',''),
            'Explore more':visit.get('explore_consent',''),'Revised preferences':visit.get('revised_preferences',''),
            'Reminder due':(at-timedelta(hours=1)).isoformat(timespec='minutes') if status=='Confirmed' else '',
            'Readiness':readiness,'Evidence':'; '.join(evidence) or 'No explicit buying intention recorded',
            'Next step':next_step,'Assessment':'Provisional; no calibrated purchase probability'}


def sync_visits(visits, db_path=FOLLOWUP_DB):
    """Discover visit-only conversations too, without guessing customer identity."""
    with _connect(db_path) as c:
        schema(c)
        for visit in visits:
            conversation=str(visit.get('conversation_id') or '').strip()
            if not conversation:
                conversation='visit:'+visit['visit_id']
            c.execute("""INSERT INTO crm_leads(id,conversation_id,customer_name,source,created_at,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(conversation_id) DO NOTHING""",
                (uuid4().hex,conversation,_redact(visit.get('customer_name') or 'Unnamed customer')[:200],'Property visit',_stamp(),_stamp()))
            name=_redact(visit.get('customer_name') or '')[:200]
            email=visit.get('followup_email') or (visit.get('contact_value','') if visit.get('contact_method')=='Email' else '')
            phone=visit.get('contact_value','') if visit.get('contact_method')=='WhatsApp' else ''
            c.execute("""UPDATE crm_leads SET
                customer_name=CASE WHEN customer_name IN ('','Unnamed customer') AND ?<>'' THEN ? ELSE customer_name END,
                email=CASE WHEN email='' THEN ? ELSE email END,
                phone=CASE WHEN phone='' THEN ? ELSE phone END
                WHERE conversation_id=?""",(name,name,email,phone,conversation))
