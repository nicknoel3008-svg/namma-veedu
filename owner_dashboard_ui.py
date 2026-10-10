"""Coastal owner overview with measured metrics and four connected records views."""
from datetime import datetime
from io import BytesIO
from math import ceil
import pandas as pd
import streamlit as st
from openpyxl import Workbook
from agent_runtime import INDIA_TZ
from inquiry_log import customer_summary_rows, _excel_text

NAVY, GOLD = "#18334D", "#B89750"


def date_of(value):
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return None
    return (stamp.tz_localize(INDIA_TZ) if stamp.tzinfo is None else stamp.tz_convert(INDIA_TZ)).date()


def in_period(value, start, end):
    day = date_of(value)
    return bool(day and (start is None or day >= start) and (end is None or day <= end))


def p95(values):
    values = sorted(float(v) for v in values if pd.notna(pd.to_numeric(v, errors="coerce")) and float(v) >= 0)
    return f"{values[ceil(.95 * len(values)) - 1]:.2f} s" if values else "Not measured"


def activity(rows, website_sessions):
    """Daily session counts separate from deduplicated conversations and actual replies."""
    website, mira = {}, {}
    seen = set()
    for row in website_sessions:
        day = date_of(row.get("started_at"))
        identity = row.get("id")
        if day and identity and identity not in seen:
            seen.add(identity)
            website[day.isoformat()] = website.get(day.isoformat(), 0) + 1
    conversations = set()
    replies = set()
    for index, row in enumerate(rows):
        day = date_of(row.get("Timestamp (Asia/Kolkata)"))
        if not day:
            continue
        day = day.isoformat()
        counts = mira.setdefault(day, {"Conversations": 0, "Replies": 0})
        conversation = row.get("Conversation ID")
        if conversation and (day, conversation) not in conversations:
            conversations.add((day, conversation))
            counts["Conversations"] += 1
        reply = row.get("Inquiry ID") or index
        if str(row.get("Assistant response") or "").strip() and reply not in replies:
            replies.add(reply)
            counts["Replies"] += 1
    return ([{"Date": day, "Sessions": count} for day, count in sorted(website.items())],
            [{"Date": day, "Series": series, "Count": count} for day, counts in sorted(mira.items()) for series, count in counts.items()])


