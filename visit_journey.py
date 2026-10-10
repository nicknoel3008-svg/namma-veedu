"""Consent-based visit responses and an opt-in email outbox. Disabled by default."""
from datetime import datetime, timedelta
from email.message import EmailMessage
import secrets
import smtplib
import ssl
from uuid import uuid4

from agent_runtime import INDIA_TZ
from followup_service import _connect, FOLLOWUP_DB, email_config_issues
from visit_service import _schema as visit_schema


def schema(c):
    visit_schema(c)
    c.execute("""CREATE TABLE IF NOT EXISTS visit_journeys (
        visit_id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE, visit_at TEXT NOT NULL,
        attendance TEXT NOT NULL DEFAULT 'Awaiting response', reason TEXT NOT NULL DEFAULT '',
        attended TEXT NOT NULL DEFAULT '', satisfied TEXT NOT NULL DEFAULT '',
        assistance TEXT NOT NULL DEFAULT '', assistance_details TEXT NOT NULL DEFAULT '',
        advisor_consent TEXT NOT NULL DEFAULT '', advisor_status TEXT NOT NULL DEFAULT '',
        explore_consent TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS visit_email_outbox (
        id TEXT PRIMARY KEY, visit_id TEXT NOT NULL, visit_at TEXT NOT NULL,
        kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', updated_at TEXT NOT NULL,
        UNIQUE(visit_id,visit_at,kind))""")
    for column,default in (('purchase_intent',''),('revised_preferences',''),('purchase_outcome','Unknown'),('outcome_note',''),('customer_purchase_confirmed_at',''),('customer_purchase_note','')):
        if getattr(c,'shared',False):
            c.execute(f"ALTER TABLE visit_journeys ADD COLUMN IF NOT EXISTS {column} TEXT NOT NULL DEFAULT '{default}'")
        elif column not in {row[1] for row in c.execute('PRAGMA table_info(visit_journeys)')}:
            c.execute(f"ALTER TABLE visit_journeys ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")
    if getattr(c, 'shared', False):
        for table in ('visit_journeys', 'visit_email_outbox'):
            c.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')


def ensure_journey(c, visit, now):
    c.execute("""INSERT INTO visit_journeys(visit_id,token,visit_at,updated_at)
        VALUES(?,?,?,?) ON CONFLICT(visit_id) DO NOTHING""",
        (visit['id'], secrets.token_urlsafe(32), visit['visit_at'], now))
    row = c.execute('SELECT * FROM visit_journeys WHERE visit_id=?', (visit['id'],)).fetchone()
    if row['visit_at'] != visit['visit_at']:
        c.execute("""UPDATE visit_journeys SET token=?,visit_at=?,attendance='Awaiting response',
            reason='',attended='',satisfied='',assistance='',assistance_details='',
            advisor_consent='',advisor_status='',explore_consent='',purchase_intent='',revised_preferences='',updated_at=? WHERE visit_id=?""",
            (secrets.token_urlsafe(32), visit['visit_at'], now, visit['id']))
        row = c.execute('SELECT * FROM visit_journeys WHERE visit_id=?', (visit['id'],)).fetchone()
    return dict(row)


def response_context(token, db_path=FOLLOWUP_DB):
    if not token or len(token) > 100:
        return None
    with _connect(db_path) as c:
        schema(c)
        row = c.execute("""SELECT j.*,v.property_title,v.status,v.contact_method,v.preferences
            FROM visit_journeys j JOIN property_visit_requests v ON v.id=j.visit_id
            WHERE j.token=? AND j.visit_at=v.visit_at""", (token,)).fetchone()
    if not row:
        return None
    result = dict(row)
    if datetime.now(INDIA_TZ) > datetime.fromisoformat(result['visit_at']) + timedelta(days=7):
        return None
    return result


