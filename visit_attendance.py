"""Scoped advisor registers and independent attendance reconciliation."""
from datetime import datetime, timedelta
import secrets
from agent_runtime import INDIA_TZ
from followup_service import _connect, FOLLOWUP_DB


def schema(c):
    from visit_journey import schema as journey_schema
    journey_schema(c)
    c.execute('''CREATE TABLE IF NOT EXISTS advisor_visit_registers (
        token TEXT PRIMARY KEY, property_key TEXT NOT NULL, visit_day TEXT NOT NULL,
        advisor TEXT NOT NULL, expires_at TEXT NOT NULL, revoked TEXT NOT NULL DEFAULT '')''')
    if getattr(c, 'shared', False):
        c.execute('ALTER TABLE advisor_visit_registers ENABLE ROW LEVEL SECURITY')


def attendance_state(row):
    customer, advisor = row.get('attended',''), row.get('agent_attended','')
    if customer and advisor:
        return ('Visited' if customer=='Yes' else 'Did not visit') if customer==advisor else 'Attendance conflict'
    return 'Awaiting advisor' if customer else 'Awaiting customer' if advisor else 'Awaiting both'


def create_register(visit_id, advisor, db_path=FOLLOWUP_DB):
    if not advisor.strip(): raise ValueError('Enter the assigned property advisor name.')
    with _connect(db_path) as c:
        schema(c)
        visit=c.execute('SELECT * FROM property_visit_requests WHERE id=?', (visit_id,)).fetchone()
        if not visit or visit['status']!='Confirmed': raise ValueError('Select a confirmed visit.')
        at=datetime.fromisoformat(visit['visit_at'])
        expiry=at.replace(hour=23,minute=59,second=59)+timedelta(days=7)
        if expiry<=datetime.now(INDIA_TZ): raise ValueError('This visit register has expired.')
        token=secrets.token_urlsafe(32)
        c.execute('INSERT INTO advisor_visit_registers(token,property_key,visit_day,advisor,expires_at) VALUES(?,?,?,?,?)',
                  (token,visit['property_key'],at.date().isoformat(),advisor.strip()[:120],expiry.isoformat()))
        return token


