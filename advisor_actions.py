"""Owner-approved advisor requests with scoped, expiring response links."""
from datetime import datetime, timedelta
from uuid import uuid4
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode
from agent_runtime import INDIA_TZ
from followup_service import _connect, FOLLOWUP_DB, email_config_issues


def schema(c):
    from property_advisors import schema as base_schema
    from advisor_directory import schema as directory_schema
    base_schema(c); directory_schema(c)
    c.execute('''CREATE TABLE IF NOT EXISTS advisor_action_requests (
        id TEXT PRIMARY KEY, visit_id TEXT NOT NULL, visit_at TEXT NOT NULL,
        kind TEXT NOT NULL, advisor TEXT NOT NULL, recipient TEXT NOT NULL,
        token TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL,
        status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', proposed_time TEXT NOT NULL DEFAULT '',
        mail_status TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(visit_id,visit_at,kind,recipient))''')
    if getattr(c,'shared',False):c.execute('ALTER TABLE advisor_action_requests ENABLE ROW LEVEL SECURITY')


def target(c, visit, kind):
    if kind=='Loan assistance':
        if visit['advisor_consent']!='Yes' or visit['assistance'] not in ('Both','Loan advisor'):
            raise ValueError('Customer consent for loan assistance is required.')
        row=c.execute("SELECT name AS advisor,email FROM property_advisors WHERE role='Loan advisor'").fetchone()
    elif kind=='Visit availability':
        if visit['status']!='Requested':raise ValueError('This booking is no longer awaiting availability.')
        row=c.execute("SELECT advisor,email FROM property_visit_advisors WHERE property_key=? AND active='Yes'",(visit['property_key'],)).fetchone()
    else:raise ValueError('Unsupported advisor request.')
    if not row:raise ValueError('Save the assigned advisor first.')
    return row


