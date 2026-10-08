import unittest
from followup_service import email_config_issues


class EmailSetupTests(unittest.TestCase):
    def setUp(self):
        self.config = {"FOLLOWUP_SMTP_HOST": "smtp.example.com", "FOLLOWUP_SMTP_USERNAME": "sender@example.com",
            "FOLLOWUP_SMTP_PASSWORD": "private", "FOLLOWUP_SMTP_FROM": "sender@example.com",
            "FOLLOWUP_PUBLIC_URL": "https://example.com", "FOLLOWUP_SMTP_PORT": ""}

    def test_blank_port_uses_default(self):
        self.assertEqual(email_config_issues(self.config), [])

    def test_missing_credentials_are_named_without_values(self):
        issues = email_config_issues({})
        self.assertIn("Missing FOLLOWUP_SMTP_PASSWORD", issues)

    def test_localhost_cannot_be_an_unsubscribe_destination(self):
        self.config["FOLLOWUP_PUBLIC_URL"] = "http://localhost:8501"
        self.assertIn("localhost", " ".join(email_config_issues(self.config)))

    def test_invalid_port_is_reported(self):
        self.config["FOLLOWUP_SMTP_PORT"] = "wrong"
        self.assertIn("port number", " ".join(email_config_issues(self.config)))
