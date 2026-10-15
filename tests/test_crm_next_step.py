import unittest
from datetime import datetime
from agent_runtime import INDIA_TZ
from crm_service import journey_summary

class NextStepTests(unittest.TestCase):
    def visit(self):
        return dict(visit_id='v',customer_name='Customer',property_title='Property',visit_at='2026-10-13T15:00+05:30',status='Confirmed',attended='Yes',agent_attended='Yes',satisfied='Yes',purchase_intent='Interested',advisor_consent='Yes',advisor_status='Requested',explore_consent='Yes')
    def test_assistance_takes_priority_over_alternatives(self):
        self.assertEqual(journey_summary(self.visit(),now=datetime(2026,10,15,tzinfo=INDIA_TZ))['Next step'],'Follow up on requested assistance')
    def test_reschedule_keeps_booking_review_first(self):
        visit=self.visit();visit['status']='Requested'
        self.assertEqual(journey_summary(visit)['Next step'],'Review requested new slot')

