"""Owner topic navigation and direct shortcuts for frequent tasks."""
SECTIONS = {
    'Visits and messaging': ['Approve a visit', 'WhatsApp confirmations', 'Visit records and email status'],
    'Customers and CRM': ['Customer CRM', 'Customer journey and outcomes'],
    'Reports and Mira': ['Overview and reports'],
    'Settings and help': ['Team access', 'Health and readiness', 'Website blueprint'],
}


def choose_topic():
    import streamlit as st
    section=st.selectbox('Choose a section',list(SECTIONS),key='studio_navigation_section')
    return st.selectbox('Choose a topic',SECTIONS[section],key='studio_navigation_topic_'+section)


def render_shortcut(topic):
    import streamlit as st
    if topic=='Approve a visit':
        from visit_approval_ui import render
        render()
        return True
    if topic=='Customer CRM':
        from crm_ui import render
        render()
        return True
    if topic=='WhatsApp confirmations':
        from visit_service import list_visit_requests
        from crm_service import list_leads
        from crm_whatsapp import render
        visits=[v for v in list_visit_requests() if v['status']=='Confirmed']
        st.subheader('WhatsApp confirmations')
        if not visits:
            st.info('No confirmed visits. Choose Approve a visit to review pending requests.')
            return True
        selected=st.selectbox('Choose customer and visit',[v['id'] for v in visits],format_func=lambda key: next(v['customer_name']+' · '+v['property_title']+' · '+v['visit_at'] for v in visits if v['id']==key))
        visit=next(v for v in visits if v['id']==selected)
        lead=next((r for r in list_leads() if r.get('conversation_id')==(visit.get('conversation_id') or 'visit:'+selected)),None)
        if not lead:
            from crm_service import sync_visits
            sync_visits([{**visit,'visit_id':selected}])
            lead=next(r for r in list_leads() if r['conversation_id']==(visit.get('conversation_id') or 'visit:'+selected))
        # Default straight to the selected booking rather than General follow-up.
        st.session_state['crm_wa_context_'+lead['id']]=selected
        from visit_journey import owner_journeys
        journey=next(r for r in owner_journeys() if r['visit_id']==selected)
        render(lead,[journey],str(st.session_state.get('mira_studio_identity') or 'Owner'))
        return True
    return False
