"""Idempotent internal triage; never decides attendance or contacts advisors."""
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5, uuid4
from agent_runtime import INDIA_TZ
from followup_service import _connect, FOLLOWUP_DB


def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS crm_visit_task_links(task_id TEXT PRIMARY KEY,visit_id TEXT NOT NULL,visit_at TEXT NOT NULL,kind TEXT NOT NULL,active TEXT NOT NULL)')
    if getattr(c,'shared',False): c.execute('ALTER TABLE crm_visit_task_links ENABLE ROW LEVEL SECURITY')


def sync_actions(db_path=FOLLOWUP_DB, *, now=None, only_visit_id=None):
    from crm_service import schema as crm_schema, _audit
    now=now or datetime.now(INDIA_TZ)
    stamp=now.isoformat(timespec='seconds')
    with _connect(db_path) as c:
        crm_schema(c)
    with _connect(db_path) as c:
        schema(c)
    with _connect(db_path) as c:
        rows=c.execute('SELECT j.*,v.customer_name,v.property_title,v.status,v.conversation_id FROM visit_journeys j JOIN property_visit_requests v ON v.id=j.visit_id'+(' WHERE v.id=?' if only_visit_id else ''),(only_visit_id,) if only_visit_id else ()).fetchall()
        created=0
        for raw in rows:
            row=dict(raw); at=datetime.fromisoformat(row['visit_at'])
            old=c.execute('SELECT l.task_id,t.lead_id FROM crm_visit_task_links l JOIN crm_tasks t ON t.id=l.task_id WHERE l.visit_id=? AND l.visit_at<>? AND t.status IN (?,?)',(row['visit_id'],row['visit_at'],'Open','In progress')).fetchall()
            for task in old:
                c.execute("UPDATE crm_tasks SET status='Cancelled',version=version+1,updated_at=? WHERE id=?",(stamp,task['task_id']))
                _audit(c,task['lead_id'],'Mira automation','Old visit task cancelled','Visit time changed; task '+task['task_id'])
            conversation=row['conversation_id'] or 'visit:'+row['visit_id']
            c.execute('INSERT INTO crm_leads(id,conversation_id,customer_name,source,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(conversation_id) DO NOTHING',
                      (uuid4().hex,conversation,row['customer_name'],'Property visit',stamp,stamp))
            lead=c.execute('SELECT id,assigned_to FROM crm_leads WHERE conversation_id=?',(conversation,)).fetchone()
            live=row['status']=='Confirmed' and not row['customer_purchase_confirmed_at'] and row['purchase_outcome']!='Purchased'
            conflict=row['attended'] in ('Yes','No') and row['agent_attended'] in ('Yes','No') and row['attended']!=row['agent_attended']
            failed=c.execute("SELECT id FROM visit_email_outbox WHERE visit_id=? AND visit_at=? AND (status='needs_review' OR (status='sending' AND updated_at<?))",(row['visit_id'],row['visit_at'],(now-timedelta(hours=1)).isoformat())).fetchone()
            conditions={
                'assistance':(row['advisor_consent']=='Yes' and row['assistance'] not in ('','None') and row['advisor_status']!='Closed','Handle '+row['assistance']+' assistance request','Normal'),
                'conflict':(live and conflict,'Review conflicting attendance reports','High'),
                'missing_advisor':(live and now>=at+timedelta(days=1) and not row['agent_attended'],'Obtain site advisor attendance report','Normal'),
                'missing_customer':(live and now>=at+timedelta(days=1) and not row['attended'] and row['followup_paused']!='Yes','Review missing customer attendance response','Normal'),
                'reschedule':(row['status']=='Requested' and row['attendance']=='No','Approve requested replacement visit time','Normal'),
                'delivery':(bool(failed),'Review uncertain email delivery before any retry','High')}
            for kind,(active,title,priority) in conditions.items():
                key=uuid5(NAMESPACE_URL,'namma-veedu:'+row['visit_id']+':'+row['visit_at']+':'+kind).hex
                task=c.execute('SELECT * FROM crm_tasks WHERE id=?',(key,)).fetchone()
                previous=c.execute('SELECT active FROM crm_visit_task_links WHERE task_id=?',(key,)).fetchone()
                if active and not task:
                    inserted=c.execute('INSERT INTO crm_tasks(id,lead_id,title,assigned_to,due_at,status,priority,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                              (key,lead['id'],(title+' — '+row['property_title'])[:500],lead['assigned_to'],(now+timedelta(hours=4 if priority=='High' else 24)).isoformat(timespec='minutes'),'Open',priority,stamp))
                    if inserted.rowcount==1:
                        _audit(c,lead['id'],'Mira automation','Task created',title+'; Visit '+row['visit_id'])
                        created+=1
                elif active and task and previous and previous['active']=='No' and task['status'] in ('Completed','Cancelled'):
                    c.execute("UPDATE crm_tasks SET status='Open',version=version+1,updated_at=?,due_at=? WHERE id=? AND version=?",(stamp,(now+timedelta(hours=24)).isoformat(timespec='minutes'),key,task['version']))
                    _audit(c,lead['id'],'Mira automation','Task reopened',title+'; condition recurred')
                elif active and task and task['status'] in ('Open','In progress') and task['priority']=='Normal' and datetime.fromisoformat(task['due_at'])<=now:
                    c.execute("UPDATE crm_tasks SET priority='High',version=version+1,updated_at=? WHERE id=? AND version=?",(stamp,key,task['version']))
                    _audit(c,lead['id'],'Mira automation','Overdue task escalated',title)
                elif not active and task and task['status'] in ('Open','In progress'):
                    state='Cancelled' if kind=='assistance' and row['advisor_status']!='Closed' else 'Completed'
                    c.execute('UPDATE crm_tasks SET status=?,version=version+1,updated_at=? WHERE id=? AND version=?',(state,stamp,key,task['version']))
                    _audit(c,lead['id'],'Mira automation','Condition cleared',title+'; Visit '+row['visit_id'])
                if active or task:
                    c.execute('INSERT INTO crm_visit_task_links(task_id,visit_id,visit_at,kind,active) VALUES(?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET active=excluded.active',(key,row['visit_id'],row['visit_at'],kind,'Yes' if active else 'No'))
        return created


def list_actions(db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        return [dict(r) for r in c.execute('SELECT t.*,l.kind,l.visit_id,l.visit_at,c.customer_name FROM crm_visit_task_links l JOIN crm_tasks t ON t.id=l.task_id JOIN crm_leads c ON c.id=t.lead_id ORDER BY t.due_at').fetchall()]


def render_queue():
    import streamlit as st
    import pandas as pd
    with st.expander('Automatic exception and assistance tasks'):
        st.caption('The hosted worker creates tasks, uses an existing assigned advisor when available and raises overdue tasks to High priority. A task is a team action, not proof that a callback happened.')
        if st.button('Load automatic task queue'):st.session_state.auto_task_queue=True
        if st.session_state.get('auto_task_queue'):
            rows=list_actions()
            active=[r for r in rows if r['status'] in ('Open','In progress')]
            st.write(f'Open tasks: {len(active)}')
            st.dataframe(pd.DataFrame(active)[['customer_name','kind','title','assigned_to','due_at','priority','status']] if active else pd.DataFrame(),hide_index=True)
            st.caption('Open the customer workspace → Advisor tasks to assign, update or close a task. Close the assistance request in the visit controls after it is handled.')
