"""Owner topic navigation and direct shortcuts for frequent tasks."""
SECTIONS = {
    'Reports and Mira': ['Overview and reports'],
    'Visits and messaging': ['Approve a visit', 'WhatsApp confirmations', 'Visit records and email status'],
    'Customers and CRM': ['Customer CRM', 'Property advisor setup', 'Team actions', 'Customer journey and outcomes'],
    'Settings and help': ['Team access', 'Health and readiness', 'Website blueprint'],
}

TOPIC_DETAILS = {
    'Property advisor setup': 'property advisor assignment email automatic register attendance link setup location',
    'Team actions': 'manual pending exceptions assistance tasks callback overdue conflict missing advisor customer',
    'Approve a visit': 'approve approval booking appointment schedule property access',
    'WhatsApp confirmations': 'whatsapp message phone number manual send confirmation',
    'Visit records and email status': 'email delivery sent smtp reminder follow up consent attendance visit status',
    'Customer CRM': 'customer lead name advisor contact phone email deals tasks notes',
    'Customer journey and outcomes': 'journey purchase interest satisfaction feedback outcome assistance reschedule',
    'Overview and reports': 'dashboard kpi metrics reports performance analytics downloads excel inquiries conversations mira responses learning feedback ratings',
    'Team access': 'team manager peer access account permissions',
    'Health and readiness': 'health readiness configuration settings database groq',
    'Website blueprint': 'blueprint documentation flowchart website design',
}


def search_topics(query):
    words=query.casefold().split()
    return [topic for topic,details in TOPIC_DETAILS.items()
            if all(word in (topic+' '+details).casefold() for word in words)]


def choose_topic():
    import streamlit as st
    def open_dashboard():
        st.session_state.studio_search=''
        st.session_state.studio_topic_search=None
        st.session_state.studio_navigation_section='Reports and Mira'
        st.session_state['studio_navigation_topic_Reports and Mira']='Overview and reports'
        st.session_state.pop('studio_customer_search',None)
    st.button('Dashboard and KPI metrics',on_click=open_dashboard,key='studio_dashboard_home')
    query=st.text_input('Search Mira Studio',placeholder='Search a topic, or enter a customer name…',key='studio_search').strip()
    if query:
        matches=search_topics(query)
        if matches:
            st.caption('Select a matching topic to open its details. Clear the search to browse all sections.')
            return st.selectbox('Search results',matches,key='studio_search_result_'+query.casefold())
        st.caption('No topic matches. Open the customer CRM to search saved customer names, locations or assigned advisors.')
        if st.button('Search customer records for “'+query+'”',key='studio_search_customers'):
            st.session_state.crm_search=query
            st.session_state.studio_customer_search=query
        if st.session_state.get('studio_customer_search')==query:
            return 'Customer CRM'
    else:
        topic=st.selectbox('Search available Mira Studio topics',list(TOPIC_DETAILS),
                           index=None,placeholder='Click to see all topics, or type to search…',
                           key='studio_topic_search',
                           help='Choose any topic to open it directly. Use Search Mira Studio above for keywords or customer names.')
        if topic:
            return topic
    section=st.selectbox('Choose a section',list(SECTIONS),key='studio_navigation_section')
    return st.selectbox('Choose a topic',SECTIONS[section],key='studio_navigation_topic_'+section)


def render_shortcut(topic):
    import streamlit as st
    if topic=='Property advisor setup':
        from property_advisors import render_setup
        render_setup()
        return True
    if topic=='Team actions':
        from visit_actions import render_queue
        st.subheader('Team actions')
        st.session_state.auto_task_queue=True
        render_queue()
        st.info('Use Customer CRM to assign or complete advisor tasks. Use Approve a visit for pending bookings and Property advisor setup for missing site assignments.')
        return True
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
        selected=st.selectbox('Choose customer and visit',[v['id'] for v in visits],index=None,placeholder='Select a customer to prepare a new message',key='studio_wa_visit',format_func=lambda key: next(v['customer_name']+' · '+v['property_title']+' · '+v['visit_at'] for v in visits if v['id']==key))
        if selected is None:
            return True
        visit=next(v for v in visits if v['id']==selected)
        lead=next((r for r in list_leads() if r.get('conversation_id')==(visit.get('conversation_id') or 'visit:'+selected)),None)
        if not lead:
            from crm_service import sync_visits
            sync_visits([{**visit,'visit_id':selected}])
            lead=next(r for r in list_leads() if r['conversation_id']==(visit.get('conversation_id') or 'visit:'+selected))
        # Default straight to the selected booking rather than General follow-up.
        from visit_journey import owner_journeys
        journey=next(r for r in owner_journeys() if r['visit_id']==selected)
        render(lead,[journey],str(st.session_state.get('mira_studio_identity') or 'Owner'),selected_visit=selected)
        return True
    return False
