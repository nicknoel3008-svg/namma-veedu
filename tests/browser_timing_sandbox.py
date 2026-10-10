"""Local browser timing QA. Temporary storage only; no production records."""
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from site_analytics import record_session, record_browser_time, capture_browser_time, sessions

st.title("Browser timing QA")
st.caption("Isolated timing check; no customer records or email.")
if "timing_temp" not in st.session_state:
    st.session_state.timing_temp = TemporaryDirectory()
db = Path(st.session_state.timing_temp.name) / 'timing.sqlite3'
record_session('browser-qa', db)
st.session_state.analytics_session_id = 'browser-qa'
st.session_state.website_session_recorded = True
with patch('site_analytics.record_browser_time', partial(record_browser_time, db_path=db)):
    capture_browser_time()
st.write('Measured browser seconds: ' + str(sessions(db)[0]['browser_seconds'] or 'Awaiting browser sample'))
