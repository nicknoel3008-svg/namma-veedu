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
        app.button[0].click().run()
        self.assertEqual(app.session_state['crm_search'],'Joseph')
        self.assertIn('Customer CRM',app.markdown[-1].value)
        self.assertFalse(app.exception)

    def test_sections_and_topics(self):
        app=AppTest.from_string('from studio_navigation import choose_topic\nimport streamlit as st\nst.write(choose_topic())').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[1].value,'Approve a visit')
        for section,topics in SECTIONS.items():
            app.selectbox[0].select(section).run()
            self.assertEqual(app.selectbox[1].options,topics)
            self.assertFalse(app.exception)

    def test_approval_shortcut(self):
        with patch('visit_approval_ui.render') as render:
            app=AppTest.from_string("from studio_navigation import render_shortcut\nrender_shortcut('Approve a visit')").run()
            self.assertFalse(app.exception)
            render.assert_called_once()
