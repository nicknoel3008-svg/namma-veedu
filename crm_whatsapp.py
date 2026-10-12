"""No API sending: prepare official click-to-chat links for manual review."""
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit
from agent_runtime import INDIA_TZ
from whatsapp_followup import normalize_phone


def chat_link(phone, message):
    phone=normalize_phone(phone)
    if not message.strip():
        raise ValueError('Enter a message.')
    return 'https://wa.me/'+phone[1:]+'?'+urlencode({'text':message})


def visit_message(visit, kind, *, now=None, response_url=''):
    now=now or datetime.now(INDIA_TZ)
    at=datetime.fromisoformat(visit['visit_at'])
    if visit['status']!='Confirmed' or visit.get('customer_purchase_confirmed_at'):
        raise ValueError('This visit is not eligible for a visit message.')
    if kind not in ('confirmation','reminder','feedback'):
        raise ValueError('Choose a supported visit message.')
    if kind in ('confirmation','reminder') and now>=at:
        raise ValueError('The visit time has passed.')
    if kind=='feedback' and now<at:
        raise ValueError('Ask for feedback after the visit.')
    name=visit.get('customer_name') or 'there'
    title=visit['property_title']
    when=at.strftime('%d %b %Y, %I:%M %p IST')
    text=f"Hello {name}, this is Namma Veedu. "
    if kind=='confirmation':
        text+=f"Your property visit for {title} is confirmed for {when}. Please confirm whether you can attend, or let us know if you need to cancel or request another time."
    elif kind=='reminder':
        text+=f"A reminder about your property visit for {title} at {when}. Will you be attending? Please let us know if you need to cancel or request another time."
    else:
        from visit_attendance import attendance_state
        verified=attendance_state(visit)
        if verified=='Attendance conflict': raise ValueError('Customer and advisor attendance disagree. Resolve the record before preparing an outcome follow-up.')
        if visit.get('followup_paused')=='Yes': raise ValueError('This customer paused visit follow-ups.')
        if verified=='Did not visit':
            text+=f"We understand you could not attend your visit for {title} at {when}. Were there any concerns? Would you like to request another time, explore more properties, or pause your search?"
        elif verified=='Visited' and visit.get('purchase_intent')=='Interested':
            text+=f"Thank you for visiting {title} and sharing your interest. Do you need further property or loan assistance? Please update your request on the response page."
        elif verified=='Visited':
            text+=f"Thank you for visiting {title}. Did it match your preferences? Please share your decision and any reason it was unsuitable. Would you like assistance or other options?"
        else:
            text+=f"Did you attend your visit for {title}, scheduled for {when}? Did it meet your preferences, and are you interested in purchasing? If yes, do you need any further assistance? If not, please share your reason and whether you would like assistance or to explore other properties."
    if response_url:
        text+='\nRespond securely here: '+response_url
    else:
        text+='\nPlease reply here; our team will review your response.'
    return text+'\nIf you do not want further WhatsApp messages, please let us know.'


def reminder_due(visit, now=None):
    if visit.get('followup_email') and visit.get('manual_whatsapp_confirmation_consent')=='Yes':
        return False  # This booking uses the automatic email reminder.
    now=now or datetime.now(INDIA_TZ)
    at=datetime.fromisoformat(visit['visit_at'])
    return (visit['status']=='Confirmed' and not visit.get('customer_purchase_confirmed_at')
            and at-timedelta(hours=1)<=now<at and visit.get('attendance')!='No')


