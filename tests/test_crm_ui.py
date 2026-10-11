import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


class CRMUITests(unittest.TestCase):
    def test_manual_customer_workspace_and_task_creation(self):
        lead=dict(id='manual1',conversation_id=None,customer_name='Manual customer',location='Chennai',property_type='Flat',budget='50 lakh',stage='New',priority='Normal',assigned_to='',next_action='',due_at='',version=0,email='',phone='',source='Manual')
        script="""
import streamlit as st
st.session_state.owner_dashboard_authenticated=True
st.session_state.crm_loaded=True
st.session_state.crm_workspace_loaded=True
from crm_ui import render
render()
"""
        with patch('crm_ui.list_leads',return_value=[lead]),patch('crm_ui.activities',return_value=[]),patch('visit_journey.owner_journeys',return_value=[]),patch('crm_workspace.list_records',return_value=[]),patch('crm_workspace.save_task') as save:
            app=AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            next(w for w in app.text_input if w.label=='Task title').set_value('Check customer feedback')
            next(w for w in app.button if w.label=='Save advisor task').click()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(save.call_args.args[1],'Check customer feedback')

    def test_authenticated_lead_edit(self):
        lead=dict(id='lead1',conversation_id='conversation1',customer_name='Test customer',location='Chennai',property_type='Flat',budget='50 lakh',stage='New',priority='Normal',assigned_to='',next_action='',due_at='',version=0)
        script="""
import streamlit as st
st.session_state.owner_dashboard_authenticated=True
st.session_state.crm_loaded=True
from crm_ui import render
render()
"""
        with patch('crm_ui.list_leads',return_value=[lead]), patch('crm_ui.activities',return_value=[]), patch('visit_journey.owner_journeys',return_value=[]), patch('crm_ui.save_lead') as save:
            app=AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            stage=next(w for w in app.selectbox if w.label=='Lead stage')
            stage.select('Qualified')
            next(w for w in app.button if w.label=='Save lead').click()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(save.call_args.kwargs['stage'],'Qualified')

    def test_unauthenticated_view_does_not_load_records(self):
        with patch('crm_ui.list_leads') as records:
            app=AppTest.from_string('from crm_ui import render\nrender()').run()
            self.assertFalse(app.exception)
            records.assert_not_called()
