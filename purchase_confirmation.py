"""Explicit customer-reported purchases, separate from owner-verified outcomes."""
from datetime import datetime
from datetime import timedelta
import secrets
import ssl
import smtplib
from email.message import EmailMessage
from agent_runtime import INDIA_TZ
from followup_service import _connect,FOLLOWUP_DB
from visit_journey import schema
from customer_journey import event,schema as customer_schema


def schema_receipts(c):
    schema(c)
    c.execute("""CREATE TABLE IF NOT EXISTS purchase_receipts (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,property_key TEXT NOT NULL,visit_id TEXT NOT NULL,
        token TEXT NOT NULL UNIQUE,confirmed_at TEXT NOT NULL,rating INTEGER,
        customer_email TEXT NOT NULL DEFAULT '',customer_mail TEXT NOT NULL DEFAULT 'not_requested',
        owner_email TEXT NOT NULL DEFAULT '',owner_mail TEXT NOT NULL DEFAULT 'queued',
        UNIQUE(user_id,property_key))""")
    if getattr(c,'shared',False):c.execute('ALTER TABLE purchase_receipts ENABLE ROW LEVEL SECURITY')


def confirm_purchase(visit_id, *, user_id='', token='', confirmed=False, note='', email_receipt=False, db_path=FOLLOWUP_DB):
    if not confirmed:
        raise ValueError('Please confirm that you completed the purchase, rather than only expressing interest.')
    stamp=datetime.now(INDIA_TZ).isoformat(timespec='seconds')
    with _connect(db_path) as c:
        schema_receipts(c)
        row=c.execute('SELECT v.*,j.token,j.customer_purchase_confirmed_at FROM property_visit_requests v JOIN visit_journeys j ON j.visit_id=v.id WHERE v.id=?',(visit_id,)).fetchone()
        if not row or not ((user_id and user_id==row['user_id']) or (token and token==row['token'])):
            raise ValueError('This purchase cannot be confirmed from this session or link.')
        if token:
            # Link expiry is checked against the same clock as other visit responses.
            if datetime.now(INDIA_TZ)>datetime.fromisoformat(row['visit_at'])+timedelta(days=7):
                raise ValueError('This visit link has expired. Use your visit requests or contact the owner.')
        if row['customer_purchase_confirmed_at']:
            return 'Your purchase confirmation is already saved. Thank you!'
        customer_schema(c)
        from advisor_directory import schema as advisor_schema
        advisor_schema(c)
        owner=c.execute("SELECT email FROM property_advisors WHERE role='Property agent'").fetchone()
        from uuid import uuid4
        customer_email=row['contact_value'] if email_receipt and row['contact_method']=='Email' else ''
        c.execute("""INSERT INTO purchase_receipts(id,user_id,property_key,visit_id,token,confirmed_at,customer_email,customer_mail,owner_email,owner_mail)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,property_key) DO NOTHING""",
            (uuid4().hex,row['user_id'],row['property_key'],visit_id,secrets.token_urlsafe(32),stamp,customer_email,'queued' if customer_email else 'not_requested',owner['email'] if owner else '', 'queued' if owner else 'needs_review'))
        related=c.execute('SELECT id FROM property_visit_requests WHERE user_id=? AND property_key=?',(row['user_id'],row['property_key'])).fetchall()
        for visit in related:
            c.execute("UPDATE visit_journeys SET customer_purchase_confirmed_at=?,customer_purchase_note=?,updated_at=? WHERE visit_id=?",(stamp,note.strip()[:1000],stamp,visit['id']))
            c.execute("UPDATE property_visit_requests SET visit_email_consent='' WHERE id=?",(visit['id'],))
            c.execute("UPDATE visit_email_outbox SET status='skipped',updated_at=? WHERE visit_id=? AND status='queued'",(stamp,visit['id']))
        c.execute("UPDATE customer_property_choices SET status='Purchased',updated_at=? WHERE user_id=? AND property_key=?",(stamp,row['user_id'],row['property_key']))
        event(c,user_id=row['user_id'],conversation_id=row['conversation_id'],property_key=row['property_key'],visit_id=visit_id,event='Customer reported completed purchase',detail=note)
        return 'Congratulations on your new property! Your confirmation is saved for Nick to review, and visit reminders for this property have stopped.'


