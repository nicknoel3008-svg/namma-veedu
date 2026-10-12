"""Property advisor assignments and owner-approved register delivery."""
from datetime import datetime, timedelta
from uuid import uuid4
import re
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode
from followup_service import _connect, FOLLOWUP_DB, email_config_issues
from agent_runtime import INDIA_TZ


def schema(c):
    from visit_attendance import schema as attendance_schema
    attendance_schema(c)
    c.execute("""CREATE TABLE IF NOT EXISTS property_visit_advisors (
        property_key TEXT PRIMARY KEY, advisor TEXT NOT NULL, email TEXT NOT NULL,
        active TEXT NOT NULL, revision TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS advisor_register_delivery (
        id TEXT PRIMARY KEY, visit_id TEXT NOT NULL, visit_at TEXT NOT NULL,
        revision TEXT NOT NULL, token TEXT NOT NULL, recipient TEXT NOT NULL,
        status TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(visit_id,visit_at,revision))""")
    c.execute("""CREATE TABLE IF NOT EXISTS advisor_assignment_history (
        id TEXT PRIMARY KEY, property_key TEXT NOT NULL, actor TEXT NOT NULL,
        detail TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    if getattr(c,'shared',False):
        for table in ('property_visit_advisors','advisor_register_delivery','advisor_assignment_history'):
            c.execute('ALTER TABLE '+table+' ENABLE ROW LEVEL SECURITY')


def save_assignment(property_key, advisor, email, *, active=True, actor='Owner', db_path=FOLLOWUP_DB):
    advisor=advisor.strip();email=email.strip()
    if not advisor or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
        raise ValueError('Enter the assigned advisor name and a valid email address.')
    with _connect(db_path) as c:
        schema(c)
        if not c.execute('SELECT id FROM property_visit_requests WHERE property_key=?',(property_key,)).fetchone():
            raise ValueError('Choose a property from the recorded visits.')
        old=c.execute('SELECT * FROM property_visit_advisors WHERE property_key=?',(property_key,)).fetchone()
        if old and (old['advisor'],old['email'],old['active'])==(advisor,email,'Yes' if active else 'No'):
            return
        stamp=datetime.now(INDIA_TZ).isoformat()
        # Withdraw existing bearer access when assignment changes or is disabled.
        c.execute("UPDATE advisor_visit_registers SET revoked='Yes' WHERE property_key=?",(property_key,))
        c.execute("UPDATE advisor_register_delivery SET status='cancelled' WHERE token IN (SELECT token FROM advisor_visit_registers WHERE property_key=?) AND status='queued'",(property_key,))
        c.execute('''INSERT INTO property_visit_advisors(property_key,advisor,email,active,revision,updated_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(property_key) DO UPDATE SET
            advisor=excluded.advisor,email=excluded.email,active=excluded.active,
            revision=excluded.revision,updated_at=excluded.updated_at''',
            (property_key,advisor[:120],email,'Yes' if active else 'No',uuid4().hex,stamp))
        c.execute('INSERT INTO advisor_assignment_history VALUES(?,?,?,?,?)',
            (uuid4().hex,property_key,actor,'Advisor assignment saved; register preparation '+('enabled' if active else 'disabled')+'; owner approval required before delivery',stamp))


def assignments(db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        return [dict(r) for r in c.execute('SELECT * FROM property_visit_advisors').fetchall()]


def run_advisor_worker(config, db_path=FOLLOWUP_DB, *, now=None):
    if str(config.get('VISIT_EMAIL_ENABLED','')).lower()!='true':return (0,0)
    if email_config_issues(config):raise ValueError('Advisor email configuration is incomplete.')
    base=config.get('FOLLOWUP_PUBLIC_URL','').rstrip('/')
    from urllib.parse import urlsplit
    parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Configure a public HTTPS website address for advisor registers.')
    now=now or datetime.now(INDIA_TZ);stamp=now.isoformat()
    with _connect(db_path) as c:
        schema(c)
        rows=c.execute("""SELECT v.*,a.advisor,a.email,a.revision FROM property_visit_requests v
            JOIN property_visit_advisors a ON a.property_key=v.property_key
            WHERE v.status='Confirmed' AND a.active='Yes'""").fetchall()
        for v in rows:
            at=datetime.fromisoformat(v['visit_at']);expiry=at.replace(hour=23,minute=59,second=59)+timedelta(days=7)
            if now>expiry:continue
            previous=c.execute('SELECT id FROM advisor_register_delivery WHERE visit_id=? AND visit_at=? AND revision=?',(v['id'],v['visit_at'],v['revision'])).fetchone()
            if previous:continue
            scope=c.execute("SELECT token FROM advisor_visit_registers WHERE property_key=? AND visit_day=? AND advisor=? AND revoked=''",(v['property_key'],at.date().isoformat(),v['advisor'])).fetchone()
            token=scope['token'] if scope else secrets.token_urlsafe(32)
            if not scope:
                c.execute('INSERT INTO advisor_visit_registers(token,property_key,visit_day,advisor,expires_at) VALUES(?,?,?,?,?)',(token,v['property_key'],at.date().isoformat(),v['advisor'],expiry.isoformat()))
            c.execute('''INSERT INTO advisor_register_delivery VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(visit_id,visit_at,revision) DO NOTHING''',
                (uuid4().hex,v['id'],v['visit_at'],v['revision'],token,v['email'],'queued',stamp))
        queued=c.execute("SELECT * FROM advisor_register_delivery WHERE status='queued'").fetchall()
    sent=failed=0
    for item in queued:
        with _connect(db_path) as c:
            from owner_approvals import is_approved
            if not is_approved(c,'advisor',item['id']):continue
            v=c.execute('''SELECT v.*,a.advisor,a.email,a.revision,a.active,r.revoked,r.expires_at
                FROM property_visit_requests v JOIN property_visit_advisors a ON a.property_key=v.property_key
                JOIN advisor_visit_registers r ON r.token=? WHERE v.id=?''',(item['token'],item['visit_id'])).fetchone()
            valid=v and v['status']=='Confirmed' and v['visit_at']==item['visit_at'] and v['active']=='Yes' and v['revision']==item['revision'] and v['email']==item['recipient'] and not v['revoked'] and now<=datetime.fromisoformat(v['expires_at'])
            if not valid:
                c.execute("UPDATE advisor_register_delivery SET status='cancelled',updated_at=? WHERE id=? AND status='queued'",(stamp,item['id']));continue
            if c.execute("UPDATE advisor_register_delivery SET status='sending',updated_at=? WHERE id=? AND status='queued'",(stamp,item['id'])).rowcount!=1:continue
        message=EmailMessage();message['From']=config['FOLLOWUP_SMTP_FROM'];message['To']=item['recipient']
        message['Subject']='Property visit attendance register - '+v['property_title']
        message.set_content('Hello '+v['advisor']+',\n\nA confirmed visit is scheduled for '+v['property_title']+' at '+v['visit_at']+'.\nOpen your private attendance register:\n'+base+'/?'+urlencode({'advisor_register':item['token']})+'\n\nThe register updates with confirmed bookings for this property and date. Record each customer as visited or did not visit after the appointment. Allow two hours before reporting a no-show. Keep this link private. It expires seven days after the visit date.\n\nNamma Veedu')
        state='sent'
        try:
            port=int(config.get('FOLLOWUP_SMTP_PORT') or 587)
            client=smtplib.SMTP_SSL(config['FOLLOWUP_SMTP_HOST'],port,context=ssl.create_default_context(),timeout=30) if port==465 else smtplib.SMTP(config['FOLLOWUP_SMTP_HOST'],port,timeout=30)
            with client as smtp:
                if port!=465:smtp.starttls(context=ssl.create_default_context())
                smtp.login(config['FOLLOWUP_SMTP_USERNAME'],config['FOLLOWUP_SMTP_PASSWORD']);smtp.send_message(message)
            sent+=1
        except Exception:
            state='needs_review';failed+=1
        with _connect(db_path) as c:
            c.execute("UPDATE advisor_register_delivery SET status=?,updated_at=? WHERE id=? AND status='sending'",(state,stamp,item['id']))
    return sent,failed


def render_setup():
    import streamlit as st
    import pandas as pd
    from visit_service import list_visit_requests
    if not st.session_state.get('owner_dashboard_authenticated'):return
    st.subheader('Property advisors and register approval')
    visits=list_visit_requests();properties={v['property_key']:v['property_title'] for v in visits}
    if not properties:
        st.info('Properties appear here when their first visit request is saved.');return
    saved={r['property_key']:r for r in assignments()}
    key=st.selectbox('Property',list(properties),format_func=lambda k:properties[k],key='advisor_property_setup')
    old=saved.get(key,{})
    with st.form('property_advisor_'+key):
        name=st.text_input('Property advisor name',value=old.get('advisor',''))
        email=st.text_input('Property advisor email',value=old.get('email',''))
        active=st.checkbox('Prepare private attendance registers for owner approval',value=old.get('active')=='Yes')
        st.caption('Enabling delivery grants this advisor access to customer names and appointment times for this property. Changing or disabling the assignment revokes its existing register links.')
        if st.form_submit_button('Add advisor changes to owner review'):
            try:
                from owner_approvals import stage
                stage('advisor:'+key,'Advisor for '+properties[key]+': '+name+' — '+email,
                      lambda: save_assignment(key,name,email,active=active,actor=str(st.session_state.get('mira_studio_identity') or 'Owner')))
            except ValueError as e:st.error(str(e))
    st.dataframe(pd.DataFrame([{'Property':title,'Advisor':saved.get(k,{}).get('advisor',''),'Email':saved.get(k,{}).get('email',''),'Status':'Owner approval required before sharing' if saved.get(k,{}).get('active')=='Yes' else 'Register preparation disabled'} for k,title in properties.items()]),hide_index=True)
    with _connect() as c:
        schema(c)
        delivery=[dict(r) for r in c.execute('''SELECT v.customer_name,v.property_title,v.visit_at,d.recipient,d.status,d.updated_at
            FROM advisor_register_delivery d JOIN property_visit_requests v ON v.id=d.visit_id ORDER BY d.updated_at DESC''').fetchall()]
    st.write('Advisor email delivery history')
    st.dataframe(pd.DataFrame(delivery),hide_index=True)
    st.caption('Sent means server submission. Sending or needs_review requires checking delivery before retrying; uncertain messages are not resent automatically.')

