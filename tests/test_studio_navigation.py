import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from studio_navigation import SECTIONS

class NavigationTests(unittest.TestCase):
    def test_search_topics_and_customer_shortcut(self):
        app=AppTest.from_string('from studio_navigation import choose_topic\nimport streamlit as st\nst.write(choose_topic())').run()
        app.text_input[0].set_value('whatsapp').run()
        self.assertEqual(app.selectbox[0].value,'WhatsApp confirmations')
        app.text_input[0].set_value('email status').run()
        self.assertEqual(app.selectbox[0].value,'Visit records and email status')
        app.text_input[0].set_value('Joseph').run()
        app.button[1].click().run()
        self.assertEqual(app.session_state['crm_search'],'Joseph')
        self.assertIn('Customer CRM',app.markdown[-1].value)
        self.assertFalse(app.exception)

    def test_sections_and_topics(self):
        app=AppTest.from_string('from studio_navigation import choose_topic\nimport streamlit as st\nst.write(choose_topic())').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[2].value,'Overview and reports')
        for section,topics in SECTIONS.items():
            app.selectbox[1].select(section).run()
            self.assertEqual(app.selectbox[2].options,topics)
            self.assertFalse(app.exception)

    def test_all_topics_available_in_search_dropdown(self):
        app=AppTest.from_string('from studio_navigation import choose_topic\nimport streamlit as st\nst.write(choose_topic())').run()
        self.assertEqual(set(app.selectbox[0].options),{topic for topics in SECTIONS.values() for topic in topics})
        app.selectbox[0].select('Property advisor setup').run()
        self.assertIn('Property advisor setup',app.markdown[-1].value)
        self.assertFalse(app.exception)

    def test_approval_shortcut(self):
        with patch('visit_approval_ui.render') as render:
            app=AppTest.from_string("from studio_navigation import render_shortcut\nrender_shortcut('Approve a visit')").run()
            self.assertFalse(app.exception)
            render.assert_called_once()

    def test_dashboard_shortcut_clears_topic_search(self):
        app=AppTest.from_string('from studio_navigation import choose_topic\nimport streamlit as st\nst.write(choose_topic())').run()
        app.text_input[0].set_value('whatsapp').run()
        app.button[0].click().run()
        self.assertEqual(app.text_input[0].value,'')
        self.assertIn('Overview and reports',app.markdown[-1].value)
        self.assertFalse(app.exception)
