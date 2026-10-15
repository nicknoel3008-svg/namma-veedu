"""Owner review of dashboard drafts and individual outbound messages."""
from followup_service import _connect, FOLLOWUP_DB
from datetime import datetime
from agent_runtime import INDIA_TZ


def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS owner_message_approvals (id TEXT PRIMARY KEY, actor TEXT NOT NULL, approved_at TEXT NOT NULL)')
    if getattr(c,'shared',False):
        c.execute('ALTER TABLE owner_message_approvals ENABLE ROW LEVEL SECURITY')


def is_approved(c, category, identifier):
    schema(c)
    return bool(c.execute('SELECT id FROM owner_message_approvals WHERE id=?',(category+':'+identifier,)).fetchone())


def approve_messages(items, actor, db_path=FOLLOWUP_DB):
    with _connect(db_path) as c:
        schema(c)
        for category,identifier in items:
            c.execute('INSERT INTO owner_message_approvals VALUES(?,?,?) ON CONFLICT(id) DO NOTHING',
                      (category+':'+identifier,actor,datetime.now(INDIA_TZ).isoformat()))


def approve_assignment_registers(property_keys, actor, db_path=FOLLOWUP_DB):
    """Approve only the current register drafts for assignments just reviewed."""
    if not property_keys:return 0
    from property_advisors import run_advisor_worker
    run_advisor_worker({'VISIT_EMAIL_ENABLED':'true'},db_path,prepare_only=True)
    with _connect(db_path) as c:
        rows=c.execute("""SELECT d.id,v.property_key FROM advisor_register_delivery d
            JOIN property_visit_requests v ON v.id=d.visit_id
            JOIN property_visit_advisors a ON a.property_key=v.property_key
            WHERE d.status='queued' AND v.status='Confirmed' AND v.visit_at=d.visit_at
            AND a.active='Yes' AND a.revision=d.revision AND a.email=d.recipient""").fetchall()
        items=[('advisor',r['id']) for r in rows if r['property_key'] in property_keys]
    approve_messages(items,actor,db_path)
    return len(items)


def prepare_current_actions(db_path=FOLLOWUP_DB):
    from property_advisors import run_advisor_worker
    from visit_journey import run_visit_worker
    config={'VISIT_EMAIL_ENABLED':'true'}
    run_advisor_worker(config,db_path,prepare_only=True)
    run_visit_worker(config,db_path,prepare_only=True)


def pending_messages(db_path=FOLLOWUP_DB):
    messages=[]
    from advisor_actions import schema as action_schema
    from property_advisors import schema as advisor_schema
    with _connect(db_path) as c:
        advisor_schema(c)
        action_schema(c)
        schema(c)
        for r in c.execute("SELECT d.id,d.recipient,v.property_title,v.visit_at FROM advisor_register_delivery d JOIN property_visit_requests v ON v.id=d.visit_id WHERE d.status='queued'").fetchall():
            if not is_approved(c,'advisor',r['id']):messages.append(('advisor',r['id'],r['recipient'],r['property_title'],r['visit_at'],'Advisor attendance register'))
        for r in c.execute("SELECT o.id,o.kind,v.customer_name,v.property_title,v.visit_at,v.followup_email,v.contact_value FROM visit_email_outbox o JOIN property_visit_requests v ON v.id=o.visit_id WHERE o.status='queued'").fetchall():
            if not is_approved(c,'visit',r['id']):messages.append(('visit',r['id'],r['followup_email'] or r['contact_value'],r['property_title'],r['visit_at'],r['kind']))
        for r in c.execute("SELECT * FROM email_followups WHERE channel='email' AND status='scheduled' AND next_send_at<=?",(datetime.now(INDIA_TZ).isoformat(timespec='seconds'),)).fetchall():
            identifier=r['id']+':'+str(r['sent_count'])+':'+r['next_send_at']
            if not is_approved(c,'followup',identifier):messages.append(('followup',identifier,r['recipient_email'],r['preference_summary'],r['next_send_at'],'Email follow-up'))
        from purchase_confirmation import schema_receipts as purchase_schema
        purchase_schema(c)
        for r in c.execute("SELECT * FROM purchase_receipts WHERE customer_mail='queued' OR owner_mail='queued'").fetchall():
            for target in ('customer','owner'):
                identifier=r['id']+':'+target
                if r[target+'_mail']=='queued' and not is_approved(c,'purchase',identifier):messages.append(('purchase',identifier,r[target+'_email'],'Purchase confirmation',r['confirmed_at'],target+' receipt'))
        for r in c.execute("SELECT r.*,v.property_title FROM advisor_action_requests r JOIN property_visit_requests v ON v.id=r.visit_id WHERE r.mail_status='queued'").fetchall():
            if not is_approved(c,'advisor_action',r['id']):messages.append(('advisor_action',r['id'],r['recipient'],r['property_title'],r['visit_at'],r['kind']))
    return messages


def stage(key, label, callback):
    import streamlit as st
    st.session_state.setdefault('owner_pending_changes',{})[key]=(label,callback)
    st.success('Added to owner review. Use Approve all changes at the top of Mira Studio to save.')


def render():
    import streamlit as st
    if not st.session_state.get('owner_dashboard_authenticated'):return
    if st.session_state.get('mira_studio_role','Owner')!='Owner':
        st.info('An Owner must approve staged dashboard changes and outbound emails.')
        return
    pending=st.session_state.setdefault('owner_pending_changes',{})
    with st.expander('Owner review — approve all changes',expanded=bool(pending)):
        st.caption('Edits must first be added to owner review using their section button. Drafts stay in this signed-in session until approved. One approval saves all staged updates and approves every currently pending email action, including messages created by those updates. Review recipients and edits before approving. Future actions arriving after this batch require a new review; unapproved reminders may expire.')
        for label,_ in pending.values():st.write('• '+label)
        messages=[]
        try:
            prepare_current_actions()
            messages=pending_messages()
        except Exception:
            st.warning('Email approvals could not load. Draft changes can still be reviewed; email approvals remain blocked.')
        if messages:
            st.write('Messages awaiting approval')
            st.dataframe([{'Recipient':r[2],'Property':r[3],'Visit time':r[4],'Message':r[5]} for r in messages],hide_index=True)
        if not pending and not messages:st.info('No staged changes or queued messages awaiting approval.')
        if st.button('Approve all changes',disabled=not(pending or messages),key='owner_approve_all'):
            failed=False
            for key,(label,callback) in list(pending.items()):
                try:
                    callback()
                    del pending[key]
                    st.success('Saved: '+label)
                except Exception as e:
                    failed=True
                    st.error(label+': '+str(e))
            # A changed advisor invalidates old queued deliveries; workers revalidate.
            if not failed:
                actor=str(st.session_state.get('mira_studio_identity') or 'Owner')
                try:
                    prepare_current_actions()
                    current=pending_messages()
                    approve_messages([(r[0],r[1]) for r in current],actor)
                    st.success(f'All staged updates saved and {len(current)} pending email action(s) approved in one step. The hosted worker submits the emails; no second approval is needed for this batch.')
                except Exception:
                    st.error('Changes were saved, but register email approval could not complete. Reload Owner review to approve the prepared emails; no automatic approval was assumed.')
            else:st.warning('Some changes could not be saved. Their drafts remain for correction; message approval was withheld.')
        if pending and st.button('Discard staged changes',key='owner_discard_drafts'):
            pending.clear();st.rerun()

    from email_delivery_ui import render as render_email_delivery
    render_email_delivery()
