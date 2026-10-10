"""Fictional data for visual QA only; uses the isolated owner sandbox."""
from datetime import datetime, timedelta
from pathlib import Path
import runpy
import streamlit as st

now = datetime.now()
st.session_state.qa_sessions = [dict(id=f"sample-{day}-{i}", started_at=(now-timedelta(days=day)).isoformat(), browser_seconds=str(1.2 + day/10)) for day in range(14) for i in range(8 + day % 5)]
st.session_state.qa_inquiry_rows = [
    {"Inquiry ID":f"sample-{day}-{i}", "Conversation ID":f"conversation-{day}-{i//2}", "User ID":f"sample-user-{day}-{i//2}",
     "Timestamp (Asia/Kolkata)":(now-timedelta(days=day)).isoformat(), "User inquiry":"I am looking for a home in Chennai.",
     "Assistant response":"Tell me your preferred area and budget so I can help you narrow down the available records.",
     "Response type":"search", "Matching records":3, "Mira response seconds":1.3 + day/10,
     "Property type mentioned":"Flat", "Location mentioned":"Chennai", "Mira performance rating (1-5)":4 + i%2}
    for day in range(14) for i in range(4+day%3)]
st.info("Visual QA only · fictional sample records · no customer writes or messages")
runpy.run_path(str(Path(__file__).with_name('owner_dashboard_sandbox.py')), run_name='__main__')
