"""Owner-only visibility and manual dispatch of the existing hosted worker."""
import os
import requests
from followup_service import _connect, FOLLOWUP_DB

WORKFLOW_URL='https://github.com/nicknoel3008-svg/namma-veedu/actions/workflows/visit-emails.yml'
DISPATCH_URL='https://api.github.com/repos/nicknoel3008-svg/namma-veedu/actions/workflows/visit-emails.yml/dispatches'

def display_status(status, approved):
    if status=='queued': return 'Approved / queued' if approved else 'Awaiting approval'
    return {'sent':'Sent (SMTP accepted)','needs_review':'Needs attention','sending':'Sending','skipped':'Expired / skipped'}.get(status,status)

def delivery_rows(db_path=FOLLOWUP_DB):
    from owner_approvals import schema
    with _connect(db_path) as c:
        schema(c)
        rows=c.execute("""SELECT v.customer_name AS customer,v.property_title AS property,o.kind,o.status,o.updated_at,a.id AS approval
          FROM visit_email_outbox o JOIN property_visit_requests v ON v.id=o.visit_id
          LEFT JOIN owner_message_approvals a ON a.id='visit:' || o.id
          UNION ALL
          SELECT v.customer_name,v.property_title,'Advisor register',d.status,d.updated_at,a.id
          FROM advisor_register_delivery d JOIN property_visit_requests v ON v.id=d.visit_id
          LEFT JOIN owner_message_approvals a ON a.id='advisor:' || d.id
          ORDER BY updated_at DESC""").fetchall()
    return [{'Customer':r['customer'],'Property':r['property'],'Email':r['kind'],'Status':display_status(r['status'],bool(r['approval'])),'Updated':r['updated_at']} for r in rows]

def dispatch_worker(token):
    if not token: raise ValueError('Connect the hosted worker before sending.')
    response=requests.post(DISPATCH_URL,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},json={'ref':'main'},timeout=20)
    if response.status_code!=204:
        raise ValueError('The hosted worker could not start. Check its connection and GitHub Actions permission.')

def render():
    import streamlit as st
    if not st.session_state.get('owner_dashboard_authenticated') or st.session_state.get('mira_studio_role','Owner')!='Owner':return
    with st.expander('Email delivery — send approved emails now'):
        st.caption('Start the hosted worker for all eligible Owner-approved emails. This does not approve pending messages. Expired messages are skipped; SMTP acceptance does not confirm inbox delivery.')
        try:
            rows=delivery_rows()
            st.dataframe(rows,hide_index=True)
        except Exception:
            rows=[]
            st.warning('Email statuses could not load. Refresh to try again.')
        token=os.environ.get('GITHUB_WORKFLOW_TOKEN','') or str(st.secrets.get('GITHUB_WORKFLOW_TOKEN',''))
        if not token:
            st.info('One-time connection needed: add GITHUB_WORKFLOW_TOKEN in Streamlit secrets with Actions write permission for this repository. Enter the token privately, never in chat.')
            st.link_button('Open hosted worker',WORKFLOW_URL)
        if st.button('Send approved emails now',disabled=not token or not any(r['Status']=='Approved / queued' for r in rows),key='send_approved_emails_now'):
            try:
                dispatch_worker(token)
                st.success('Hosted worker requested. Refresh email statuses after it finishes; this is not delivery confirmation.')
            except (ValueError,requests.RequestException):
                st.error('The worker could not be confirmed as started. Check GitHub run history before trying again.')
        st.button('Refresh email statuses',key='refresh_email_delivery')
