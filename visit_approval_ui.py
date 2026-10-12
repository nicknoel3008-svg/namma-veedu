"""Owner approval dataset with explicit bulk selection."""
def approve_selected(rows):
    from visit_service import update_visit_status
    approved, errors = [], []
    for row in rows:
        if not row.get('Approve') or row.get('Status') != 'Requested':
            continue
        try:
            if update_visit_status(row['Request ID'], 'Confirmed'):
                approved.append(row['Request ID'])
            else:
                errors.append(row['Customer'] + ': request no longer exists.')
        except ValueError as error:
            errors.append(row['Customer'] + ': ' + str(error))
    return approved, errors


def render():
    import streamlit as st
    from visit_service import list_visit_requests
    if not st.session_state.get('owner_dashboard_authenticated'):
        return
    st.subheader('Approve property visits')
    result=st.session_state.pop('visit_bulk_result',None)
    if result:
        approved,errors=result
        if approved:
            st.success(f'{len(approved)} visit(s) approved. Consented emails will be processed automatically. WhatsApp confirmation remains manual.')
        for error in errors:
            st.warning(error)
    try:
        visits=list_visit_requests()
        pending=[v for v in visits if v['status']=='Requested']
        if pending:
            st.caption('Tick the visits whose property access and appointment availability you have checked, then approve them together. Past appointments and conflicting slots cannot be approved.')
            all_selected=st.checkbox('Select all pending requests',key='visit_bulk_all_'+str(st.session_state.get('visit_bulk_revision',0)))
            rows=[{'Approve':all_selected,'Customer':v['customer_name'],'Property':v['property_title'],
                   'Visit time':v['visit_at'],'Status':v['status'],
                   'WhatsApp number':v['contact_value'] if v['contact_method']=='WhatsApp' else '',
                   'Email':v.get('followup_email') or (v['contact_value'] if v['contact_method']=='Email' else ''),
                   'Email permission':v.get('visit_email_consent') or 'No','Request ID':v['id']} for v in pending]
            selected=st.data_editor(rows,hide_index=True,use_container_width=True,
                disabled=[key for key in rows[0] if key!='Approve'],
                column_config={'Approve':st.column_config.CheckboxColumn('Approve',default=False),'Request ID':None},
                key='visit_bulk_editor_'+str(st.session_state.get('visit_bulk_revision',0))+'_'+str(all_selected))
            count=sum(bool(row['Approve']) for row in selected)
            if st.button(f'Add selected visits to owner review ({count})',disabled=not count,key='visit_bulk_approve'):
                from owner_approvals import stage
                chosen=[dict(row) for row in selected if row['Approve']]
                def save_visits():
                    approved,errors=approve_selected(chosen)
                    if errors:raise ValueError('; '.join(errors))
                stage('visit_approvals',str(count)+' selected visit approval(s)',save_visits)
        else:
            st.info('No pending visit requests to approve.')
        with st.expander('All visit requests and booking status',expanded=not pending):
            if visits:
                st.dataframe([{'Customer':v['customer_name'],'Property':v['property_title'],'Visit time':v['visit_at'],'Status':v['status']} for v in visits],hide_index=True,use_container_width=True)
            else:
                st.info('No visit requests recorded.')
    except Exception:
        st.error('Could not load visit approvals. Please retry.')
