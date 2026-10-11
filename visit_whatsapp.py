"""WATI visit notifications with separate consent and durable submission claims."""
from datetime import datetime, timedelta
from uuid import uuid4
from agent_runtime import INDIA_TZ
from followup_service import FOLLOWUP_DB, _connect
from visit_journey import schema, ensure_journey
from whatsapp_followup import whatsapp_config_issues


def config_issues(config):
    issues = whatsapp_config_issues({**config, 'FOLLOWUP_WHATSAPP_ENABLED': 'true',
                                  'WATI_TEMPLATE_NAME': config.get('WATI_VISIT_CONFIRMATION_TEMPLATE', '')})
    if config.get('WHATSAPP_PROVIDER') != 'wati':
        issues.append('Visit WhatsApp requires WHATSAPP_PROVIDER=wati')
    if str(config.get('VISIT_WHATSAPP_ENABLED', '')).lower() != 'true':
        issues.append('Visit WhatsApp delivery is disabled (VISIT_WHATSAPP_ENABLED)')
    for kind in ('CONFIRMATION', 'REMINDER', 'REVIEW'):
        if not config.get('WATI_VISIT_' + kind + '_TEMPLATE'):
            issues.append('Missing WATI_VISIT_' + kind + '_TEMPLATE')
    return issues


def outbox_schema(c):
    schema(c)
    c.execute("""CREATE TABLE IF NOT EXISTS visit_whatsapp_outbox (
        id TEXT PRIMARY KEY, visit_id TEXT NOT NULL, visit_at TEXT NOT NULL,
        kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
        provider_message_id TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
        UNIQUE(visit_id,visit_at,kind))""")
    if getattr(c, 'shared', False):
        c.execute('ALTER TABLE visit_whatsapp_outbox ENABLE ROW LEVEL SECURITY')


def eligible(visit, journey, kind, at, now):
    if not visit or not journey:
        return False
    if (visit['status'] != 'Confirmed' or visit['contact_method'] != 'WhatsApp'
            or visit['visit_whatsapp_consent'] != 'Yes'
            or visit['visit_at'] != at.isoformat(timespec='minutes')
            or journey['customer_purchase_confirmed_at']):
        return False
    return ((kind == 'confirmation' and now < at)
            or (kind == 'reminder' and at-timedelta(hours=1) <= now < at
                and journey['attendance'] == 'Awaiting response')
            or (kind == 'review' and at+timedelta(hours=2) <= now < at+timedelta(days=1)
                and not journey['attended']))


def run_worker(config, db_path=FOLLOWUP_DB, *, now=None):
    if config_issues(config):
        raise ValueError('Visit WhatsApp configuration is incomplete; no messages sent.')
    now = now or datetime.now(INDIA_TZ)
    stamp = now.isoformat(timespec='seconds')
    with _connect(db_path) as c:
        outbox_schema(c)
        for visit in c.execute("SELECT * FROM property_visit_requests WHERE status='Confirmed' AND contact_method='WhatsApp' AND visit_whatsapp_consent='Yes'").fetchall():
            journey = ensure_journey(c, visit, stamp)
            at = datetime.fromisoformat(visit['visit_at'])
            confirmation = c.execute("SELECT status,updated_at FROM visit_whatsapp_outbox WHERE visit_id=? AND visit_at=? AND kind='confirmation'", (visit['id'],visit['visit_at'])).fetchone()
            for kind in ('confirmation', 'reminder', 'review'):
                if not eligible(visit, journey, kind, at, now):
                    continue
                # A confirmation in the final hour also serves as the reminder.
                if kind == 'reminder' and (not confirmation or confirmation['status'] != 'accepted' or datetime.fromisoformat(confirmation['updated_at']) >= at-timedelta(hours=1)):
                    continue
                c.execute("INSERT INTO visit_whatsapp_outbox(id,visit_id,visit_at,kind,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(visit_id,visit_at,kind) DO NOTHING", (uuid4().hex,visit['id'],visit['visit_at'],kind,stamp))
        queued = c.execute("SELECT * FROM visit_whatsapp_outbox WHERE status='queued'").fetchall()
    accepted = failed = 0
    for mail in queued:
        with _connect(db_path) as c:
            visit = c.execute('SELECT * FROM property_visit_requests WHERE id=?', (mail['visit_id'],)).fetchone()
            journey = c.execute('SELECT * FROM visit_journeys WHERE visit_id=?', (mail['visit_id'],)).fetchone()
            at = datetime.fromisoformat(mail['visit_at'])
            if not eligible(visit, journey, mail['kind'], at, now):
                c.execute("UPDATE visit_whatsapp_outbox SET status='skipped',updated_at=? WHERE id=? AND status='queued'", (stamp,mail['id']))
                continue
            if c.execute("UPDATE visit_whatsapp_outbox SET status='sending',updated_at=? WHERE id=? AND status='queued'", (stamp,mail['id'])).rowcount != 1:
                continue
        payload = dict(template_name=config['WATI_VISIT_'+mail['kind'].upper()+'_TEMPLATE'],
                       broadcast_name='namma_veedu_visit_'+mail['kind'], channel_number=config['WATI_CHANNEL_NUMBER'],
                       parameters=[{'name':name,'value':value} for name,value in (
                           ('name',visit['customer_name']), ('property',visit['property_title']),
                           ('visit_time',at.strftime('%d %b %Y, %I:%M %p IST')),
                           ('response_url',config['FOLLOWUP_PUBLIC_URL'].rstrip('/')+'/?visit_response='+journey['token']))])
        message_id = ''
        try:
            from whatsapp_followup import send_wati_template
            message_id = send_wati_template(config,visit['contact_value'],payload)
            state = 'accepted'; accepted += 1
        except Exception:
            state = 'needs_review'; failed += 1
        with _connect(db_path) as c:
            c.execute("UPDATE visit_whatsapp_outbox SET status=?,provider_message_id=?,updated_at=? WHERE id=? AND status='sending'", (state,message_id,stamp,mail['id']))
    return accepted, failed
