import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from crm_service import sync_inquiries, list_leads, save_lead, add_note, activities


class CRMTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'crm.sqlite3'
        self.rows=[{'Conversation ID':'c1','Inquiry ID':'i1','Customer name':'Customer','Location mentioned':'Chennai','Timestamp (Asia/Kolkata)':'2026-10-11T10:00:00+05:30'}]

    def test_sync_deduplicates_and_preserves_workflow(self):
        self.assertEqual(sync_inquiries(self.rows,self.db),1)
        lead=list_leads(self.db)[0]
        save_lead(lead['id'],version=0,stage='Qualified',priority='High',assigned_to='Advisor',db_path=self.db)
        self.assertEqual(sync_inquiries(self.rows*2,self.db),0)
        self.assertEqual(list_leads(self.db)[0]['stage'],'Qualified')
        self.assertEqual(len(activities(lead['id'],self.db)),1)

    def test_concurrent_edit_does_not_overwrite(self):
        sync_inquiries(self.rows,self.db); lead=list_leads(self.db)[0]
        save_lead(lead['id'],version=0,stage='Contacted',priority='Normal',db_path=self.db)
        with self.assertRaises(ValueError):
            save_lead(lead['id'],version=0,stage='Closed lost',priority='Normal',db_path=self.db)
        self.assertEqual(list_leads(self.db)[0]['stage'],'Contacted')

    def test_notes_and_due_validation(self):
        sync_inquiries(self.rows,self.db); lead=list_leads(self.db)[0]
        add_note(lead['id'],'Call customer tomorrow',db_path=self.db)
        self.assertEqual(activities(lead['id'],self.db)[0]['detail'],'Call customer tomorrow')
        with self.assertRaises(ValueError):
            save_lead(lead['id'],version=0,stage='New',priority='Normal',due_at='2026-10-12T10:00',db_path=self.db)
        with self.assertRaises(ValueError):
            add_note(lead['id'],' ',db_path=self.db)

    def test_invalid_stage_and_missing_identity(self):
        self.assertEqual(sync_inquiries([{'Inquiry ID':'alone'}],self.db),0)
        sync_inquiries(self.rows,self.db); lead=list_leads(self.db)[0]
        with self.assertRaises(ValueError):
            save_lead(lead['id'],version=0,stage='Unknown',priority='High',db_path=self.db)
