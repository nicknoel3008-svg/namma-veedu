from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_runtime import INDIA_TZ
from followup_service import _connect, schedule_email_followup, send_chat_end_recommendations


class ChatEndEmailTests(unittest.TestCase):
    config = dict(FOLLOWUP_SMTP_HOST='smtp.example.com', FOLLOWUP_SMTP_USERNAME='sender',
                  FOLLOWUP_SMTP_PASSWORD='test', FOLLOWUP_SMTP_FROM='sender@example.com',
                  FOLLOWUP_PUBLIC_URL='https://example.com')

    def test_immediate_email_preserves_followups_and_does_not_repeat(self):
        with TemporaryDirectory() as folder:
            db = Path(folder) / 'queue.sqlite3'
            identifier = schedule_email_followup(user_id='u', conversation_id='c',
                recipient_email='buyer@example.com', customer_name='', preference_summary='Plots',
                started_at=datetime.now(INDIA_TZ), max_messages=3, db_path=db)
            with patch('followup_service.smtplib.SMTP') as smtp, patch('inquiry_log.update_conversation_fields'):
                args = dict(config=self.config, user_id='u', conversation_id='c',
                            recommendations='Updated matching plot: source.example', db_path=db)
                self.assertEqual(send_chat_end_recommendations(**args), (1, 0))
                self.assertEqual(send_chat_end_recommendations(**args), (0, 0))
                self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count, 1)
                with _connect(db) as connection:
                    row = connection.execute('SELECT * FROM email_followups WHERE id=?', (identifier,)).fetchone()
                self.assertEqual((row['sent_count'], row['max_messages'], row['status']), (1, 4, 'scheduled'))
                self.assertEqual(row['recommendations'], args['recommendations'])
                self.assertGreater(datetime.fromisoformat(row['next_send_at']), datetime.now(INDIA_TZ)+timedelta(days=2))

    def test_no_consent_or_delivery_off_never_sends(self):
        with TemporaryDirectory() as folder, patch('followup_service.smtplib.SMTP') as smtp:
            args = dict(user_id='u', conversation_id='c', recommendations='Plot',
                        db_path=Path(folder)/'queue.sqlite3')
            self.assertEqual(send_chat_end_recommendations(config=self.config, **args), (0, 0))
            self.assertEqual(send_chat_end_recommendations(config={}, **args), (0, 0))
            smtp.assert_not_called()
