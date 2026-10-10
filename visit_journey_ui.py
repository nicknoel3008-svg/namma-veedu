"""Public response form; viewing the link never changes a visit."""
from datetime import datetime, timedelta
import streamlit as st
from agent_runtime import INDIA_TZ
from visit_journey import response_context, record_response


def render_visit_response():
    token = str(st.query_params.get('visit_response','') or '')
    if not token:
        return
    st.title('Namma Veedu · Your property visit')
    try:
        context = response_context(token)
        if not context:
            st.info('This visit link is invalid, expired or replaced by a newer booking.')
            st.stop()
        st.subheader(context['property_title'])
        st.write('Visit time: '+datetime.fromisoformat(context['visit_at']).strftime('%d %b %Y, %I:%M %p IST'))
        st.write('Booking status: '+context['status'])
        if context['status'] != 'Confirmed':
            st.info('Please contact the owner about this request. Rescheduled times need owner confirmation.')
            st.stop()
        past = datetime.now(INDIA_TZ)>=datetime.fromisoformat(context['visit_at'])
        choices = ['Visit feedback','I purchased this property','Reschedule','Explore other properties','Cancel visit'] if past else ['Yes, I will attend','I purchased this property','No, I cannot attend','Reschedule','Explore other properties']
        choice=st.radio('How can we help?',choices)
        with st.form('visit_response_form'):
            reason=st.text_area('Reason or visit comments (no financial account details)')
            when=None;attended='';satisfied='';assistance='None';details='';consent=False;explore=False;intent='Undecided';changes=''
            purchase_confirmed=False;receipt_consent=False
            if choice=='I purchased this property':
                purchase_confirmed=st.checkbox('I confirm that I completed the purchase of this property.')
                receipt_consent=st.checkbox('Email me a thank-you message and optional final-rating link.',disabled=context['contact_method']!='Email')
                st.caption('This records your reported purchase for owner review and stops visit reminders for this property. Do not enter payment or identity document details.')
            if choice=='Reschedule':
                day=st.date_input('New visit date',value=datetime.now(INDIA_TZ).date()+timedelta(days=1),min_value=datetime.now(INDIA_TZ).date())
                time=st.time_input('Requested time (IST)',value=datetime.strptime('10:00','%H:%M').time())
                when=datetime.combine(day,time,tzinfo=INDIA_TZ)
                st.caption('This requests a new time. The owner must confirm availability.')
            if choice=='Visit feedback':
                attended=st.radio('Did you attend the visit?',['Yes','No'])
                satisfied=st.radio('Did the property satisfy your preferences?',['Yes','Partly','No','Not visited'])
                intent=st.radio('Are you interested in purchasing this property?',['Undecided','Interested','Not interested','Not visited'])
                assistance=st.selectbox('Do you need further assistance?',['None','Property agent','Loan advisor','Both'])
                details=st.text_area('What assistance do you need?')
                consent=st.checkbox('I permit sharing my visit details, contact and assistance request with the relevant property agent or loan advisor.')
                st.caption('This saves a callback request for the owner. It does not automatically connect or contact an advisor.')
            if choice=='Explore other properties':
                explore=st.checkbox('I would like to return to Mira to explore other properties.')
            if choice in ('Visit feedback','Explore other properties'):
                changes=st.text_area('What should Mira change in your next search?')
                if choice=='Visit feedback':
                    explore=st.checkbox('I would like Mira to help me explore other properties using my saved preferences and these changes.')
            submitted=st.form_submit_button('Save response')
        if submitted:
            if choice=='I purchased this property':
                from purchase_confirmation import confirm_purchase
                st.success(confirm_purchase(context['visit_id'],token=token,confirmed=purchase_confirmed,note=reason,email_receipt=receipt_consent))
                st.stop()
            action={'Yes, I will attend':'yes','No, I cannot attend':'no','Cancel visit':'no','Reschedule':'reschedule','Explore other properties':'explore','Visit feedback':'feedback'}[choice]
            reply=record_response(token,action=action,reason=reason,visit_at=when,attended=attended,satisfied=satisfied,assistance=assistance,details=details,advisor_consent=consent,explore_consent=explore,purchase_intent=intent,revised_preferences=changes)
            st.success(reply)
            if explore:
                st.link_button('Return to Mira', '/?resume_visit='+token)
        st.caption('Keep this private response link to yourself. No response does not cancel your visit.')
    except ValueError as error:
        st.error(str(error))
    except Exception:
        st.error('Your visit response could not be loaded or saved. Please contact the owner or try again.')
    st.stop()


def render_purchase_rating():
    token=str(st.query_params.get('purchase_rating','') or '')
    if not token:return
    from purchase_confirmation import rating_context,save_rating
    st.title('Namma Veedu · Your experience')
    try:
        context=rating_context(token)
        if not context:
            st.info('This private rating link is invalid or expired.');st.stop()
        st.write(context['property_title'])
        with st.form('final_purchase_rating'):
            rating=st.radio('How would you rate your overall experience with Mira?',[1,2,3,4,5],index=None)
            if st.form_submit_button('Save final rating'):
                save_rating(token,rating);st.success('Thank you! Your final rating is saved.')
    except ValueError as error:st.error(str(error))
    except Exception:st.error('Could not load or save the rating. Please try again.')
    st.stop()
