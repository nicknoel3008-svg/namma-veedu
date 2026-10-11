import unittest
from datetime import timedelta
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import tests.test_visit_journey as fixtures
from visit_attendance import create_register, record_agent_attendance
from visit_journey import record_response, run_visit_worker, owner_journeys


class ClarificationTests(unittest.TestCase):
    setUp=fixtures.VisitJourneyTests.setUp
    remind=fixtures.VisitJourneyTests.remind
    token=fixtures.VisitJourneyTests.token

    def conflict(self):
        self.remind()
        self.after=self.at+timedelta(hours=2)
        record_response(self.token(),action='feedback',attended='Yes',satisfied='Yes',purchase_intent='Interested',db_path=self.db,now=self.after)
        register=create_register(self.id,'Advisor',self.db)
        record_agent_attendance(register,self.id,'No',db_path=self.db,now=self.after)
        return register

    def test_conflict_email_once_and_customer_clarification(self):
        self.conflict()
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.after),(1,0))
        mail=self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertIn('clarify',mail['Subject'])
        self.assertIn('visit_action=clarify',mail.get_body(preferencelist=('plain',)).get_content())
        self.assertIn('Clarify my visit',mail.get_body(preferencelist=('html',)).get_content())
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.after),(0,0))
        with self.assertRaises(ValueError):
            record_response(self.token(),action='clarify',attended='Yes',reason='I visited',db_path=self.db,now=self.after)
        record_response(self.token(),action='clarify',attended='Yes',arrival_time='10:15 AM',met_person='Reception advisor',reason='I waited at reception',db_path=self.db,now=self.after)
        row=owner_journeys(self.db)[0]
        self.assertEqual(row['arrival_time'],'10:15 AM')
        self.assertEqual(row['agent_attended'],'No')
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.after),(0,0))
        record_response(self.token(),action='clarify',attended='No',reason='I visited a different site',db_path=self.db,now=self.after)
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.after),(1,0))
        self.assertEqual(owner_journeys(self.db)[0]['purchase_intent'],'Not visited')

    def test_pause_and_expiry_suppress_clarification(self):
        self.conflict()
        record_response(self.token(),action='pause',db_path=self.db,now=self.after)
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.after),(0,0))
        record_response(self.token(),action='resume',db_path=self.db,now=self.after)
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at+timedelta(days=8)),(0,0))

    def test_clarification_page_view_is_read_only_and_submission_saves(self):
        self.conflict()
        from visit_journey import response_context
        context=response_context(self.token(),self.db)
        context['visit_at']=self.after.isoformat()
        context['visit_at']=(self.after-timedelta(days=3)).isoformat()
        with patch('visit_journey_ui.response_context',return_value=context),patch('visit_journey_ui.record_response') as save:
            app=AppTest.from_string('from visit_journey_ui import render_visit_response\nrender_visit_response()')
            app.query_params.update(visit_response='private-test-token',visit_action='clarify')
            app.run()
            self.assertFalse(app.exception)
            save.assert_not_called()
            self.assertEqual(app.radio[0].value,'Clarify my visit')
            app.radio[1].set_value('Yes')
            next(w for w in app.text_input if w.label=='Approximate arrival time (IST)').set_value('10 AM')
            next(w for w in app.text_input if w.label.startswith('Whom did')).set_value('Site advisor')
            app.text_area[0].set_value('I came to reception')
            next(w for w in app.button if w.label=='Save response').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(save.call_args.kwargs['action'],'clarify')
            self.assertEqual(save.call_args.kwargs['arrival_time'],'10 AM')
