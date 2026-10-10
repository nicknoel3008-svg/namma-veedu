"""Isolated owner UI preview with empty inquiry/rule fixtures. Local QA only."""
from pathlib import Path
import runpy
import sys
from unittest.mock import patch
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
st.query_params["studio"] = "1"
st.session_state.owner_dashboard_authenticated = True
with patch("ai_config.select_ai_config", return_value=("offline", "", "")), \
     patch("storage_backend._database_url", return_value=""), \
     patch("inquiry_log.read_inquiries", return_value=st.session_state.get("qa_inquiry_rows", [])), \
     patch("inquiry_log.append_inquiry"), \
     patch("inquiry_log.update_conversation_fields"), \
     patch("mira_learning_library.load_learning_rules", return_value=[]), \
     patch("mira_learning_library.save_learning_rules"), \
     patch("followup_service.cancel_user_followups", return_value=0), \
     patch("followup_service.list_email_followups", return_value=[]), \
     patch("customer_journey.choices", side_effect=lambda *args,**kwargs: st.session_state.get("qa_choices", [])), \
     patch("customer_journey.timeline", side_effect=lambda *args,**kwargs: st.session_state.get("qa_events", [])), \
     patch("visit_journey.owner_journeys", side_effect=lambda *args,**kwargs: st.session_state.get("qa_journeys", [])), \
     patch("advisor_directory.advisors", return_value=[]), \
     patch("advisor_directory.save_advisor"), \
     patch("advisor_directory.prepare_handoff"), \
     patch("visit_journey.record_purchase_outcome"):

    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
