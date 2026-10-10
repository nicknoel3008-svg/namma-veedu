"""Wati submission tests: temporary queues and mocked HTTP only."""
from unittest.mock import Mock, patch
from tests.test_whatsapp_followup import WhatsAppFollowupTests
from followup_service import list_email_followups, _connect
from whatsapp_followup import send_due_whatsapp_followups, whatsapp_config_issues

WATI = dict(FOLLOWUP_WHATSAPP_ENABLED='true', WHATSAPP_PROVIDER='wati',
            WATI_API_BASE_URL='https://live-mt-server.wati.io/123', WATI_ACCESS_TOKEN='test-secret',
            WATI_TEMPLATE_NAME='namma_veedu_recommendations_en', WATI_CHANNEL_NUMBER='919999999999',
            FOLLOWUP_PUBLIC_URL='https://example.com')

class WatiTests(WhatsAppFollowupTests):
    def test_wati_submission_preserves_recommendations_and_stop_link(self):
        key=self.due()
        response=Mock(status_code=200)
        response.json.return_value={'result':True,'localMessageId':'local-test'}
        with patch('whatsapp_followup.requests.post',return_value=response) as post, patch('inquiry_log.update_conversation_fields'):
            self.assertEqual(send_due_whatsapp_followups(WATI,self.db),(1,0))
            self.assertEqual(send_due_whatsapp_followups(WATI,self.db),(0,0))
        payload=post.call_args.kwargs['json']
        self.assertIn('Saved listing A',payload['parameters'][0]['value'])
        self.assertIn('stop_followup='+key,payload['parameters'][2]['value'])
        self.assertEqual(post.call_args.kwargs['params']['whatsappNumber'],'919876543210')
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertEqual(list_email_followups('qa',self.db)[0]['provider_message_id'],'wati:local-test')

    def test_wati_ambiguous_or_rejected_response_never_retries(self):
        for index,body in enumerate(({'result':False,'localMessageId':'bad'}, {'result':True})):
            self.due(preference_summary=str(index))
            response=Mock(status_code=200)
            response.json.return_value=body
            with patch('whatsapp_followup.requests.post',return_value=response) as post, patch('inquiry_log.update_conversation_fields'):
                self.assertEqual(send_due_whatsapp_followups(WATI,self.db),(0,1))
                self.assertEqual(send_due_whatsapp_followups(WATI,self.db),(0,0))
                self.assertEqual(post.call_count,1)

    def test_no_consent_never_sends_even_if_row_scheduled(self):
        key=self.due()
        with _connect(self.db) as connection:
            connection.execute("UPDATE email_followups SET opted_in_at='' WHERE id=?",(key,))
        with patch('whatsapp_followup.requests.post') as post:
            self.assertEqual(send_due_whatsapp_followups(WATI,self.db),(0,0))
            post.assert_not_called()

    def test_provider_config_does_not_require_meta_credentials(self):
        self.assertEqual(whatsapp_config_issues(WATI),[])
        for base in ('http://live-mt-server.wati.io/123','https://example.com/123','https://live.wati.io.attacker.test/123','https://live.wati.io/123?token=bad','https://live.wati.io:invalid/123','https://[bad/123'):
            self.assertTrue(whatsapp_config_issues({**WATI,'WATI_API_BASE_URL':base}))
        self.assertTrue(whatsapp_config_issues({**WATI,'FOLLOWUP_WHATSAPP_ENABLED':'false'}))
