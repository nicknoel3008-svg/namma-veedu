"""Owner-managed advisor directory and consent-checked handoff drafts. Never sends."""
import re
from datetime import datetime
from agent_runtime import INDIA_TZ
from followup_service import _connect,FOLLOWUP_DB
from customer_journey import event


def schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS property_advisors (
        role TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL,updated_at TEXT NOT NULL)""")
    if getattr(c,'shared',False):c.execute('ALTER TABLE property_advisors ENABLE ROW LEVEL SECURITY')


def save_advisor(role,name,email,db_path=FOLLOWUP_DB):
    if role not in ('Property agent','Loan advisor') or not name.strip() or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email.strip()):
        raise ValueError('Enter a role, advisor name and valid email address.')
    with _connect(db_path) as c:
        schema(c)
        c.execute('INSERT INTO property_advisors VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET name=excluded.name,email=excluded.email,updated_at=excluded.updated_at', (role,name.strip()[:100],email.strip().lower(),datetime.now(INDIA_TZ).isoformat()))


def advisors(db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        return [dict(r) for r in c.execute('SELECT * FROM property_advisors').fetchall()]


def prepare_handoff(visit_id,role,db_path=FOLLOWUP_DB):
    from visit_journey import schema as journey_schema
    if role not in ('Property agent','Loan advisor'):raise ValueError('Choose a supported advisor role.')
    with _connect(db_path) as c:
        schema(c);journey_schema(c)
        advisor=c.execute('SELECT * FROM property_advisors WHERE role=?',(role,)).fetchone()
        row=c.execute('SELECT j.*,v.user_id,v.conversation_id,v.property_key,v.property_title,v.customer_name,v.contact_method,v.contact_value FROM visit_journeys j JOIN property_visit_requests v ON v.id=j.visit_id WHERE visit_id=?',(visit_id,)).fetchone()
        if not advisor:raise ValueError('Configure this advisor in the directory first.')
        if not row or row['advisor_consent']!='Yes' or row['assistance'] not in (role,'Both'):
            raise ValueError('This customer has not consented to this advisor handoff.')
        body=f"Hello {advisor['name']},\n\nThe customer consented to a {role.lower()} callback.\nCustomer: {row['customer_name']}\nContact ({row['contact_method']}): {row['contact_value']}\nProperty: {row['property_title']}\nRequested assistance: {row['assistance_details']}\n\nPlease coordinate through the Namma Veedu owner."
        event(c,user_id=row['user_id'],conversation_id=row['conversation_id'],property_key=row['property_key'],visit_id=visit_id,event='Advisor handoff draft prepared',detail=role)
        return {'to':advisor['email'],'subject':'Namma Veedu customer callback request','body':body}