def create_request(visit_id,kind,db_path=FOLLOWUP_DB):
    now=datetime.now(INDIA_TZ)
    with _connect(db_path) as c:
        schema(c)
        visit=c.execute('SELECT v.*,j.advisor_consent,j.assistance FROM property_visit_requests v JOIN visit_journeys j ON j.visit_id=v.id WHERE v.id=?',(visit_id,)).fetchone()
        if not visit:raise ValueError('Visit not found.')
        advisor=target(c,visit,kind)
        existing=c.execute('SELECT id FROM advisor_action_requests WHERE visit_id=? AND visit_at=? AND kind=? AND recipient=?',(visit_id,visit['visit_at'],kind,advisor['email'])).fetchone()
        if existing:return existing['id']
        identifier=uuid4().hex
        c.execute('INSERT INTO advisor_action_requests(id,visit_id,visit_at,kind,advisor,recipient,token,expires_at,status,mail_status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                  (identifier,visit_id,visit['visit_at'],kind,advisor['advisor'],advisor['email'],secrets.token_urlsafe(32),(now+timedelta(days=14)).isoformat(),'Awaiting advisor response','queued',now.isoformat()))
        return identifier


def context(token,db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        row=c.execute('''SELECT r.*,v.customer_name,v.property_title,v.status AS booking_status,
            v.property_key,v.visit_at AS current_time,j.advisor_consent,j.assistance
            FROM advisor_action_requests r JOIN property_visit_requests v ON v.id=r.visit_id
            JOIN visit_journeys j ON j.visit_id=v.id WHERE r.token=?''',(token,)).fetchone()
        if not row or datetime.fromisoformat(row['expires_at'])<datetime.now(INDIA_TZ) or row['visit_at']!=row['current_time']:return None
        visit=dict(row);visit['status']=row['booking_status']
        try:current=target(c,visit,row['kind'])
        except ValueError:return None
        if current['email']!=row['recipient']:return None
        return dict(row)


def respond(token,status,note='',proposed_time='',db_path=FOLLOWUP_DB):
    row=context(token,db_path)
    if not row:raise ValueError('This request is expired or no longer current.')
    allowed=('Accepted','Alternative time proposed','Declined') if row['kind']=='Visit availability' else ('Accepted','In progress','Completed','Declined')
    if status not in allowed:raise ValueError('Choose a valid response.')
    if status=='Alternative time proposed':
        at=datetime.fromisoformat(proposed_time)
        if at.tzinfo is None or at<=datetime.now(INDIA_TZ):raise ValueError('Propose a future time with timezone.')
    with _connect(db_path) as c:
        c.execute('UPDATE advisor_action_requests SET status=?,note=?,proposed_time=?,updated_at=? WHERE id=?',
                  (status,note.strip()[:1000],proposed_time if status=='Alternative time proposed' else '',datetime.now(INDIA_TZ).isoformat(),row['id']))
        if row['kind']=='Loan assistance':
            progress={'Accepted':'Contacting','In progress':'Contacting','Completed':'Completed','Declined':'Requested'}[status]
            c.execute('UPDATE visit_journeys SET advisor_status=?,updated_at=? WHERE visit_id=?',(progress,datetime.now(INDIA_TZ).isoformat(),row['visit_id']))
        from customer_journey import event
        v=c.execute('SELECT * FROM property_visit_requests WHERE id=?',(row['visit_id'],)).fetchone()
        event(c,user_id=v['user_id'],conversation_id=v['conversation_id'],property_key=v['property_key'],visit_id=v['id'],event='Advisor action response',detail=row['kind']+': '+status+'; '+note.strip()[:1000])


def run_worker(config,db_path=FOLLOWUP_DB):
    if str(config.get('VISIT_EMAIL_ENABLED','')).lower()!='true':return 0,0
    if email_config_issues(config):raise ValueError('Advisor email settings are incomplete.')
    with _connect(db_path) as c:
        schema(c)
        rows=c.execute("SELECT * FROM advisor_action_requests WHERE mail_status='queued'").fetchall()
    sent=failed=0
    for row in rows:
        from owner_approvals import is_approved
        with _connect(db_path) as c:
            if not is_approved(c,'advisor_action',row['id']):continue
        current=context(row['token'],db_path)
        with _connect(db_path) as c:
            if not current:
                c.execute("UPDATE advisor_action_requests SET mail_status='skipped' WHERE id=? AND mail_status='queued'",(row['id'],));continue
            if c.execute("UPDATE advisor_action_requests SET mail_status='sending' WHERE id=? AND mail_status='queued'",(row['id'],)).rowcount!=1:continue
        mail=EmailMessage();mail['From']=config['FOLLOWUP_SMTP_FROM'];mail['To']=row['recipient']
        mail['Subject']='Namma Veedu - '+row['kind']
        link=config['FOLLOWUP_PUBLIC_URL'].rstrip('/')+'/?'+urlencode({'advisor_action':row['token']})
        mail.set_content('Hello '+row['advisor']+',\n\nPlease review this '+row['kind'].lower()+' request for '+current['property_title']+'.\nRequested visit time: '+row['visit_at']+'\n\nAccept, decline, or update progress through your private link:\n'+link+'\n\nKeep this link private. It expires after 14 days. Availability responses do not approve bookings. Coordinate customer contact through the owner.\nNamma Veedu')
        state='sent'
        try:
            port=int(config.get('FOLLOWUP_SMTP_PORT') or 587)
            client=smtplib.SMTP_SSL(config['FOLLOWUP_SMTP_HOST'],port,context=ssl.create_default_context(),timeout=30) if port==465 else smtplib.SMTP(config['FOLLOWUP_SMTP_HOST'],port,timeout=30)
            with client as smtp:
                if port!=465:smtp.starttls(context=ssl.create_default_context())
                smtp.login(config['FOLLOWUP_SMTP_USERNAME'],config['FOLLOWUP_SMTP_PASSWORD']);smtp.send_message(mail)
            sent+=1
        except Exception:state='needs_review';failed+=1
        with _connect(db_path) as c:c.execute("UPDATE advisor_action_requests SET mail_status=?,updated_at=? WHERE id=? AND mail_status='sending'",(state,datetime.now(INDIA_TZ).isoformat(),row['id']))
    return sent,failed


def render_response():
    import streamlit as st
    token=str(st.query_params.get('advisor_action','') or '')
    if not token:return
    row=context(token)
    if not row:st.warning('This advisor request is invalid, expired or no longer current.');st.stop()
    st.title('Advisor request')
    st.write(row['advisor']+' - '+row['kind'])
    st.write(row['customer_name']+' - '+row['property_title']+' - '+row['visit_at'])
    st.write('Current status: '+row['status'])
    st.caption('Keep this link private. Coordinate contact with the owner. Do not enter financial documents or account details.')
    with st.form('advisor_action_response'):
        options=['Accepted','Alternative time proposed','Declined'] if row['kind']=='Visit availability' else ['Accepted','In progress','Completed','Declined']
        status=st.selectbox('Response',options)
        note=st.text_area('Notes')
        proposed=st.text_input('Alternative visit time (example: 2026-10-22T10:00+05:30)') if row['kind']=='Visit availability' else ''
        if st.form_submit_button('Save advisor response'):
            try:respond(token,status,note,proposed);st.success('Response saved. The owner can review it in Mira Studio.')
            except ValueError as e:st.error(str(e))
    st.stop()


def render_owner():
    import streamlit as st
    if not st.session_state.get('owner_dashboard_authenticated'):return
    st.subheader('Advisor action requests')
    st.caption('Prepare a loan assistance or visit availability request for the saved advisor. Add it to Owner review, then approve all changes. Customer email pauses stay unchanged. Advisor acceptance does not automatically confirm a visit.')
    with _connect(FOLLOWUP_DB) as c:
        schema(c)
        visits=[dict(v) for v in c.execute('SELECT v.*,j.advisor_consent,j.assistance FROM property_visit_requests v JOIN visit_journeys j ON j.visit_id=v.id ORDER BY v.visit_at DESC').fetchall()]
        rows=c.execute('SELECT v.customer_name,v.property_title,r.kind,r.advisor,r.status,r.note,r.proposed_time,r.mail_status,r.updated_at FROM advisor_action_requests r JOIN property_visit_requests v ON v.id=r.visit_id ORDER BY r.updated_at DESC').fetchall()
    st.dataframe([dict(r) for r in rows],hide_index=True)
    if not visits:return
    selected=st.selectbox('Customer visit for advisor request',visits,format_func=lambda v:v['customer_name']+' - '+v['property_title']+' - '+v['visit_at'])
    kind=st.selectbox('Advisor request type',['Loan assistance','Visit availability'])
    try:
        with _connect(FOLLOWUP_DB) as c:advisor=target(c,selected,kind)
        st.write('Assigned advisor: '+advisor['advisor']+' ('+advisor['email']+')')
    except ValueError as e:st.info(str(e));return
    if st.button('Add advisor request to owner review'):
        from functools import partial
        from owner_approvals import stage
        stage('advisor-action:'+selected['id']+':'+kind,kind+' - '+selected['customer_name'],partial(create_request,selected['id'],kind))
