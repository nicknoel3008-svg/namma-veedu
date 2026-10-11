from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from crm_service import (create_lead,save_profile,list_leads,list_records,save_deal,save_task,
                         report,journey_summary,sync_visits,activities)
from crm_workspace import export_csv
from agent_runtime import INDIA_TZ


class CRMWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'crm.sqlite3'
        self.key=create_lead('Customer',email='test@example.com',phone='+919876543210',db_path=self.db)
        self.now=datetime.now(INDIA_TZ)

    def test_multiple_manual_customers_and_profile_conflict(self):
        create_lead('Second customer',db_path=self.db)
        self.assertEqual(len(list_leads(self.db)),2)
        save_profile(self.key,version=0,name='Updated',db_path=self.db)
        with self.assertRaises(ValueError): save_profile(self.key,version=0,name='Stale',db_path=self.db)
        self.assertTrue(any(a['kind']=='Profile updated' for a in activities(self.key,self.db)))

    def test_task_completion_and_stale_write(self):
        key=save_task(self.key,'Call customer',(self.now-timedelta(hours=1)).isoformat(),db_path=self.db)
        self.assertEqual(report([],[],list_records('tasks',self.db),self.now)['overdue_tasks'],1)
        save_task(self.key,'Call customer',self.now.isoformat(),status='Completed',record_id=key,version=0,db_path=self.db)
        self.assertEqual(report([],[],list_records('tasks',self.db),self.now)['overdue_tasks'],0)
        with self.assertRaises(ValueError):
            save_task(self.key,'Stale task',self.now.isoformat(),record_id=key,version=0,db_path=self.db)

    def test_deal_reports_and_lost_reason(self):
        save_deal(self.key,'Open plot',value_inr='1250000.50',db_path=self.db)
        key=save_deal(self.key,'Won flat',value_inr='2500000',stage='Won',db_path=self.db)
        save_deal(self.key,'Lost house',stage='Lost',loss_reason='Location',db_path=self.db)
        stats=report(list_leads(self.db),list_records('deals',self.db),[])
        self.assertEqual(stats['pipeline_inr'],Decimal('1250000.50'))
        self.assertEqual(stats['won_inr'],Decimal('2500000'))
        self.assertEqual(stats['win_rate'],50)
        for value in ('NaN','-1','Infinity','0.123'):
            with self.assertRaises(ValueError): save_deal(self.key,'Invalid',value_inr=value,db_path=self.db)
        with self.assertRaises(ValueError): save_deal(self.key,'Lost',stage='Lost',db_path=self.db)
        save_deal(self.key,'Won flat revised',stage='Won',record_id=key,version=0,db_path=self.db)
        with self.assertRaises(ValueError): save_deal(self.key,'Stale',record_id=key,version=0,db_path=self.db)

    def test_invalid_contact_and_orphan_task(self):
        with self.assertRaises(ValueError): create_lead('Customer',email='invalid',db_path=self.db)
        with self.assertRaises(ValueError): save_task('missing','Task',self.now.isoformat(),db_path=self.db)

    def test_attendance_and_readiness_from_customer_evidence(self):
        visit=dict(visit_id='v',property_title='Plot',visit_at=(self.now-timedelta(hours=3)).isoformat(timespec='minutes'),status='Confirmed',attendance='Yes',conversation_id='visit-only',customer_name='Visitor')
        summary=journey_summary(visit,now=self.now)
        self.assertEqual(summary['Attendance'],'Awaiting response')
        self.assertEqual(summary['Readiness'],'Insufficient evidence')
        visit.update(attended='Yes',satisfied='Yes',purchase_intent='Interested')
        self.assertEqual(journey_summary(visit,now=self.now)['Readiness'],'High interest')
        visit.update(purchase_intent='Not interested',reason='Too far',explore_consent='Yes')
        summary=journey_summary(visit,now=self.now)
        self.assertEqual(summary['Readiness'],'Declined this property')
        self.assertEqual(summary['Next step'],'Assist with revised preferences')
        sync_visits([visit,visit],self.db)
        self.assertEqual(len(list_leads(self.db)),2)

    def test_csv_formula_injection(self):
        data=export_csv([{'name':'=HYPERLINK("bad")','phone':'+919876543210'}])
        self.assertIn("'=HYPERLINK",data)
        self.assertIn("'+919876543210",data)

    def test_customer_feedback_reaches_crm_without_reentry(self):
        from visit_service import request_visit,update_visit_status
        from visit_journey import owner_journeys,record_response
        from followup_service import _connect
        at=(self.now+timedelta(days=1)).replace(second=0,microsecond=0)
        key=request_visit(record={'property_id':'p','title':'Customer plot'},user_id='user',
                          visit_at=at,slot_kind='Custom time',customer_name='Visitor',contact_method='Email',
                          contact_value='test@example.com',consent=True,conversation_id='customer-journey',db_path=self.db)
        update_visit_status(key,'Confirmed',db_path=self.db)
        with _connect(self.db) as c:
            token=c.execute('SELECT token FROM visit_journeys WHERE visit_id=?',(key,)).fetchone()['token']
        record_response(token,action='feedback',attended='Yes',satisfied='No',purchase_intent='Not interested',
                        reason='Need a smaller property',explore_consent=True,revised_preferences='Smaller plot near school',
                        now=at+timedelta(hours=3),db_path=self.db)
        journeys=owner_journeys(self.db)
        sync_visits(journeys,self.db)
        lead=next(r for r in list_leads(self.db) if r['conversation_id']=='customer-journey')
        summary=journey_summary(next(r for r in journeys if r['conversation_id']==lead['conversation_id']),now=at+timedelta(hours=3))
        self.assertEqual(summary['Attendance'],'Visited')
        self.assertEqual(summary['Reason'],'Need a smaller property')
        self.assertEqual(summary['Revised preferences'],'Smaller plot near school')
        self.assertEqual(summary['Next step'],'Assist with revised preferences')
