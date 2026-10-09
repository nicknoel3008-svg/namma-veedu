import unittest

from inquiry_log import _excel_text


class InquiryRedactionTests(unittest.TestCase):
    def test_generated_conversation_id_is_preserved(self):
        conversation_id = "67d66233-1bda-4771-9941-2961d7762352"
        self.assertEqual(_excel_text(conversation_id), conversation_id)
        self.assertEqual(_excel_text('ID: ' + conversation_id), 'ID: ' + conversation_id)

    def test_identity_numbers_still_redacted(self):
        for number in ("123456789012", "1234 5678 9012", "1234-5678-9012"):
            with self.subTest(number=number):
                self.assertEqual(_excel_text('Aadhaar: ' + number + '.'), 'Aadhaar: [Aadhaar redacted].')
        self.assertEqual(_excel_text('PAN: ABCDE1234F'), 'PAN: [PAN redacted]')