def record_response(token, *, action, reason='', visit_at=None, attended='', satisfied='',
                    assistance='None', details='', advisor_consent=False, explore_consent=False,
                    purchase_intent='Undecided', revised_preferences='',db_path=FOLLOWUP_DB, now=None):
    now = now or datetime.now(INDIA_TZ)
    stamp = now.isoformat(timespec='seconds')
    with _connect(db_path) as c:
        schema(c)
        row = c.execute("""SELECT j.*,v.status,v.property_key,v.user_id,v.conversation_id FROM visit_journeys j
            JOIN property_visit_requests v ON v.id=j.visit_id
            WHERE token=? AND j.visit_at=v.visit_at""", (token,)).fetchone()
        if not row or now > datetime.fromisoformat(row['visit_at']) + timedelta(days=7):
            raise ValueError('This visit link is invalid or expired.')
        if row['status'] != 'Confirmed':
            raise ValueError('This visit is no longer confirmed. Please contact the owner.')
        from customer_journey import event
        def log(label,detail=''):
            event(c,user_id=row['user_id'],conversation_id=row['conversation_id'],property_key=row['property_key'],visit_id=row['visit_id'],event=label,detail=detail)
        if action == 'yes' and now >= datetime.fromisoformat(row['visit_at']):
            raise ValueError('This visit time has passed. Please share your visit feedback instead.')
        if action == 'yes':
            c.execute("UPDATE visit_journeys SET attendance='Yes',updated_at=? WHERE token=?", (stamp,token))
            if row['attendance']!='Yes': log('Customer confirmed attendance')
            return 'Great! We look forward to welcoming you at the confirmed property and time.'
        if action in ('no', 'reschedule', 'explore'):
            if not reason.strip():
                raise ValueError('Please tell us the reason so we can help.')
            if action == 'explore' and not explore_consent:
                raise ValueError('Please give permission to return to Mira for another search.')
            if action == 'reschedule':
                if visit_at is None or visit_at.tzinfo is None or visit_at <= now:
                    raise ValueError('Choose a future visit date and time.')
                when = visit_at.astimezone(INDIA_TZ).replace(second=0,microsecond=0).isoformat(timespec='minutes')
                conflict = c.execute("SELECT id FROM property_visit_requests WHERE property_key=? AND visit_at=? AND status='Confirmed' AND id<>?", (row['property_key'],when,row['visit_id'])).fetchone()
                if conflict:
                    raise ValueError('That slot is already confirmed. Please choose another time.')
                c.execute("UPDATE property_visit_requests SET visit_at=?,status='Requested',slot_kind='Custom time',updated_at=? WHERE id=?", (when,stamp,row['visit_id']))
            else:
                c.execute("UPDATE property_visit_requests SET status='Cancelled',updated_at=? WHERE id=?", (stamp,row['visit_id']))
            c.execute("UPDATE visit_journeys SET attendance='No',reason=?,explore_consent=?,updated_at=? WHERE token=?", (reason.strip()[:1000], 'Yes' if explore_consent else '',stamp,token))
            c.execute('UPDATE visit_journeys SET revised_preferences=? WHERE token=?',(revised_preferences.strip()[:1000],token))
            log('Reschedule requested' if action=='reschedule' else 'Return to Mira permitted' if action=='explore' else 'Customer cancelled visit',reason)
            return 'Your new time is requested, pending owner confirmation.' if action == 'reschedule' else 'Your visit is cancelled. Thank you for letting us know.'
        if action == 'feedback':
            if now < datetime.fromisoformat(row['visit_at']):
                raise ValueError('Please share visit feedback after the visit time.')
            if attended not in ('Yes','No') or satisfied not in ('Yes','Partly','No','Not visited'):
                raise ValueError('Please answer the visit questions.')
            if attended == 'No':
                satisfied = 'Not visited'
                if not reason.strip():
                    raise ValueError('Please tell us why you could not visit.')
            elif satisfied=='Not visited' or purchase_intent=='Not visited':
                raise ValueError('For an attended visit, choose a satisfaction level and purchase decision.')
            if assistance not in ('None','Property agent','Loan advisor','Both'):
                raise ValueError('Choose the assistance you need.')
            if assistance != 'None' and (not details.strip() or not advisor_consent):
                raise ValueError('Please describe your needs and consent to an advisor callback request.')
            if purchase_intent not in ('Interested','Not interested','Undecided','Not visited'):
                raise ValueError('Please choose your purchase decision.')
            if attended=='No': purchase_intent='Not visited'
            if purchase_intent=='Not interested' and not reason.strip():
                raise ValueError('Please tell us why this property is not right for you.')
            c.execute("""UPDATE visit_journeys SET attended=?,satisfied=?,reason=?,assistance=?,
                assistance_details=?,advisor_consent=?,advisor_status=?,updated_at=? WHERE token=?""",
                (attended,satisfied,reason.strip()[:1000],assistance,details.strip()[:1000],
                 'Yes' if advisor_consent and assistance != 'None' else '',
                 'Requested' if assistance != 'None' else '',stamp,token))
            c.execute('UPDATE visit_journeys SET purchase_intent=?,revised_preferences=?,explore_consent=? WHERE token=?',
                (purchase_intent,revised_preferences.strip()[:1000],'Yes' if explore_consent else '',token))
            log('Visit feedback saved',f'{attended}; {satisfied}; {purchase_intent}')
            if assistance!='None': log('Advisor callback requested',assistance)
            if explore_consent: log('Return to Mira permitted',revised_preferences)
            return 'Thank you for your feedback. Your assistance request is saved for owner review; an advisor is not yet connected.' if assistance != 'None' else 'Thank you for sharing how your visit went.'
        raise ValueError('Unsupported visit response.')


