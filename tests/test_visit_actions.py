import unittest
from datetime import timedelta
import tests.test_visit_journey as fixtures
from visit_journey import record_response, run_visit_worker, set_advisor_status
from visit_actions import list_actions, sync_actions


class VisitActionsTests(unittest.TestCase):
    setUp=fixtures.VisitJourneyTests.setUp
    remind=fixtures.VisitJourneyTests.remind
    token=fixtures.VisitJourneyTests.token

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
