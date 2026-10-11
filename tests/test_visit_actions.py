import unittest
from datetime import timedelta
import tests.test_visit_journey as fixtures
from visit_journey import record_response, run_visit_worker, set_advisor_status
from visit_actions import list_actions, sync_actions


class VisitActionsTests(unittest.TestCase):
    setUp=fixtures.VisitJourneyTests.setUp
    remind=fixtures.VisitJourneyTests.remind
    token=fixtures.VisitJourneyTests.token

    def test_assistance_form_collects_question_and_callback_preference(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        self.remind()
        from visit_journey import response_context
        context=response_context(self.token(),self.db)
        with patch('visit_journey_ui.response_context',return_value=context),patch('visit_journey_ui.record_response') as save:
            app=AppTest.from_string('from visit_journey_ui import render_visit_response\nrender_visit_response()')
            app.query_params.update(visit_response='private-test-token',visit_action='help')
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio[0].value,'Request assistance')
            next(w for w in app.text_area if w.label=='What assistance do you need?').set_value('Need floor plan')
            next(w for w in app.text_input if w.label.startswith('Preferred callback')).set_value('Tomorrow 5 PM IST')
            next(w for w in app.checkbox if w.label.startswith('I permit sharing')).check()
            next(w for w in app.button if w.label=='Save response').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(save.call_args.kwargs['action'],'help')
            self.assertEqual(save.call_args.kwargs['callback_preference'],'Tomorrow 5 PM IST')

    def help(self):
        record_response(self.token(),action='help',assistance='Property agent',details='Need floor plan',advisor_consent=True,callback_preference='Tomorrow evening IST',db_path=self.db,now=self.at-timedelta(hours=2))

    def test_assistance_acknowledgment_tasks_dedup_escalation_and_close(self):
        self.remind();self.help()
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(minutes=20)),(1,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(minutes=20)),(0,0))
        tasks=list_actions(self.db)
        self.assertEqual(len(tasks),1)
        self.assertEqual(tasks[0]['kind'],'assistance')
        self.assertEqual(tasks[0]['status'],'Open')
        sync_actions(self.db,now=self.at+timedelta(days=2))
        task=next(r for r in list_actions(self.db) if r['kind']=='assistance')
        self.assertEqual(task['priority'],'High')
        set_advisor_status(self.id,'Closed',self.db)
        sync_actions(self.db,now=self.at+timedelta(days=2))
        self.assertEqual(next(r for r in list_actions(self.db) if r['kind']=='assistance')['status'],'Completed')
        self.help()
        sync_actions(self.db,now=self.at+timedelta(days=2))
        self.assertEqual(next(r for r in list_actions(self.db) if r['kind']=='assistance')['status'],'Open')

    def test_missing_reports_get_one_neutral_email_and_internal_tasks(self):
        self.remind()
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at+timedelta(days=1)),(1,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at+timedelta(days=1)),(0,0))
        self.assertEqual({r['kind'] for r in list_actions(self.db)},{'missing_customer','missing_advisor'})
        mail=self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertIn('Silence will not be treated',mail.get_body(preferencelist=('plain',)).get_content())

    def test_help_requires_consent_and_pause_suppresses_email(self):
        self.remind()
        with self.assertRaises(ValueError):record_response(self.token(),action='help',assistance='Property agent',details='Question',db_path=self.db)
        self.help()
        record_response(self.token(),action='pause',db_path=self.db)
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(minutes=20)),(0,0))
        self.assertEqual(len(list_actions(self.db)),1)