def interest(row):
    reasons = []
    if row.get('purchase_outcome')=='Purchased':
        return 'Purchased (owner recorded)',row.get('outcome_note') or 'Owner recorded a completed purchase'
    if row.get('purchase_outcome')=='Did not purchase':
        return 'Did not purchase (owner recorded)',row.get('outcome_note') or 'Owner recorded the outcome'
    if row.get('customer_purchase_confirmed_at'):
        return 'Purchased (customer reported; owner review pending)',row.get('customer_purchase_note') or 'Customer explicitly reported a completed purchase'
    if row.get('purchase_intent')=='Not interested':
        return 'Not interested in this property',row.get('reason') or 'Customer declined this property'
    if row.get('purchase_intent')=='Interested': reasons.append('Customer explicitly interested in purchasing')
    if row['attended'] == 'Yes': reasons.append('Visit completed')
    if row['satisfied'] == 'Yes': reasons.append('Property matched preferences')
    if row['advisor_consent'] == 'Yes' and row['assistance'] != 'None':
        reasons.append('Advisor assistance requested')
    if row['advisor_status'] == 'Connected': reasons.append('Advisor connection recorded by owner')
    level = 'Strong engagement' if row['attended']=='Yes' and row['satisfied']=='Yes' and row['advisor_consent']=='Yes' else ('Engaged' if reasons else 'Insufficient evidence')
    return level, '; '.join(reasons) or 'No visit or assistance feedback yet'