def response_link(visit,public_url,db_path=None):
    """Read an existing private response token; never create a booking or token."""
    from followup_service import _connect,FOLLOWUP_DB
    parsed=urlsplit(public_url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.hostname in ('localhost','127.0.0.1','::1') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ''
    with _connect(db_path or FOLLOWUP_DB) as c:
        row=c.execute('SELECT token FROM visit_journeys WHERE visit_id=? AND visit_at=?',(visit['visit_id'],visit['visit_at'])).fetchone()
    return public_url.rstrip('/')+'/?'+urlencode({'visit_response':row['token']}) if row else ''


def recipient_number(lead, visits, visit=None):
    """Reuse this customer's saved number; never infer it from another customer."""
    if visit and visit.get('contact_method') == 'WhatsApp' and visit.get('contact_value'):
        return visit['contact_value']
    if lead.get('phone'):
        return lead['phone']
    for saved in sorted(visits, key=lambda v: v.get('visit_at', ''), reverse=True):
        if saved.get('contact_method') == 'WhatsApp' and saved.get('contact_value'):
            return saved['contact_value']
    return ''


def approval_rows(visits, leads, journeys):
    """Display saved contacts and mail state beside the owner's decision."""
    profiles={r.get('conversation_id'):r for r in leads if r.get('conversation_id')}
    states={r['visit_id']:r for r in journeys}
    rows=[]
    for visit in visits:
        lead=profiles.get(visit.get('conversation_id') or 'visit:'+visit['id'],{})
        linked=[r for r in visits if r['user_id']==visit['user_id']]
        phone=recipient_number(lead,linked,visit)
        row=dict(visit)
        row['WhatsApp number']=phone or 'Not provided — ask customer'
        row['Confirmation email']=states.get(visit['id'],{}).get('confirmation email','Not sent')
        row['Email recipient']=visit.get('followup_email') or (visit['contact_value'] if visit['contact_method']=='Email' else '')
        rows.append(row)
    return rows


def render(lead,visits,actor):
    import streamlit as st
    from crm_service import add_note
    now=datetime.now(INDIA_TZ)
    st.caption('No paid messaging API. Review the draft, open WhatsApp, then press Send yourself. Opening WhatsApp does not prove sending or delivery.')
    visit=None
    options=['General follow-up']+[v['visit_id'] for v in visits if v['status']=='Confirmed' and not v.get('customer_purchase_confirmed_at')]
    choice=st.selectbox('WhatsApp message context',options,format_func=lambda k: next((v['property_title']+' · '+v['visit_at'] for v in visits if v['visit_id']==k),k),key='crm_wa_context_'+lead['id'])
    visit=next((v for v in visits if v['visit_id']==choice),None)
    suffix=lead['id']+'_'+choice
    phone=st.text_input('Recipient WhatsApp number (+country code)',value=recipient_number(lead, visits, visit),key='crm_wa_phone_'+suffix)
    st.caption('Filled automatically from this customer’s saved WhatsApp visit number or CRM phone. If neither is saved, ask the customer for their number.')
    if visit:
        at=datetime.fromisoformat(visit['visit_at'])
        mixed=bool(visit.get('followup_email') and visit.get('manual_whatsapp_confirmation_consent')=='Yes')
        kinds=(['confirmation'] if mixed else ['confirmation','reminder']) if now<at else ['feedback']
        if mixed and now>=at:
            st.info('Email handles the follow-up. An optional WhatsApp draft requires separate customer permission below.')
        kind=st.selectbox('Message type',kinds,key='crm_wa_kind_'+suffix)
        if mixed:
            st.info('Send this confirmation manually. The scheduled email worker handles the one-hour reminder and later follow-ups independently.')
        elif reminder_due(visit,now):
            st.warning('Visit reminder is due now. Open WhatsApp and send it manually.')
        elif now<at:
            st.info('Reminder due: '+(at-timedelta(hours=1)).strftime('%d %b %Y, %I:%M %p IST')+'. Refresh this CRM near the due time; it does not run in the background.')
        from run_followup_worker import load_config
        url=response_link(visit,load_config().get('FOLLOWUP_PUBLIC_URL',''))
        try: draft=visit_message(visit,kind,now=now,response_url=url)
        except ValueError as error:
            st.info(str(error));return
        if mixed:
            draft+='\nYour visit reminders and follow-up questions will arrive by email.'
        if not url:
            st.caption('A public response link is not configured. Replies must be reviewed manually; they do not update Mira automatically.')
        else:
            st.caption('Responses submitted through the private link update visit records and Mira Studio. Ordinary WhatsApp replies need manual review.')
    else:
        kind='follow-up'
        draft=f"Hello {lead['customer_name']}, this is Namma Veedu. Are you still looking for {lead.get('property_type') or 'a property'}{(' in '+lead['location']) if lead.get('location') else ''}? Please share any changes to your preferences or let us know if you need assistance. If you do not want further WhatsApp follow-ups, please let us know."
    draft_key=suffix+'_'+kind
    message=st.text_area('Review WhatsApp message',value=draft,key='crm_wa_draft_'+draft_key,height=200)
    consent=st.checkbox('I have verified this number belongs to the customer and they agreed to these WhatsApp messages.',key='crm_wa_consent_'+draft_key)
    try: url=chat_link(phone,message) if consent else None
    except ValueError as error:
        st.error(str(error)); url=None
    if url:
        st.link_button('1. Open customer chat in WhatsApp',url)
        st.info('2. In WhatsApp, check the customer and message, then press Send. Return here afterward to save your send record.')
    else: st.info('Enter the customer number and confirm permission to enable WhatsApp.')
    sent=st.checkbox('I personally pressed Send in WhatsApp for this message.',key='crm_wa_sent_'+draft_key)
    st.caption('The button below only updates the CRM after you send in WhatsApp. It does not send a message.')
    if st.button('3. Save WhatsApp send record',disabled=not(consent and sent and url),key='crm_wa_record_'+draft_key):
        add_note(lead['id'],f'WhatsApp {kind} manually marked sent by advisor. Context: {choice}. Visit time: {visit["visit_at"] if visit else "Not applicable"}. Recipient: {normalize_phone(phone)}. Delivery and receipt unverified.',actor=actor)
        st.success('Saved in CRM: you marked this WhatsApp message as manually sent. Check WhatsApp for delivery ticks; this website cannot verify delivery.')
