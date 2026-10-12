import tempfile
import unittest
from pathlib import Path
from crm_whatsapp import record_chat_open, chat_opened, opening_key
from crm_service import schema, activities
from followup_service import _connect

class WhatsAppOpeningTests(unittest.TestCase):
    def test_opening_persisted_once_without_claiming_send(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'crm.sqlite3'
            with _connect(db) as c:
                schema(c)
                c.execute("INSERT INTO crm_leads(id,customer_name,created_at,updated_at) VALUES(?,?,?,?)",('lead','Test','now','now'))
            key=opening_key('lead','visit','tomorrow','confirmation')
            self.assertFalse(chat_opened(key,db))
            for _ in range(2):
                record_chat_open('lead',key,'+919876543210','Prepared confirmation','Owner',db)
            self.assertTrue(chat_opened(key,db))
            rows=activities('lead',db)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['kind'],'WhatsApp chat opened')
            self.assertIn('unverified',rows[0]['detail'])
            self.assertFalse(chat_opened(opening_key('lead','visit','new time','confirmation'),db))
            with _connect(db) as c:
                self.assertEqual(c.execute('SELECT message FROM crm_whatsapp_openings').fetchone()['message'],'Prepared confirmation')
