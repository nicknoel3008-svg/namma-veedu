"""CRM surface rendered only within the authenticated Mira Studio branch."""
from datetime import datetime, time
import pandas as pd
import streamlit as st
from agent_runtime import INDIA_TZ
from crm_service import STAGES, PRIORITIES, sync_inquiries, list_leads, save_lead, add_note, activities


def render():
    if not st.session_state.get('owner_dashboard_authenticated'):
        return
    st.caption('Manage leads and advisor actions. CRM stages are owner records; Closed won does not verify a purchase or change message consent.')
    refresh = st.button('Load / refresh CRM',key='crm_load')
    if refresh or not st.session_state.get('crm_loaded'):
        from inquiry_log import read_inquiries
        from visit_journey import owner_journeys
        from crm_service import sync_visits
        sync_inquiries(read_inquiries())
        sync_visits(owner_journeys())
        st.session_state.crm_loaded = True
    from visit_actions import render_queue
    render_queue()
    from crm_workspace import create_customer
    create_customer()
    if not st.session_state.get('crm_loaded'):
        return
    leads = list_leads()
    if not leads:
        from visit_journey import owner_journeys
        from visit_attendance import render_owner
        render_owner(owner_journeys())
        st.info('No conversation leads yet. Customer conversations will appear when you refresh the CRM.')
        return
    now = datetime.now(INDIA_TZ)
    from visit_journey import owner_journeys
    from crm_whatsapp import reminder_due
    journeys=owner_journeys()
    st.caption('Visit records sync automatically when the CRM opens. Use refresh to reload changes made while this screen is open.')
    from visit_attendance import render_owner
    render_owner(journeys)
    reminders=[v for v in journeys if reminder_due(v,now)]
    if reminders:
        st.warning(f'{len(reminders)} confirmed visit(s) are within the final hour. Select the customer below and prepare a WhatsApp reminder to send manually.')
        st.dataframe(pd.DataFrame([{'Customer':v['customer_name'],'Property':v['property_title'],'Visit time':v['visit_at'],'Conversation':v['conversation_id']} for v in reminders]),hide_index=True)
    active = [r for r in leads if r['stage'] not in ('Closed won','Closed lost')]
    overdue = lambda r: bool(r['due_at'] and datetime.fromisoformat(r['due_at']) <= now and r['stage'] not in ('Closed won','Closed lost'))
    cols=st.columns(3)
    cols[0].metric('Leads',len(leads)); cols[1].metric('Open leads',len(active)); cols[2].metric('Actions due',sum(overdue(r) for r in leads))
    search=st.text_input('Search customer, location or advisor',key='crm_search').casefold()
    stage=st.selectbox('Pipeline filter',('All',)+STAGES,key='crm_filter')
    due_only=st.checkbox('Show actions due',key='crm_due_only')
    filtered=[r for r in leads if (stage=='All' or r['stage']==stage) and (not due_only or overdue(r)) and search in ' '.join(str(r[k]) for k in ('customer_name','location','assigned_to','conversation_id')).casefold()]
    st.dataframe(pd.DataFrame(filtered)[['customer_name','location','property_type','budget','stage','priority','assigned_to','next_action','due_at']] if filtered else pd.DataFrame(),hide_index=True)
    if not filtered:
        return
    lead_id=st.selectbox('Open lead',[r['id'] for r in filtered],format_func=lambda key: next(r['customer_name']+' · '+(r['conversation_id'] or 'Manual customer') for r in filtered if r['id']==key),key='crm_selected')
    lead=next(r for r in filtered if r['id']==lead_id)
    actor=str(st.session_state.get('mira_studio_identity') or st.session_state.get('mira_studio_role') or 'Owner')
    from crm_workspace import render_workspace
    if st.button('Open customer, deals and tasks workspace',key='crm_workspace_load'):
        st.session_state.crm_workspace_loaded=True
    if st.session_state.get('crm_workspace_loaded'):
        render_workspace(lead,leads,actor)
    with st.form('crm_edit_'+lead_id+'_'+str(lead['version'])):
        selected_stage=st.selectbox('Lead stage',STAGES,index=STAGES.index(lead['stage']))
        priority=st.selectbox('Priority',PRIORITIES,index=PRIORITIES.index(lead['priority']))
        advisor=st.text_input('Assigned advisor',value=lead['assigned_to'])
        action=st.text_input('Next action',value=lead['next_action'])
        has_due=st.checkbox('Set action due time (IST)',value=bool(lead['due_at']))
        existing=datetime.fromisoformat(lead['due_at']) if lead['due_at'] else now
        day=st.date_input('Action date',value=existing.date())
        clock=st.time_input('Action time (IST)',value=existing.time().replace(tzinfo=None))
        save=st.form_submit_button('Save lead')
    if save:
        try:
            save_lead(lead_id,version=lead['version'],stage=selected_stage,priority=priority,assigned_to=advisor,next_action=action,due_at=datetime.combine(day,clock,tzinfo=INDIA_TZ).isoformat() if has_due else '',actor=actor)
            st.rerun()
        except ValueError as error:
            st.error(str(error))
    with st.form('crm_note_'+lead_id):
        note=st.text_area('Add an advisor note')
        note_save=st.form_submit_button('Save note')
    if note_save:
        try:
            add_note(lead_id,note,actor=actor); st.rerun()
        except ValueError as error:
            st.error(str(error))
    st.write('Activity history')
    st.dataframe(pd.DataFrame(activities(lead_id)),hide_index=True)
    with st.expander('Linked visits and customer journey'):
        linked=[r for r in journeys if lead['conversation_id'] and (r['conversation_id']==lead['conversation_id'] or lead['conversation_id']=='visit:'+r['visit_id'])]
        from crm_service import journey_summary
        st.dataframe(pd.DataFrame([journey_summary(r) for r in linked]),hide_index=True) if linked else st.info('No linked visits yet.')
        st.caption('For WhatsApp confirmation with email follow-ups, send the confirmation manually; the email worker handles reminders and later questions with consent. Other manual WhatsApp drafts require pressing Send. Customer feedback updates this view on refresh; an attendance promise is not a completed visit.')
    with st.expander('WhatsApp messages — free manual sending'):
        if st.button('Prepare WhatsApp messages',key='crm_wa_prepare_'+lead['id']):
            st.session_state['crm_wa_loaded_'+lead['id']]=True
        if st.session_state.get('crm_wa_loaded_'+lead['id']):
            from crm_whatsapp import render as render_whatsapp
            render_whatsapp(lead,linked,actor)