def owner_journeys(db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        rows = c.execute("""SELECT j.visit_id,j.visit_at,j.attendance,j.reason,j.attended,j.satisfied,
            j.assistance,j.assistance_details,j.advisor_consent,j.advisor_status,j.explore_consent,
            j.purchase_intent,j.revised_preferences,j.purchase_outcome,j.outcome_note,j.customer_purchase_confirmed_at,j.customer_purchase_note,
            v.property_title,v.customer_name,v.contact_method,v.contact_value,v.status,v.conversation_id,v.preferences,v.user_id
            FROM visit_journeys j JOIN property_visit_requests v ON v.id=j.visit_id""").fetchall()
        all_emails=c.execute('SELECT visit_id,visit_at,kind,status FROM visit_email_outbox').fetchall()
        email_states={(mail['visit_id'],mail['visit_at'],mail['kind']):mail['status'] for mail in all_emails}
    results = []
    for row in rows:
        result = dict(row)
        for kind in ('reminder','review'):
            result[kind+' email'] = email_states.get((row['visit_id'],row['visit_at'],kind),'Not sent')
        result['Purchase interest'], result['Evidence'] = interest(result)
        results.append(result)
    return results


def set_advisor_status(visit_id, status, db_path=FOLLOWUP_DB):
    if status not in ('Requested','Contacting','Connected','Closed'):
        raise ValueError('Unsupported advisor status.')
    with _connect(db_path) as c:
        schema(c)
        previous=c.execute('SELECT j.advisor_status,j.advisor_consent,v.user_id,v.conversation_id,v.property_key FROM visit_journeys j JOIN property_visit_requests v ON v.id=j.visit_id WHERE visit_id=?',(visit_id,)).fetchone()
        c.execute("UPDATE visit_journeys SET advisor_status=?,updated_at=? WHERE visit_id=? AND advisor_consent='Yes' AND assistance<>'None'", (status,datetime.now(INDIA_TZ).isoformat(),visit_id))
        if previous and previous['advisor_consent']=='Yes' and previous['advisor_status']!=status:
            from customer_journey import event
            event(c,user_id=previous['user_id'],conversation_id=previous['conversation_id'],property_key=previous['property_key'],visit_id=visit_id,event='Advisor status updated',detail=status)


def record_purchase_outcome(visit_id, outcome, note, db_path=FOLLOWUP_DB):
    if outcome not in ('Unknown','Purchased','Did not purchase','Still deciding') or not note.strip():
        raise ValueError('Choose an outcome and record the evidence or source of confirmation.')
    with _connect(db_path) as c:
        schema(c)
        visit=c.execute('SELECT * FROM property_visit_requests WHERE id=?',(visit_id,)).fetchone()
        if not visit: raise ValueError('Visit not found.')
        c.execute('UPDATE visit_journeys SET purchase_outcome=?,outcome_note=?,updated_at=? WHERE visit_id=?',(outcome,note.strip()[:1000],datetime.now(INDIA_TZ).isoformat(),visit_id))
        from customer_journey import event
        event(c,user_id=visit['user_id'],conversation_id=visit['conversation_id'],property_key=visit['property_key'],visit_id=visit_id,event='Purchase outcome recorded',detail=outcome+': '+note)


def resume_preferences(token, db_path=FOLLOWUP_DB):
    """Read only preferences, never transfer identity, contacts or chat access."""
    import json
    context=response_context(token,db_path)
    if not context or context['explore_consent']!='Yes': return None
    return {'preferences':json.loads(context['preferences']), 'changes':context['revised_preferences']}


def run_visit_worker(config, db_path=FOLLOWUP_DB, *, now=None):
    """Explicit enable flag required. Invoke every five minutes on a reliable host."""
    if str(config.get('VISIT_EMAIL_ENABLED','')).lower() != 'true':
        return (0,0)
    if email_config_issues(config):
        raise ValueError('Visit email SMTP configuration is incomplete.')
    now = now or datetime.now(INDIA_TZ)
    stamp = now.isoformat(timespec='seconds')
    with _connect(db_path) as c:
        schema(c)
        visits = c.execute("SELECT * FROM property_visit_requests WHERE status='Confirmed' AND contact_method='Email' AND visit_email_consent='Yes'").fetchall()
        for visit in visits:
            at = datetime.fromisoformat(visit['visit_at'])
            journey = ensure_journey(c,visit,stamp)
            kind = None
            if journey['customer_purchase_confirmed_at']: continue
            if at-timedelta(hours=1) <= now < at and journey['attendance']=='Awaiting response': kind='reminder'
            if at+timedelta(hours=2) <= now < at+timedelta(days=1) and not journey['attended']: kind='review'
            if kind:
                c.execute("""INSERT INTO visit_email_outbox(id,visit_id,visit_at,kind,updated_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(visit_id,visit_at,kind) DO NOTHING""", (uuid4().hex,visit['id'],visit['visit_at'],kind,stamp))
        queued = c.execute("SELECT * FROM visit_email_outbox WHERE status='queued'").fetchall()
    sent=failed=0
    for mail in queued:
        with _connect(db_path) as c:
            visit = c.execute('SELECT * FROM property_visit_requests WHERE id=?', (mail['visit_id'],)).fetchone()
            j = c.execute('SELECT * FROM visit_journeys WHERE visit_id=?',(mail['visit_id'],)).fetchone()
            at = datetime.fromisoformat(mail['visit_at'])
            valid = visit and j and not j['customer_purchase_confirmed_at'] and visit['status']=='Confirmed' and visit['visit_at']==mail['visit_at'] and visit['visit_email_consent']=='Yes'
            valid = valid and ((mail['kind']=='reminder' and at-timedelta(hours=1)<=now<at and j['attendance']=='Awaiting response') or (mail['kind']=='review' and at+timedelta(hours=2)<=now<at+timedelta(days=1) and not j['attended']))
            if not valid:
                c.execute("UPDATE visit_email_outbox SET status='skipped',updated_at=? WHERE id=? AND status='queued'",(stamp,mail['id']))
                continue
            claim=c.execute("UPDATE visit_email_outbox SET status='sending',updated_at=? WHERE id=? AND status='queued'",(stamp,mail['id']))
            if claim.rowcount!=1: continue
        message=EmailMessage()
        message['From']=config['FOLLOWUP_SMTP_FROM'];message['To']=visit['contact_value']
        message['Subject']='Please confirm your property visit' if mail['kind']=='reminder' else 'How was your property visit?'
        prompt='Will you attend? Choose Yes, No or Reschedule on the secure response page.' if mail['kind']=='reminder' else 'Did you attend, and did the property match your preferences? Tell us if you need property or loan assistance.'
        url=config['FOLLOWUP_PUBLIC_URL'].rstrip('/')+'/?visit_response='+j['token']
        message.set_content(f"Hello {visit['customer_name']},\n\n{visit['property_title']}\nVisit: {at.strftime('%d %b %Y, %I:%M %p IST')}\n\n{prompt}\n{url}\n\nIf you no longer want visit emails, cancel the visit through this page or contact the owner.\nNamma Veedu")
        state='sent'
        try:
            port=int(config.get('FOLLOWUP_SMTP_PORT') or 587)
            client=smtplib.SMTP_SSL(config['FOLLOWUP_SMTP_HOST'],port,context=ssl.create_default_context(),timeout=30) if port==465 else smtplib.SMTP(config['FOLLOWUP_SMTP_HOST'],port,timeout=30)
            with client as smtp:
                if port!=465: smtp.starttls(context=ssl.create_default_context())
                smtp.login(config['FOLLOWUP_SMTP_USERNAME'],config['FOLLOWUP_SMTP_PASSWORD'])
                smtp.send_message(message)
            sent+=1
        except Exception:
            state='needs_review';failed+=1
        with _connect(db_path) as c:
            c.execute('UPDATE visit_email_outbox SET status=?,updated_at=? WHERE id=? AND status=\'sending\'',(state,stamp,mail['id']))
    return sent,failed