def rating_context(token,db_path=FOLLOWUP_DB):
    if not token or len(token)>100:return None
    with _connect(db_path) as c:
        schema_receipts(c)
        row=c.execute('SELECT r.*,v.property_title FROM purchase_receipts r JOIN property_visit_requests v ON v.id=r.visit_id WHERE r.token=?',(token,)).fetchone()
    if not row or datetime.now(INDIA_TZ)>datetime.fromisoformat(row['confirmed_at'])+timedelta(days=30):return None
    return dict(row)


def reports(db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema_receipts(c)
        return [dict(row) for row in c.execute('SELECT visit_id,confirmed_at,rating,customer_mail,owner_mail FROM purchase_receipts ORDER BY confirmed_at DESC').fetchall()]


def save_rating(token,rating,db_path=FOLLOWUP_DB):
    if type(rating) is not int or not 1<=rating<=5:raise ValueError('Choose a rating from 1 to 5.')
    if not rating_context(token,db_path):raise ValueError('This rating link is invalid or expired.')
    with _connect(db_path) as c:
        row=c.execute('SELECT * FROM purchase_receipts WHERE token=?',(token,)).fetchone()
        if row['rating']==rating:return
        c.execute('UPDATE purchase_receipts SET rating=? WHERE token=?',(rating,token))
        visit=c.execute('SELECT conversation_id FROM property_visit_requests WHERE id=?',(row['visit_id'],)).fetchone()
        event(c,user_id=row['user_id'],conversation_id=visit['conversation_id'],property_key=row['property_key'],visit_id=row['visit_id'],event='Final journey rating saved',detail=str(rating))


def run_purchase_worker(config,db_path=FOLLOWUP_DB):
    if str(config.get('VISIT_EMAIL_ENABLED','')).lower()!='true':return (0,0)
    from followup_service import email_config_issues
    if email_config_issues(config):raise ValueError('Purchase email configuration is incomplete.')
    with _connect(db_path) as c:
        schema_receipts(c)
        rows=c.execute("SELECT r.*,v.property_title FROM purchase_receipts r JOIN property_visit_requests v ON v.id=r.visit_id WHERE customer_mail='queued' OR owner_mail='queued'").fetchall()
    sent=failed=0
    for row in rows:
        for target in ('customer','owner'):
            state=target+'_mail';address=row[target+'_email']
            if row[state]!='queued':continue
            with _connect(db_path) as c:
                if not address:
                    c.execute(f"UPDATE purchase_receipts SET {state}='needs_review' WHERE id=? AND {state}='queued'",(row['id'],));failed+=1;continue
                claim=c.execute(f"UPDATE purchase_receipts SET {state}='sending' WHERE id=? AND {state}='queued'",(row['id'],))
                if claim.rowcount!=1:continue
            mail=EmailMessage();mail['From']=config['FOLLOWUP_SMTP_FROM'];mail['To']=address
            mail['Subject']='Congratulations on your property purchase!' if target=='customer' else 'Customer purchase confirmation — owner review needed'
            if target=='customer':
                link=config['FOLLOWUP_PUBLIC_URL'].rstrip('/')+'/?purchase_rating='+row['token']
                body=f"Congratulations on your new property!\n\n{row['property_title']}\nYour reported purchase is saved for owner review. Visit reminders for this property have stopped.\n\nHow was your experience with Mira? Please share a final rating (optional):\n{link}\nThis private link expires after 30 days.\n\nThank you for choosing Namma Veedu."
            else:
                body=f"A customer reported a completed purchase of {row['property_title']}.\nReview visit {row['visit_id']} in Mira Studio and record the verified outcome with an evidence note. This report is not yet owner-verified.\n{config['FOLLOWUP_PUBLIC_URL'].rstrip('/')}\nNamma Veedu"
            mail.set_content(body);status='sent'
            try:
                port=int(config.get('FOLLOWUP_SMTP_PORT') or 587)
                client=smtplib.SMTP_SSL(config['FOLLOWUP_SMTP_HOST'],port,context=ssl.create_default_context(),timeout=30) if port==465 else smtplib.SMTP(config['FOLLOWUP_SMTP_HOST'],port,timeout=30)
                with client as smtp:
                    if port!=465:smtp.starttls(context=ssl.create_default_context())
                    smtp.login(config['FOLLOWUP_SMTP_USERNAME'],config['FOLLOWUP_SMTP_PASSWORD']);smtp.send_message(mail)
                sent+=1
            except Exception:status='needs_review';failed+=1
            with _connect(db_path) as c:c.execute(f"UPDATE purchase_receipts SET {state}=? WHERE id=? AND {state}='sending'",(status,row['id']))
    return sent,failed