def workbook_bytes(sheets):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, frame in sheets.items():
        sheet = workbook.create_sheet(name)
        sheet.append(list(frame.columns))
        for row in frame.fillna("").itertuples(index=False, name=None):
            sheet.append([_excel_text(str(value)) for value in row])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def render(rows, *, sessions, deliveries, visits, selections, rules, history_rows=None, start=None, end=None, telemetry_available=True):
    summary = customer_summary_rows(rows)
    website = [r for r in sessions if in_period(r.get("started_at"), start, end)]
    relevant = {str(r.get("Conversation ID") or "") for r in rows}
    visits = [r for r in visits if str(r.get("conversation_id") or "") in relevant]
    deliveries = [r for r in deliveries if str(r.get("conversation_id") or "") in relevant and in_period(r.get("updated_at"), start, end)]
    ratings = [float(r["Mira performance rating (1-5)"]) for r in summary if pd.notna(pd.to_numeric(r.get("Mira performance rating (1-5)"), errors="coerce")) and 1 <= float(r["Mira performance rating (1-5)"]) <= 5]
    search_ids = {r.get("Conversation ID") for r in rows if r.get("Conversation ID") and pd.notna(pd.to_numeric(r.get("Matching records"), errors="coerce"))}
    matched = {r.get("Conversation ID") for r in rows if r.get("Conversation ID") and pd.to_numeric(r.get("Matching records"), errors="coerce") > 0}
    email = [r for r in deliveries if r.get("channel") == "email"]
    failed_rows = [r for r in email if r.get("failed_recent") or r.get("status") in ("failed", "needs_review")]
    failed = len(failed_rows)
    submitted = sum(int(r.get("sent_count") or 0) > 0 and r not in failed_rows for r in email)
    complete = sum(r.get("attended") == "Yes" for r in visits)
    confirmed = sum(r.get("status") == "Confirmed" for r in visits)
    purchased = len({r.get("visit_id") for r in visits if r.get("purchase_outcome") == "Purchased"})
    metrics = [
        ("Website sessions", f"{len({r['id'] for r in website}):,}" if telemetry_available and sessions else "No samples", "Anonymous Streamlit sessions, counted once. Collection starts with this release; not unique people or historical traffic."),
        ("Dashboard load · p95", p95([r.get("browser_seconds") for r in website]), "Live browser navigation to the customer dashboard timing component's first painted frame. Includes startup, network and initial rendering; new samples only. Local QA is separate."),
        ("Mira response · p95", p95([r.get("Mira response seconds") for r in rows]), "95th percentile of measured server turn processing, including tools; excludes browser/network rendering. New turns only."),
        ("Mira rating", f"{sum(ratings)/len(ratings):.1f} / 5" if ratings else "Not rated", f"Latest rating per conversation. {len(ratings)} valid ratings; unrated conversations excluded."),
        ("Search success", f"{len(matched)/len(search_ids):.0%}" if search_ids else "No searches", "Share of conversations with numeric recorded search results that found a match. Does not verify availability."),
        ("Follow-up acceptance", f"{submitted/(submitted+failed):.0%}" if submitted+failed else "No attempts", "Share of attempted search-email schedules whose last known SMTP attempt succeeded. Uses current queue state and update date, not a historical attempt-level rate. Inbox delivery is unverified."),
        ("Visits completed", f"{complete} / {confirmed}", "Completed / currently confirmed visit requests linked to conversations in this period."),
        ("Confirmed purchases", str(purchased), "Visit outcomes explicitly recorded Purchased by the owner. Customer interest and reports are separate."),
    ]
    for offset in (0, 4):
        for column, (label, value, help_text) in zip(st.columns(4), metrics[offset:offset+4]):
            column.metric(label, value, help=help_text)
    st.caption("Actual recorded data only. Sessions and browser timing collection start with this release; older traffic is unavailable. Browser load and Mira server processing are separate measurements; local QA timings are not mixed in.")
    site_data, mira_data = activity(rows, website)
    for column, title, data, kind in zip(st.columns(2), ("Website activity", "Mira activity"), (site_data, mira_data), ("website", "mira")):
        with column, st.container(border=True):
            st.subheader(title)
            st.caption("Daily anonymous sessions" if kind == "website" else "Daily conversations and saved replies")
            if not data:
                st.info("No measured activity for this period.")
                continue
            encoding = {"x": {"field": "Date", "type": "temporal", "axis": {"title": None, "format": "%d %b", "labelAngle": 0, "tickCount": 5}},
                        "y": {"field": "Sessions" if kind == "website" else "Count", "type": "quantitative", "axis": {"title": None, "tickMinStep": 1}}}
            mark = {"type": "area", "line": {"color": NAVY, "strokeWidth": 3}, "color": NAVY, "opacity": .24, "point": {"filled": True, "size": 40}}
            if kind == "mira":
                mark = {"type": "bar", "cornerRadiusTopLeft": 4, "cornerRadiusTopRight": 4}
                encoding.update({"xOffset": {"field": "Series"}, "color": {"field": "Series", "scale": {"domain": ["Conversations", "Replies"], "range": [NAVY, GOLD]}, "legend": {"orient": "top", "title": None}}})
            encoding["tooltip"] = [{"field": "Date", "type": "temporal"}, {"field": "Sessions" if kind == "website" else "Count", "type": "quantitative"}]
            st.vega_lite_chart(pd.DataFrame(data), {"height": 240, "background": "#F5F2EA", "mark": mark, "encoding": encoding, "config": {"view": {"stroke": None}, "legend": {"labelColor": "#18334D", "titleColor": "#18334D"}, "axis": {"titleColor": "#18334D", "labelColor": "#18334D", "gridColor": "#E8EDF0", "domain": False, "labelFontSize": 11}}}, use_container_width=True)
    st.subheader("Owner records")
    st.caption(f"{len(summary):,} conversations · linked responses, actions and feedback")
    st.caption("Four connected views. Every saved conversation is included; customer feedback and learning changes keep the existing owner approval workflow.")
    inquiry_frame = pd.DataFrame(summary)
    first_columns = ["Conversation ID", "Timestamp (Asia/Kolkata)", "Customer name", "Property type", "Location", "Budget", "Conversation status", "Follow-up schedule status", "Mira performance rating (1-5)"]
    inquiry_frame = inquiry_frame.reindex(columns=first_columns + [c for c in inquiry_frame.columns if c not in first_columns])
    frames = {
        "Inquiries": inquiry_frame,
        "Mira responses & actions": pd.DataFrame(rows).reindex(columns=["Inquiry ID", "Conversation ID", "Timestamp (Asia/Kolkata)", "Assistant response", "Response type", "Matching records", "Mira response seconds", "Follow-up schedule status", "Human handoff requested signal", "Advisor callback status"]),
        "Feedback": pd.DataFrame([r for r in rows if r.get("Feedback ID")]).reindex(columns=["Feedback ID", "Conversation ID", "Timestamp (Asia/Kolkata)", "Feedback category", "Feedback comment", "Mira performance rating (1-5)"]),
        "Learning library": pd.DataFrame(rules),
    }
    for tab, (name, frame) in zip(st.tabs(list(frames)), frames.items()):
        with tab:
            if frame.empty:
                st.info("No records in this view yet.")
            else:
                st.dataframe(frame.fillna(""), hide_index=True, use_container_width=True)
            if name == "Inquiries" and relevant - {""}:
                selected = st.selectbox("Read complete conversation", sorted(relevant - {""}), key="owner_full_conversation")
                st.caption("Complete saved conversation, including turns outside the selected report period.")
                transcript = sorted([r for r in (history_rows if history_rows is not None else rows) if str(r.get("Conversation ID") or "") == selected], key=lambda r: str(r.get("Timestamp (Asia/Kolkata)") or ""))
                for row in transcript:
                    if row.get("User inquiry"):
                        with st.chat_message("user"):
                            st.write(str(row["User inquiry"]))
                    if row.get("Assistant response"):
                        with st.chat_message("assistant"):
                            st.write(str(row["Assistant response"]))
            if name == "Learning library":
                st.caption("Use the Mira Learning Library editor below to add, edit, approve, reject or pause rules. Only Approved guidance affects Mira. Learning rules show their current state across all dates.")
    st.download_button("Download four connected record views (.xlsx)", workbook_bytes(dict(zip(("Inquiries", "Mira work", "Feedback", "Learning library"), frames.values()))), "namma_veedu_owner_records.xlsx", key="download_connected_records")
    journey_column, left, right = st.columns(3)
    with journey_column, st.container(border=True):
        st.subheader("Customer journey")
        selected = {r.get("conversation_id") for r in selections if str(r.get("conversation_id") or "") in relevant and r.get("status") == "Selected"}
        journey_data = pd.DataFrame({"Stage": ["Conversations", "Active shortlists", "Visits completed", "Verified purchases"], "Count": [len(summary), len(selected), complete, purchased]})
        st.vega_lite_chart(journey_data, {"height": 150, "background": "#F5F2EA", "mark": {"type": "bar", "color": NAVY, "cornerRadiusEnd": 5}, "encoding": {"y": {"field": "Stage", "type": "nominal", "sort": None, "axis": {"title": None, "domain": False, "ticks": False, "labelColor": "#18334D"}}, "x": {"field": "Count", "type": "quantitative", "axis": {"title": None, "tickMinStep": 1, "gridColor": "#E8EDF0"}}, "tooltip": [{"field": "Stage"}, {"field": "Count"}]}, "config": {"view": {"stroke": None}}}, use_container_width=True)
        st.caption("Recorded stages use different units; this is not a purchase conversion forecast.")
    with left, st.container(border=True):
        st.subheader("Action queue")
        st.write(f"Open follow-ups: {sum(r.get('Follow-up schedule status') in ('Scheduled', 'Active') for r in summary)}")
        st.write(f"Emails needing review: {failed}")
        st.write(f"Advisor requests: {sum(r.get('Human advisor requested') == 'Yes' for r in summary)}")
    with right, st.container(border=True):
        st.subheader("Feedback & learning")
        st.write(f"Feedback received: {len(frames['Feedback'])}")
        st.write(f"Awaiting approval: {sum(r.get('Status') == 'Draft' for r in rules)}")
        st.write(f"Approved improvements: {sum(r.get('Status') == 'Approved' for r in rules)}")
        st.caption("Existing quality review, feedback drafts, outcome tracking and learning approval controls are preserved below.")