def revoke_register(token, db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        c.execute("UPDATE advisor_visit_registers SET revoked='Yes' WHERE token=?",(token,))


def register_context(token, db_path=FOLLOWUP_DB, *, now=None):
    now=now or datetime.now(INDIA_TZ)
    if not token or len(token)>100: return None
    with _connect(db_path) as c:
        schema(c)
        scope=c.execute("SELECT * FROM advisor_visit_registers WHERE token=? AND revoked=''",(token,)).fetchone()
        if not scope or now>datetime.fromisoformat(scope['expires_at']): return None
        visits=c.execute("SELECT * FROM property_visit_requests WHERE property_key=? AND status='Confirmed'",(scope['property_key'],)).fetchall()
        from visit_journey import ensure_journey
        rows=[]
        for visit in visits:
            if datetime.fromisoformat(visit['visit_at']).date().isoformat()!=scope['visit_day']: continue
            j=ensure_journey(c,visit,now.isoformat())
            # Do not disclose customer contacts, preferences, feedback or customer response tokens.
            rows.append({k:visit[k] for k in ('id','customer_name','property_title','visit_at')} |
                        {k:j[k] for k in ('agent_attended','agent_note','agent_recorded_at')})
        return dict(advisor=scope['advisor'],day=scope['visit_day'],visits=rows)


def record_agent_attendance(token, visit_id, attended, note='', db_path=FOLLOWUP_DB, *, now=None):
    now=now or datetime.now(INDIA_TZ)
    context=register_context(token,db_path,now=now)
    visit=next((v for v in context['visits'] if v['id']==visit_id),None) if context else None
    if not visit: raise ValueError('This register cannot update that booking.')
    if attended not in ('Yes','No'): raise ValueError('Choose visited or did not visit.')
    at=datetime.fromisoformat(visit['visit_at'])
    if now<at or (attended=='No' and now<at+timedelta(hours=2)):
        raise ValueError('Record attendance after the visit time; allow two hours before marking a no-show.')
    with _connect(db_path) as c:
        schema(c)
        scope=c.execute("SELECT * FROM advisor_visit_registers WHERE token=? AND revoked=''",(token,)).fetchone()
        if not scope or now>datetime.fromisoformat(scope['expires_at']):
            raise ValueError('This register link is revoked or expired.')
        current=c.execute('SELECT * FROM property_visit_requests WHERE id=?',(visit_id,)).fetchone()
        if not current or current['status']!='Confirmed' or current['visit_at']!=visit['visit_at'] or current['property_key']!=scope['property_key']:
            raise ValueError('The booking changed. Refresh the register.')
        c.execute('UPDATE visit_journeys SET agent_attended=?,agent_name=?,agent_note=?,agent_recorded_at=?,updated_at=? WHERE visit_id=? AND visit_at=?',
                  (attended,context['advisor'],note.strip()[:1000],now.isoformat(),now.isoformat(),visit_id,visit['visit_at']))
        from customer_journey import event
        event(c,user_id=current['user_id'],conversation_id=current['conversation_id'],property_key=current['property_key'],visit_id=visit_id,
              event='Property advisor attendance recorded',detail=context['advisor']+': '+attended+'; '+note.strip()[:1000])


def render_register():
    import streamlit as st
    token=str(st.query_params.get('advisor_register','') or '')
    if not token:return
    st.title('Property advisor · Attendance register')
    try:
        context=register_context(token)
        if not context:
            st.warning('This private register link is invalid, revoked or expired.');st.stop()
        st.write(context['advisor']+' · '+context['day'])
        st.caption('Keep this link private. Record only attendance you personally verified. Customer feedback is recorded separately.')
        rows=context['visits']
        st.write(f"Scheduled: {len(rows)} · Visited: {sum(v['agent_attended']=='Yes' for v in rows)} · Did not visit: {sum(v['agent_attended']=='No' for v in rows)} · Pending: {sum(not v['agent_attended'] for v in rows)}")
        for v in rows:
            with st.form('agent_'+v['id']):
                st.subheader(v['customer_name']+' · '+v['property_title'])
                st.write(v['visit_at'])
                st.caption('Recorded: '+(v['agent_attended'] or 'Pending'))
                value=st.radio('Attendance',['Yes','No'],index=None,key='agent_value_'+v['id'])
                note=st.text_area('Observation or correction reason',key='agent_note_'+v['id'])
                if st.form_submit_button('Save advisor attendance'):
                    record_agent_attendance(token,v['id'],value,note)
                    st.success('Advisor attendance saved. Refresh to see updated totals.')
        if st.button('Refresh register'):st.rerun()
    except ValueError as error:st.error(str(error))
    except Exception:st.error('Could not load or save the register. Please try again or contact the team.')
    st.stop()


def render_owner(journeys):
    import streamlit as st
    import pandas as pd
    from crm_service import journey_summary
    now=datetime.now(INDIA_TZ)
    with st.expander('Visit attendance and needs attention',expanded=True):
        summaries=[dict(Customer=v['customer_name'],**journey_summary(v,now=now)) for v in journeys]
        attention=[v for v in summaries if v['Booking status']=='Requested' or
                   (v['Emails paused']!='Yes' and (v['Verified attendance']=='Attendance conflict' or
                    (datetime.fromisoformat(v['Visit time'])+timedelta(hours=2)<=now and v['Booking status']=='Confirmed' and v['Verified attendance'].startswith('Awaiting')) or
                    v['Advisor status'] in ('Requested','Contacting') or v['Explore more']=='Yes'))]
        st.write(f'Visits needing attention: {len(attention)}')
        if attention:st.dataframe(pd.DataFrame(attention),hide_index=True)
        if summaries:
            st.dataframe(pd.DataFrame(summaries)[['Customer','Property','Visit time','Customer attendance','Advisor attendance','Verified attendance','Readiness']],hide_index=True)
            totals=pd.DataFrame([{'Property':v['Property'],'Visit date':v['Visit time'][:10],'Attendance':v['Verified attendance']} for v in summaries if v['Booking status']=='Confirmed'])
            if not totals.empty:
                st.caption('Property totals use matching customer and advisor reports. Pending reports are not counted as no-shows.')
                st.dataframe(totals.groupby(['Property','Visit date','Attendance']).size().reset_index(name='Customers'),hide_index=True)
        if st.button('Load advisor register controls'): st.session_state.advisor_register_controls=True
        if not st.session_state.get('advisor_register_controls'): return
        with _connect(FOLLOWUP_DB) as c:
            schema(c)
            visits=[dict(v) for v in c.execute("SELECT * FROM property_visit_requests WHERE status='Confirmed'").fetchall() if datetime.fromisoformat(v['visit_at'])+timedelta(days=7)>now]
            registers=[dict(r) for r in c.execute("SELECT * FROM advisor_visit_registers WHERE revoked='' ORDER BY expires_at DESC").fetchall() if datetime.fromisoformat(r['expires_at'])>now]
        st.subheader('Private property advisor registers')
        st.caption('Each link permits attendance updates for confirmed bookings at one property on one date. It shows customer names and times, without customer contacts or feedback. Share only with the assigned advisor. Links expire after seven days and can be revoked here.')
        if visits:
            selected=st.selectbox('Property and visit date',[v['id'] for v in visits],format_func=lambda key:next(v['property_title']+' · '+v['visit_at'][:10] for v in visits if v['id']==key))
            advisor=st.text_input('Assigned property advisor name')
            if st.button('Create private advisor register'):
                try:
                    create_register(selected,advisor)
                    st.rerun()
                except ValueError as error:st.error(str(error))
        from run_followup_worker import load_config
        from urllib.parse import urlsplit
        base=load_config().get('FOLLOWUP_PUBLIC_URL','').rstrip('/')
        parsed=urlsplit(base)
        for r in registers:
            st.write(r['advisor']+' · '+r['visit_day'])
            if parsed.scheme=='https' and parsed.hostname and not parsed.query and not parsed.fragment and not parsed.username:
                st.code(base+'/?advisor_register='+r['token'],language=None)
            else:st.warning('Configure the public HTTPS website address before sharing links.')
            if st.button('Revoke advisor link',key='revoke_'+r['token']):
                revoke_register(r['token']);st.rerun()
