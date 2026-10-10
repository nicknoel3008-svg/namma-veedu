"""Run with Streamlit for browser QA without writing leads or sending email.

streamlit run tests/website_sandbox.py --server.port 8503
"""
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

with patch("ai_config.select_ai_config", return_value=("offline", "", "")), \
     patch("storage_backend._database_url", return_value=""), \
     patch("inquiry_log.append_inquiry"), \
     patch("inquiry_log.read_inquiries", return_value=[]), \
     patch("inquiry_log.update_conversation_fields"), \
     patch("mira_learning_library.load_learning_rules", return_value=[]), \
     patch("mira_learning_library.save_learning_rules"), \
     patch("followup_service.cancel_user_followups", return_value=0), \
     patch("followup_service.list_email_followups", return_value=[]), \
     patch("followup_service.schedule_email_followup", side_effect=RuntimeError("Email sending is disabled in browser QA")), \
     patch("whatsapp_followup.schedule_whatsapp_followup", side_effect=RuntimeError("WhatsApp sending is disabled in browser QA")), \
     patch("visit_service.confirmed_visit_times", return_value=set()), \
     patch("visit_service.request_visit", return_value="qa-visit-request"), \
     patch("visit_service.list_visit_requests", return_value=[]), \
     patch("customer_journey.select_property"), \
     patch("customer_journey.choices", return_value=[]), \
     patch("customer_journey.timeline", return_value=[]), \
     patch("visit_journey.owner_journeys", return_value=[]):
    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
