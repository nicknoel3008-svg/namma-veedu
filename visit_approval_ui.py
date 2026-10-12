"""Small owner approval panel independent of CRM imports and searches."""
def render():
    import streamlit as st
    from visit_service import list_visit_requests, update_visit_status
    if not st.session_state.get('owner_dashboard_authenticated'):
        return
    st.subheader('Approve a property visit')
    try:
        visits=list_visit_requests()
        if not visits:
            st.info('No visit requests recorded.')
            return
        selected=st.selectbox('Select customer visit',[v['id'] for v in visits],
            format_func=lambda key: next(v['customer_name']+' · '+v['property_title']+' · '+v['visit_at']+' · '+v['status'] for v in visits if v['id']==key),key='quick_visit_selection')
        visit=next(v for v in visits if v['id']==selected)
        st.write('Current status: '+visit['status'])
        st.write('WhatsApp number: '+(visit['contact_value'] if visit['contact_method']=='WhatsApp' and visit['contact_value'] else 'Not provided for this booking'))
        st.write('Email recipient: '+(visit.get('followup_email') or (visit['contact_value'] if visit['contact_method']=='Email' else '') or 'Not provided'))
        st.write('Email permission: '+(visit.get('visit_email_consent') or 'No'))
        if visit['status']=='Confirmed':
            st.success('Already approved. No further approval is needed. Missing emails require a delivery check.')
        else:
            checked=st.checkbox('I have checked property access and availability for this appointment.',key='quick_visit_access_'+selected)
            if st.button('Approve this visit',disabled=not checked or visit['status']!='Requested',key='quick_visit_approve_'+selected):
                if update_visit_status(selected,'Confirmed'):
                    st.success('Visit approved. Consented email confirmation will be processed by the hosted worker. WhatsApp must be sent manually.')
                    st.rerun()
    except ValueError as error:
        st.error(str(error))
    except Exception:
        st.error('Could not load visit approvals. Please retry.')
