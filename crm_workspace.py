"""Customer profiles, deals, advisor tasks and exports for authenticated Studio."""
from datetime import datetime
import csv
import io
import pandas as pd
import streamlit as st
from functools import partial
from owner_approvals import stage as queue_change
from agent_runtime import INDIA_TZ
from crm_service import (create_lead,save_profile,list_records,save_task,save_deal,
                         DEAL_STAGES,TASK_STATUSES,PRIORITIES,report)


def export_csv(rows):
    if not rows: return ''
    out=io.StringIO(); writer=csv.DictWriter(out,fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        safe={k: ('\''+str(v) if str(v).lstrip().startswith(('=','+','-','@')) else v) for k,v in row.items()}
        writer.writerow(safe)
    return out.getvalue()


def create_customer():
    with st.expander('Add customer manually'):
        with st.form('crm_new_customer',clear_on_submit=True):
            name=st.text_input('Customer name')
            email=st.text_input('Customer email')
            phone=st.text_input('Phone with country code')
            location=st.text_input('Preferred location')
            budget=st.text_input('Stated budget')
            source=st.text_input('Lead source',value='Manual')
            submit=st.form_submit_button('Add to owner review - Create customer')
        if submit:
            try:
                queue_change('new_customer:'+email+':'+name,'New customer: '+name,partial(create_lead,name,email=email,phone=phone,location=location,budget=budget,source=source,actor=str(st.session_state.get('mira_studio_identity') or 'Owner')))
            except ValueError as error: st.error(str(error))


def render_workspace(lead,leads,actor):
    deals=list_records('deals'); tasks=list_records('tasks')
    stats=report(leads,deals,tasks)
    profile,deal_tab,task_tab,reports=st.tabs(['Customer profile','Property deals','Advisor tasks','Reports and exports'])
    with profile:
        st.caption('Contact details are entered by the team. Saving a contact does not authorize email or WhatsApp messages.')
        with st.form('crm_profile_'+lead['id']+'_'+str(lead['version'])):
            name=st.text_input('Profile name',value=lead['customer_name'])
            email=st.text_input('Profile email',value=lead.get('email',''))
            phone=st.text_input('Profile phone',value=lead.get('phone',''))
            location=st.text_input('Location preference',value=lead['location'])
            kind=st.text_input('Property preference',value=lead['property_type'])
            budget=st.text_input('Customer budget',value=lead['budget'])
            source=st.text_input('Profile source',value=lead.get('source',''))
            save=st.form_submit_button('Add to owner review - Save customer profile')
        if save:
            try:
                queue_change('profile:'+lead['id'],'Customer profile: '+name,partial(save_profile,lead['id'],version=lead['version'],name=name,email=email,phone=phone,location=location,property_type=kind,budget=budget,source=source,actor=actor))
            except ValueError as error: st.error(str(error))
    with deal_tab:
        linked=[r for r in deals if r['lead_id']==lead['id']]
        st.dataframe(pd.DataFrame(linked),hide_index=True)
        selected=st.selectbox('Deal to edit',['New deal']+[r['id'] for r in linked],format_func=lambda k: next((r['title'] for r in linked if r['id']==k),k))
        current=next((r for r in linked if r['id']==selected),{})
        with st.form('crm_deal_'+lead['id']+'_'+selected+'_'+str(current.get('version',0))):
            title=st.text_input('Deal title',value=current.get('title',''))
            reference=st.text_input('Property reference or source link',value=current.get('property_reference',''))
            value=st.text_input('Deal value (INR)',value=current.get('value_inr','0'))
            stage=st.selectbox('Deal stage',DEAL_STAGES,index=DEAL_STAGES.index(current.get('stage','Discovery')))
            advisor=st.text_input('Deal advisor',value=current.get('assigned_to',lead['assigned_to']))
            close=st.text_input('Expected close date (YYYY-MM-DD, optional)',value=current.get('expected_close',''))
            reason=st.text_area('Reason if lost',value=current.get('loss_reason',''))
            save=st.form_submit_button('Add to owner review - Save property deal')
        if save:
            try:
                queue_change('deal:'+lead['id']+':'+selected,'Property deal: '+title,partial(save_deal,lead['id'],title,property_reference=reference,value_inr=value,stage=stage,assigned_to=advisor,expected_close=close,loss_reason=reason,record_id=current.get('id'),version=current.get('version',0),actor=actor))
            except ValueError as error: st.error(str(error))
        st.caption('Won is a team-recorded sales stage. Record purchase verification separately in visit management.')
    with task_tab:
        linked=[r for r in tasks if r['lead_id']==lead['id']]
        st.dataframe(pd.DataFrame(linked),hide_index=True)
        selected=st.selectbox('Task to edit',['New task']+[r['id'] for r in linked],format_func=lambda k: next((r['title'] for r in linked if r['id']==k),k))
        current=next((r for r in linked if r['id']==selected),{})
        when=datetime.fromisoformat(current['due_at']) if current else datetime.now(INDIA_TZ)
        with st.form('crm_task_'+lead['id']+'_'+selected+'_'+str(current.get('version',0))):
            title=st.text_input('Task title',value=current.get('title',''))
            advisor=st.text_input('Task advisor',value=current.get('assigned_to',lead['assigned_to']))
            day=st.date_input('Task date (IST)',value=when.date())
            clock=st.time_input('Task time (IST)',value=when.time().replace(tzinfo=None))
            status=st.selectbox('Task status',TASK_STATUSES,index=TASK_STATUSES.index(current.get('status','Open')))
            priority=st.selectbox('Task priority',PRIORITIES,index=PRIORITIES.index(current.get('priority','Normal')))
            save=st.form_submit_button('Add to owner review - Save advisor task')
        if save:
            try:
                queue_change('task:'+lead['id']+':'+selected,'Advisor task: '+title,partial(save_task,lead['id'],title,datetime.combine(day,clock,tzinfo=INDIA_TZ).isoformat(),assigned_to=advisor,status=status,priority=priority,record_id=current.get('id'),version=current.get('version',0),actor=actor))
            except ValueError as error: st.error(str(error))
        st.caption('Tasks are internal work reminders; they do not send customer messages.')
    with reports:
        cols=st.columns(3)
        cols[0].metric('Open property deals',stats['open_deals'])
        cols[1].metric('Pipeline value (INR)',f"{stats['pipeline_inr']:,.2f}")
        cols[2].metric('Overdue advisor tasks',stats['overdue_tasks'])
        st.write(f"Team-recorded won value: INR {stats['won_inr']:,.2f}")
        st.write('Closed-deal win rate: '+(f"{stats['win_rate']:.1f}%" if stats['win_rate'] is not None else 'No closed deals'))
        st.caption('Win rate = Won / (Won + Lost). Open deals are excluded. This is a sales report, not a customer purchase probability.')
        st.bar_chart(pd.DataFrame({'Stage':DEAL_STAGES,'Deals':[sum(d['stage']==s for d in deals) for s in DEAL_STAGES]}).set_index('Stage'))
        due=[r for r in tasks if r['status'] not in ('Completed','Cancelled') and datetime.fromisoformat(r['due_at'])<=datetime.now(INDIA_TZ)]
        st.write('Team tasks due'); st.dataframe(pd.DataFrame(due),hide_index=True)
        for label,rows in [('Leads',leads),('Deals',deals),('Tasks',tasks)]:
            st.download_button('Export '+label,export_csv(rows),file_name='namma_veedu_crm_'+label.lower()+'.csv',mime='text/csv',key='crm_export_'+label)
