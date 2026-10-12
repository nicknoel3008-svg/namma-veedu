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


def suggested_assignment(property, records):
    """Use contact fields only on the exact booked property; never guess an agent."""
    from visit_service import property_key
    candidates={}
    for record in records:
        if property_key(record)!=property['property_key']:continue
        def value(fields):
            for field in fields:
                text=str(record.get(field) or '').strip()
                if text and text.lower() not in ('nan','none'):return text
            return ''
        email=value(('agent_email','listing_contact_email','public_contact_email','contact_email','broker_email'))
        name=value(('agent_name','listing_contact_name','public_contact_name','contact_person','contact_name','broker_name'))
        if name and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
            candidates[email.lower()]={'advisor':name,'email':email,'source':record.get('source_url') or record.get('source_name') or 'Property dataset'}
    return next(iter(candidates.values())) if len(candidates)==1 else {}


def run_advisor_worker(config, db_path=FOLLOWUP_DB, *, now=None, prepare_only=False):
    if str(config.get('VISIT_EMAIL_ENABLED','')).lower()!='true':return (0,0)
    if not prepare_only and email_config_issues(config):raise ValueError('Advisor email configuration is incomplete.')
    base=config.get('FOLLOWUP_PUBLIC_URL','').rstrip('/')
    from urllib.parse import urlsplit
    parsed=urlsplit(base)
    if not prepare_only and (parsed.scheme!='https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password):
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
    if prepare_only:
        return 0,0
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


def apply_assignment_edits(rows, edits, contacts):
    updated=[dict(row) for row in rows]
    for index,changes in edits.items():
        row=updated[int(index)]
        row.update({key:value for key,value in changes.items() if key in ('Select','Saved CRM advisor','Advisor','Advisor email','Prepare register')})
        if 'Saved CRM advisor' in changes:
            contact=contacts.get(changes['Saved CRM advisor'])
            if contact:
                row['Advisor']=contact['name'];row['Advisor email']=contact['email']
                row['Assignment']='Temporary - actual site advisor pending'
            else:
                row['Assignment']='Owner / property source - verify before approval'
        elif 'Advisor' in changes or 'Advisor email' in changes:
            row['Saved CRM advisor']='Custom / property source'
            row['Assignment']='Owner edited - verify before approval'
    return updated


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
    from advisor_directory import advisors
    from property_search import load_properties
    from functools import partial
    from hashlib import sha256
    directory=[r for r in advisors() if r['role']=='Property agent']
    contacts={r['name']+' | '+r['email']:r for r in directory}
    try:
        records=load_properties().fillna('').to_dict('records')
    except (OSError,ValueError):
        records=[]
        st.warning('Property contact data could not be read. Saved CRM contacts remain available.')
    fingerprint=sha256(repr((properties,saved,directory)).encode()).hexdigest()
    if st.session_state.get('advisor_table_fingerprint')!=fingerprint:
        rows=[]
        for key,title in properties.items():
            old=saved.get(key) or suggested_assignment(next(v for v in visits if v['property_key']==key),records)
            # User authorized CRM contacts as temporary assignments; never send before approval.
            if not old and directory:
                old={'advisor':directory[0]['name'],'email':directory[0]['email']}
            choice=next((label for label,r in contacts.items() if r['name']==old.get('advisor') and r['email']==old.get('email')),'Custom / property source')
            rows.append({'Select':False,'Property':title,'Saved CRM advisor':choice,
                'Advisor':old.get('advisor',''),'Advisor email':old.get('email',''),
                'Prepare register':old.get('active','Yes')=='Yes',
                'Assignment':'Temporary - actual site advisor pending' if choice in contacts else 'Owner / property source - verify before approval',
                'Property key':key})
        st.session_state.advisor_table_rows=rows
        st.session_state.advisor_table_fingerprint=fingerprint
        st.session_state.advisor_table_revision=st.session_state.get('advisor_table_revision',0)+1
    def select_all_rows():
        for row in st.session_state.advisor_table_rows:row['Select']=st.session_state.advisor_table_all
        st.session_state.advisor_table_revision+=1
    st.caption('Review and edit advisors directly in this table. Saved CRM contacts are temporary suggestions until actual site contacts are available. Choosing a saved advisor fills their name and email. Selected rows are staged for Owner approval; no register is shared here.')
    st.checkbox('Select all properties',key='advisor_table_all',on_change=select_all_rows)
    editor_key='advisor_assignment_table_'+str(st.session_state.advisor_table_revision)
    def apply_edits():
        edits=st.session_state.get(editor_key,{}).get('edited_rows',{})
        st.session_state.advisor_table_rows=apply_assignment_edits(st.session_state.advisor_table_rows,edits,contacts)
        st.session_state.advisor_table_revision+=1
    edited=st.data_editor(st.session_state.advisor_table_rows,hide_index=True,use_container_width=True,
        disabled=['Property','Property key','Assignment'],key=editor_key,on_change=apply_edits,
        column_config={'Property key':None,'Select':st.column_config.CheckboxColumn('Select'),
            'Saved CRM advisor':st.column_config.SelectboxColumn('Saved CRM advisor',options=['Custom / property source',*contacts]),
            'Prepare register':st.column_config.CheckboxColumn('Prepare register')})
    selected=[r for r in edited if r['Select']]
    if st.button('Add selected changes to owner review',disabled=not selected,key='advisor_table_stage'):
        invalid=[r['Property'] for r in selected if not str(r['Advisor']).strip() or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',str(r['Advisor email']).strip())]
        if invalid:
            st.error('A valid advisor name and email are missing for: '+', '.join(invalid))
        else:
            from owner_approvals import stage
            actor=str(st.session_state.get('mira_studio_identity') or 'Owner')
            for row in selected:
                stage('advisor:'+row['Property key'],'Advisor for '+row['Property']+': '+row['Advisor']+' - '+row['Advisor email'],
                    partial(save_assignment,row['Property key'],row['Advisor'],row['Advisor email'],active=bool(row['Prepare register']),actor=actor))
            st.info('Open Owner review at the top, review your selected assignments, then Approve all changes.')
    with _connect() as c:
        schema(c)
        delivery=[dict(r) for r in c.execute('''SELECT v.customer_name,v.property_title,v.visit_at,d.recipient,d.status,d.updated_at
            FROM advisor_register_delivery d JOIN property_visit_requests v ON v.id=d.visit_id ORDER BY d.updated_at DESC''').fetchall()]
    st.write('Advisor email delivery history')
    st.dataframe(pd.DataFrame(delivery),hide_index=True)
    st.caption('Sent means server submission. Sending or needs_review requires checking delivery before retrying; uncertain messages are not resent automatically.')

