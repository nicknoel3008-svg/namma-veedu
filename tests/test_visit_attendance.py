from datetime import timedelta
import unittest
import tests.test_visit_journey as fixtures
from visit_attendance import create_register, register_context, record_agent_attendance, revoke_register, attendance_state
from visit_journey import record_response, run_visit_worker, owner_journeys


class DualAttendanceTests(unittest.TestCase):
    setUp=fixtures.VisitJourneyTests.setUp
    remind=fixtures.VisitJourneyTests.remind
    token=fixtures.VisitJourneyTests.token

    def test_advisor_ui_saves_independent_report(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        context=dict(advisor='Advisor',day=self.at.date().isoformat(),visits=[dict(id=self.id,customer_name='Customer',property_title='Plot',visit_at=self.at.isoformat(),agent_attended='',agent_note='',agent_recorded_at='')])
        with patch('visit_attendance.register_context',return_value=context),patch('visit_attendance.record_agent_attendance') as save:
            app=AppTest.from_string('from visit_attendance import render_register\nrender_register()')
            app.query_params['advisor_register']='private-test-token'
            app.run()
            self.assertFalse(app.exception)
            app.radio[0].set_value('Yes')
            next(b for b in app.button if b.label=='Save advisor attendance').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(save.call_args.args[:3],('private-test-token',self.id,'Yes'))
    def test_scoped_register_conflict_and_matching_decision(self):
        self.remind()
        token=create_register(self.id,'Site advisor',self.db)
        context=register_context(token,self.db)
        self.assertEqual(len(context['visits']),1)
        self.assertNotIn('contact_value',context['visits'][0])
        self.assertNotIn('token',context['visits'][0])
        after=self.at+timedelta(hours=2)
        record_response(self.token(),action='feedback',attended='Yes',satisfied='Yes',purchase_intent='Interested',db_path=self.db,now=after)
        self.assertEqual(run_visit_worker(self.config,self.db,now=after),(0,0))
        record_agent_attendance(token,self.id,'No',db_path=self.db,now=after)
        self.assertEqual(attendance_state(owner_journeys(self.db)[0]),'Attendance conflict')
        self.assertEqual(run_visit_worker(self.config,self.db,now=after),(1,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=after),(0,0))
        record_agent_attendance(token,self.id,'Yes','Corrected from site register',self.db,now=after)
        self.assertEqual(attendance_state(owner_journeys(self.db)[0]),'Visited')
        self.assertEqual(run_visit_worker(self.config,self.db,now=after),(1,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=after),(0,0))

    def test_scope_revocation_expiry_and_early_no_show(self):
        token=create_register(self.id,'Advisor',self.db)
        with self.assertRaises(ValueError):record_agent_attendance(token,'another-booking','Yes',db_path=self.db,now=self.at)
        with self.assertRaises(ValueError):record_agent_attendance(token,self.id,'Yes',db_path=self.db,now=self.at-timedelta(minutes=1))
        with self.assertRaises(ValueError):record_agent_attendance(token,self.id,'No',db_path=self.db,now=self.at+timedelta(minutes=30))
        self.assertIsNone(register_context(token,self.db,now=self.at+timedelta(days=9)))
        revoke_register(token,self.db)
        self.assertIsNone(register_context(token,self.db))
        with self.assertRaises(ValueError):record_agent_attendance(token,self.id,'Yes',db_path=self.db,now=self.at)

    def test_pause_preserves_booking_stops_emails_and_resume_requires_submission(self):
        self.remind()
        record_response(self.token(),action='pause',db_path=self.db,now=self.at-timedelta(minutes=30))
        self.assertEqual(owner_journeys(self.db)[0]['status'],'Confirmed')
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at+timedelta(hours=2)),(0,0))
        record_response(self.token(),action='resume',db_path=self.db,now=self.at+timedelta(hours=2))
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at+timedelta(hours=2)),(1,0))
