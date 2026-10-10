"""Minimal shared session counts; no IPs, contacts or chat text."""
from datetime import datetime
from followup_service import FOLLOWUP_DB, _connect
from agent_runtime import INDIA_TZ
from functools import lru_cache


def schema(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS website_sessions (id TEXT PRIMARY KEY, started_at TEXT NOT NULL)")
    if getattr(connection, "shared", False):
        connection.execute("ALTER TABLE website_sessions ADD COLUMN IF NOT EXISTS browser_seconds TEXT NOT NULL DEFAULT ''")
        connection.execute("ALTER TABLE website_sessions ENABLE ROW LEVEL SECURITY")
    elif 'browser_seconds' not in {row['name'] for row in connection.execute('PRAGMA table_info(website_sessions)').fetchall()}:
        connection.execute("ALTER TABLE website_sessions ADD COLUMN browser_seconds TEXT NOT NULL DEFAULT ''")


def record_session(session_id, db_path=FOLLOWUP_DB):
    with _connect(db_path) as connection:
        schema(connection)
        connection.execute("INSERT INTO website_sessions (id,started_at) VALUES (?,?) ON CONFLICT(id) DO NOTHING",
                           (session_id, datetime.now(INDIA_TZ).isoformat(timespec="seconds")))


def sessions(db_path=FOLLOWUP_DB):
    with _connect(db_path) as connection:
        schema(connection)
        return [dict(row) for row in connection.execute("SELECT * FROM website_sessions ORDER BY started_at").fetchall()]


def delivery_records(db_path=FOLLOWUP_DB):
    with _connect(db_path) as connection:
        return [dict(row) for row in connection.execute("SELECT conversation_id,channel,status,sent_count,updated_at,CASE WHEN last_error<>'' THEN 1 ELSE 0 END AS failed_recent FROM email_followups").fetchall()]


def record_browser_time(session_id, seconds, db_path=FOLLOWUP_DB):
    seconds = float(seconds)
    if not 0 < seconds < 600:
        raise ValueError("Invalid browser timing")
    with _connect(db_path) as connection:
        schema(connection)
        connection.execute("UPDATE website_sessions SET browser_seconds=? WHERE id=? AND browser_seconds=''", (str(round(seconds, 3)), session_id))


@lru_cache(maxsize=1)
def browser_component():
    from streamlit.components.v2 import component
    return component("namma_veedu_browser_timing", js="""
export default function(component) {
    if (window.__nammaVeeduTimingCaptured) return;
    window.__nammaVeeduTimingCaptured = true;
    requestAnimationFrame(() => requestAnimationFrame(() => {
        component.setStateValue('seconds', performance.now() / 1000);
    }));
}
""")


def capture_browser_time():
    import streamlit as st
    if not st.session_state.get("website_session_recorded") or st.session_state.get("browser_timing_saved"):
        return
    result = browser_component()(key="website_browser_timing", on_seconds_change=lambda: None)
    seconds = result.seconds
    if seconds is not None:
        record_browser_time(st.session_state.analytics_session_id, seconds)
        st.session_state.browser_timing_saved = True
