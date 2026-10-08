"""Private, append-only workbook storage for property inquiries."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import re
import uuid
import logging
from threading import Lock, Timer

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment, Font, PatternFill


INQUIRY_LOG_PATH = Path(__file__).resolve().parent / "data" / "private" / "inquiries.xlsx"
INQUIRY_ARCHIVE_DIR = INQUIRY_LOG_PATH.parent / "Property Inquiries"
SHEET_NAME = "Inquiries"
HEADERS = (
    "Inquiry ID",
    "Conversation ID",
    "Timestamp (Asia/Kolkata)",
    "Language",
    "User inquiry",
    "Assistant response",
    "Response type",
    "Matching records",
    "Search criteria",
    "Property details / tool results",
    "Recent conversation context",
    "User ID",
    "Customer name",
    "Preferred form of address",
    "Details shared by customer",
    "Conversation topic",
    "Customer tone signal",
    "Follow-up requested signal",
    "Follow-up method",
    "Follow-up schedule status",
    "Follow-up cadence",
    "Follow-up consent timestamp (Asia/Kolkata)",
    "Next follow-up time (Asia/Kolkata)",
    "Human handoff requested signal",
    "Listing status asked signal",
    "Sale outcome mentioned signal",
    "Follow-up status (owner)",
    "Follow-up date (owner)",
    "Listing status (owner)",
    "Sale outcome (owner)",
    "Advisor notes (owner)",
    "Customer satisfaction signal",
    "Customer satisfaction (owner)",
    "Customer interest signal",
    "Customer interest (owner)",
    "Budget mentioned signal",
    "Customer budget / price stated",
    "Purchase value / offer stated",
    "Property type mentioned",
    "Location mentioned",
    "Preferred size stated",
    "Next follow-up action (owner)",
    "Lead priority (owner)",
    "Conversation status",
    "Chat ended at (Asia/Kolkata)",
    "Conversation close reason",
    "Final conversation transcript",
    "Mira performance rating (1-5)",
    "User satisfaction rating (1-5)",
    "Advisor callback status",
    "Advisor callback method",
    "Advisor callback contact",
    "Advisor callback preferred time",
    "Advisor callback consent timestamp",
    "Mira review status (owner)",
    "Mira corrected intent (owner)",
    "Mira review notes (owner)",
)
_WRITE_LOCK = Lock()
_MAX_CELL_LENGTH = 32_000
_AADHAAR_PATTERN = re.compile(r"(?<!\d)(?:\d[\s-]?){11}\d(?!\d)")
_PAN_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)
_SNAPSHOT_TIMER_LOCK = Lock()
_SNAPSHOT_TIMER: Timer | None = None


def schedule_daily_inquiry_snapshot(path: Path = INQUIRY_LOG_PATH) -> None:
    """Debounce daily workbook refreshes so export work never delays a chat reply."""
    global _SNAPSHOT_TIMER
    path = Path(path)
    if path.resolve() != INQUIRY_LOG_PATH.resolve():
        return

    def refresh() -> None:
        try:
            write_daily_inquiry_snapshot(path)
        except Exception:
            logging.exception("Could not refresh the daily inquiry export")

    with _SNAPSHOT_TIMER_LOCK:
        if _SNAPSHOT_TIMER is not None:
            _SNAPSHOT_TIMER.cancel()
        _SNAPSHOT_TIMER = Timer(1.0, refresh)
        _SNAPSHOT_TIMER.daemon = True
        _SNAPSHOT_TIMER.start()


def _excel_text(value: Any) -> str:
    """Bound text to Excel's cell limit and prevent formula injection."""
    text = "" if value is None else str(value)
    # Chat transcripts are private exports, so strip identity numbers before
    # persisting either the direct inquiry or a serialized conversation.
    text = _AADHAAR_PATTERN.sub("[Aadhaar redacted]", text)
    text = _PAN_PATTERN.sub("[PAN redacted]", text)
    if len(text) > _MAX_CELL_LENGTH:
        text = text[:_MAX_CELL_LENGTH] + " …[truncated to fit Excel cell limit]"
    if text.lstrip().startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text


def _backfill_user_ids(worksheet) -> bool:
    """Add a session ID column and derive stable IDs for older conversation rows."""
    headers = [cell.value for cell in worksheet[1]]
    try:
        conversation_column = headers.index("Conversation ID") + 1
    except ValueError:
        conversation_column = 0
    try:
        user_column = headers.index("User ID") + 1
    except ValueError:
        user_column = worksheet.max_column + 1
        cell = worksheet.cell(1, user_column, "User ID")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087D78")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        worksheet.column_dimensions[cell.column_letter].width = 30
    changed = "User ID" not in headers
    for row_index in range(2, worksheet.max_row + 1):
        if worksheet.cell(row_index, user_column).value:
            continue
        conversation_id = worksheet.cell(row_index, conversation_column).value if conversation_column else None
        if conversation_id:
            token = uuid.uuid5(uuid.NAMESPACE_URL, f"namma-illam:{conversation_id}").hex[:12].upper()
            worksheet.cell(row_index, user_column, f"NMI-USER-{token}")
            changed = True
    return changed


def _ensure_headers(worksheet) -> bool:
    """Append newly introduced columns without disturbing existing inquiry rows."""
    headers = [cell.value for cell in worksheet[1]]
    changed = False
    if not headers or headers[0] is None:
        for column, header in enumerate(HEADERS, start=1):
            worksheet.cell(1, column, header)
        headers = list(HEADERS)
        changed = True
    for header in HEADERS:
        if header in headers:
            continue
        column = worksheet.max_column + 1
        cell = worksheet.cell(1, column, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087D78")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        worksheet.column_dimensions[cell.column_letter].width = 24 if "owner)" in header else 28
        headers.append(header)
        changed = True
    worksheet.freeze_panes = "A2"
    return changed


def update_inquiry_fields(inquiry_id: str, fields: dict[str, Any], path: Path = INQUIRY_LOG_PATH) -> bool:
    """Update owner-maintained follow-up and sale fields for one inquiry."""
    path = Path(path)
    if not path.exists():
        return False
    allowed = {"Follow-up status (owner)", "Follow-up date (owner)", "Listing status (owner)", "Sale outcome (owner)", "Advisor notes (owner)", "Customer satisfaction (owner)", "Customer interest (owner)", "Next follow-up action (owner)", "Lead priority (owner)", "Mira review status (owner)", "Mira corrected intent (owner)", "Mira review notes (owner)"}
    updates = {key: _excel_text(value) for key, value in fields.items() if key in allowed}
    if not updates:
        return False
    with _WRITE_LOCK:
        workbook = load_workbook(path)
        try:
            worksheet = workbook[SHEET_NAME] if SHEET_NAME in workbook.sheetnames else workbook.active
            _ensure_headers(worksheet)
            headers = [cell.value for cell in worksheet[1]]
            id_column = headers.index("Inquiry ID") + 1
            target_row = next((row for row in range(2, worksheet.max_row + 1) if str(worksheet.cell(row, id_column).value or "") == inquiry_id), None)
            if target_row is None:
                return False
            for key, value in updates.items():
                worksheet.cell(target_row, headers.index(key) + 1, value)
            temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.tmp.xlsx")
            try:
                workbook.save(temporary)
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        finally:
            workbook.close()
    if path.resolve() == INQUIRY_LOG_PATH.resolve():
        schedule_daily_inquiry_snapshot(path)
    return True


def update_conversation_fields(conversation_id: str, fields: dict[str, Any], path: Path = INQUIRY_LOG_PATH) -> int:
    """Update conversation-level completion details on every matching turn."""
    path = Path(path)
    if not path.exists() or not str(conversation_id or "").strip():
        return 0
    allowed = {
        "Conversation status",
        "Chat ended at (Asia/Kolkata)",
        "Conversation close reason",
        "Final conversation transcript",
        "Follow-up method",
        "Follow-up schedule status",
        "Follow-up cadence",
        "Follow-up consent timestamp (Asia/Kolkata)",
        "Next follow-up time (Asia/Kolkata)",
        "Mira performance rating (1-5)",
        "User satisfaction rating (1-5)",
    }
    updates = {key: _excel_text(value) for key, value in fields.items() if key in allowed}
    if not updates:
        return 0
    updated_rows = 0
    with _WRITE_LOCK:
        workbook = load_workbook(path)
        try:
            worksheet = workbook[SHEET_NAME] if SHEET_NAME in workbook.sheetnames else workbook.active
            _ensure_headers(worksheet)
            headers = [cell.value for cell in worksheet[1]]
            id_column = headers.index("Conversation ID") + 1
            for row in range(2, worksheet.max_row + 1):
                if str(worksheet.cell(row, id_column).value or "") != str(conversation_id):
                    continue
                for key, value in updates.items():
                    worksheet.cell(row, headers.index(key) + 1, value)
                updated_rows += 1
            if updated_rows:
                temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.tmp.xlsx")
                try:
                    workbook.save(temporary)
                    os.replace(temporary, path)
                finally:
                    if temporary.exists():
                        temporary.unlink()
        finally:
            workbook.close()
    if updated_rows and path.resolve() == INQUIRY_LOG_PATH.resolve():
        schedule_daily_inquiry_snapshot(path)
    return updated_rows


def append_inquiry(record: dict[str, Any], path: Path = INQUIRY_LOG_PATH) -> None:
    """Append one completed inquiry to the private workbook, atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        if path.exists():
            workbook = load_workbook(path)
            worksheet = workbook[SHEET_NAME] if SHEET_NAME in workbook.sheetnames else workbook.active
            _ensure_headers(worksheet)
            _backfill_user_ids(worksheet)
        else:
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = SHEET_NAME
            worksheet.append(HEADERS)
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}1"
            for cell in worksheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="087D78")
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            widths = (28, 36, 25, 14, 52, 64, 18, 18, 42, 64, 72, 30, 28, 26, 64, 24, 22, 22, 24, 22, 24, 24, 20, 22, 22, 32, 28, 26, 26, 26, 22, 36, 36, 24, 28, 24, 30, 20, 22, 28, 34, 80)
            for index, width in enumerate(widths, 1):
                worksheet.column_dimensions[get_column_letter(index)].width = width

        workbook_headers = [cell.value for cell in worksheet[1] if cell.value]
        worksheet.append([_excel_text(record.get(header)) for header in workbook_headers])
        worksheet.auto_filter.ref = f"A1:{worksheet.cell(1, len(workbook_headers)).column_letter}{worksheet.max_row}"
        row = worksheet.max_row
        for cell in worksheet[row]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

        temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.tmp.xlsx")
        try:
            workbook.save(temporary)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
            workbook.close()
    # Keep an automatically refreshed, date-stamped daily workbook on the
    # server. It is available to the owner from the protected dashboard.
    if path.resolve() == INQUIRY_LOG_PATH.resolve():
        schedule_daily_inquiry_snapshot(path)


def archive_inquiry_export(data: bytes, export_kind: str, period_label: str = "selected_period") -> Path:
    """Save a generated workbook under a dated private archive folder."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    day_dir = INQUIRY_ARCHIVE_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    safe_period = re.sub(r"[^a-zA-Z0-9_-]+", "_", period_label.strip().lower()).strip("_") or "selected_period"
    kind = "manual" if export_kind.casefold() == "manual" else "automatic"
    stamp = now.strftime("%H%M%S") if kind == "manual" else now.strftime("%Y%m%d")
    target = day_dir / f"{kind}_inquiries_{safe_period}_{stamp}.xlsx"
    temporary = target.with_name(f".{target.stem}-{uuid.uuid4().hex}.tmp.xlsx")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def write_daily_inquiry_snapshot(path: Path = INQUIRY_LOG_PATH) -> Path | None:
    """Refresh today's automatic owner export after each saved chat turn."""
    path = Path(path)
    if not path.exists():
        return None
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    today = now.date()
    rows = read_inquiries(path)
    dated_rows = []
    for row in rows:
        stamp = row.get("Timestamp (Asia/Kolkata)") or row.get("Timestamp (Asia/Calcutta)")
        try:
            value = datetime.fromisoformat(str(stamp)).date()
        except (TypeError, ValueError):
            continue
        if value == today:
            dated_rows.append(row)
    if not dated_rows:
        return None
    payload = build_inquiry_export(dated_rows, today.strftime("%Y-%m-%d"), today.isoformat(), today.isoformat())
    day_dir = INQUIRY_ARCHIVE_DIR / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    target = day_dir / f"automatic_inquiries_{today:%Y%m%d}.xlsx"
    temporary = target.with_name(f".{target.stem}-{uuid.uuid4().hex}.tmp.xlsx")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def read_inquiries(path: Path = INQUIRY_LOG_PATH) -> list[dict[str, Any]]:
    """Read saved inquiry rows for the authenticated owner dashboard."""
    path = Path(path)
    if not path.exists():
        return []
    with _WRITE_LOCK:
        workbook = load_workbook(path, data_only=True)
        try:
            worksheet = workbook[SHEET_NAME]
            changed = _ensure_headers(worksheet)
            changed = _backfill_user_ids(worksheet) or changed
            if changed:
                temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.tmp.xlsx")
                try:
                    workbook.save(temporary)
                    os.replace(temporary, path)
                finally:
                    if temporary.exists():
                        temporary.unlink()
            rows = worksheet.iter_rows(values_only=True)
            headers = next(rows, ())
            return [dict(zip(headers, row)) for row in rows if any(value is not None for value in row)]
        finally:
            workbook.close()


CUSTOMER_SUMMARY_HEADERS = (
    "User ID", "Customer name", "Conversation ID", "Inquiry ID", "Timestamp (Asia/Kolkata)",
    "Language", "Conversation status", "Email follow-ups", "Interested in property",
    "Not interested in property", "Interest stated", "Follow-up requested", "Human advisor requested",
    "Property type", "Location", "Budget", "Preferred size", "Follow-up schedule status",
    "Follow-up cadence", "Next follow-up time (Asia/Kolkata)", "Chat ended at (Asia/Kolkata)",
    "Mira performance rating (1-5)", "User satisfaction rating (1-5)",
    "Customer interest (owner)", "Follow-up status (owner)", "Lead priority (owner)",
)

MIRA_RESPONSE_HEADERS = (
    "Inquiry ID", "Conversation ID", "Timestamp (Asia/Kolkata)", "Language",
    "Response type", "Mira response",
)


def customer_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One structured row per conversation; no verbatim customer or AI answers."""
    grouped = {}
    for row in sorted(rows, key=lambda item: str(item.get("Timestamp (Asia/Kolkata)") or "")):
        key = str(row.get("Conversation ID") or row.get("Inquiry ID") or len(grouped))
        grouped.setdefault(key, []).append(row)
    summaries = []
    for turns in grouped.values():
        latest = turns[-1]
        def last_value(field, ignored=("", "Not stated", "Not recorded", "Not updated")):
            return next((str(turn.get(field) or "") for turn in reversed(turns)
                         if str(turn.get(field) or "") not in ignored), "")
        interest = last_value("Customer interest (owner)") or last_value("Customer interest signal")
        summary = {header: latest.get(header, "") for header in CUSTOMER_SUMMARY_HEADERS}
        summary.update({
            "Email follow-ups": "Yes" if last_value("Follow-up method") in {"Email", "Email follow-up"} and last_value("Follow-up consent timestamp (Asia/Kolkata)") else "No",
            "Interested in property": "Yes" if interest in {"Interested", "Interested signal"} else "No",
            "Not interested in property": "Yes" if interest in {"Not interested", "Not interested signal"} else "No",
            "Interest stated": "Yes" if interest else "No",
            "Follow-up requested": "Yes" if any(turn.get("Follow-up requested signal") == "Yes" for turn in turns) else "No",
            "Human advisor requested": "Yes" if any(turn.get("Human handoff requested signal") == "Yes" for turn in turns) else "No",
            "Property type": last_value("Property type mentioned"),
            "Location": last_value("Location mentioned"),
            "Preferred size": last_value("Preferred size stated"),
            "Budget": "",
            "Mira performance rating (1-5)": last_value("Mira performance rating (1-5)"),
            "User satisfaction rating (1-5)": last_value("User satisfaction rating (1-5)"),
        })
        budget = last_value("Customer budget / price stated")
        amount = re.search(r"(?:₹|rs\.?\s*)?\d[\d,.]*\s*(?:lakh|lakhs|lac|crore|cr|k)\b|(?:₹|rs\.?\s*)\s*\d[\d,.]*", budget, re.I)
        summary["Budget"] = amount.group(0) if amount else ""
        summaries.append(summary)
    return summaries


CONVERSATION_TRANSCRIPT_HEADERS = (
    "Conversation ID", "Customer name", "User ID", "Language", "Conversation started at (Asia/Kolkata)",
    "Chat ended at (Asia/Kolkata)", "Conversation status", "Conversation close reason",
    "Mira performance rating (1-5)", "User satisfaction rating (1-5)", "Saved turns", "Complete chat transcript",
)


def conversation_transcript_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one private, owner-review row per conversation with its final transcript."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda item: str(item.get("Timestamp (Asia/Kolkata)") or "")):
        key = str(row.get("Conversation ID") or row.get("Inquiry ID") or len(grouped))
        grouped.setdefault(key, []).append(row)
    conversations = []
    for conversation_id, turns in grouped.items():
        latest = turns[-1]

        def last_value(field: str) -> str:
            return next((str(turn.get(field) or "") for turn in reversed(turns) if str(turn.get(field) or "").strip()), "")

        transcript = last_value("Final conversation transcript")
        if not transcript:
            transcript_lines = []
            for turn in turns:
                inquiry = str(turn.get("User inquiry") or "").strip()
                response = str(turn.get("Assistant response") or "").strip()
                if inquiry:
                    transcript_lines.append(f"Customer: {inquiry}")
                if response:
                    transcript_lines.append(f"Mira: {response}")
            transcript = "\n\n".join(transcript_lines)
        conversations.append({
            "Conversation ID": conversation_id,
            "Customer name": last_value("Customer name"),
            "User ID": last_value("User ID"),
            "Language": last_value("Language"),
            "Conversation started at (Asia/Kolkata)": str(turns[0].get("Timestamp (Asia/Kolkata)") or ""),
            "Chat ended at (Asia/Kolkata)": last_value("Chat ended at (Asia/Kolkata)"),
            "Conversation status": last_value("Conversation status"),
            "Conversation close reason": last_value("Conversation close reason"),
            "Mira performance rating (1-5)": last_value("Mira performance rating (1-5)"),
            "User satisfaction rating (1-5)": last_value("User satisfaction rating (1-5)"),
            "Saved turns": len(turns),
            "Complete chat transcript": transcript,
        })
    return conversations


def structured_archive_export(path: Path) -> bytes:
    """Present older snapshots in the current format without changing the archive."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[SHEET_NAME]
        values = worksheet.iter_rows(values_only=True)
        headers = next(values, ())
        if "Email follow-ups" in headers and "Mira responses" in workbook.sheetnames:
            return Path(path).read_bytes()
        rows = [dict(zip(headers, row)) for row in values]
        metadata = dict(workbook["Export details"].iter_rows(values_only=True)) if "Export details" in workbook.sheetnames else {}
        return build_inquiry_export(rows, str(metadata.get("Selected date filter", path.parent.name)),
                                    str(metadata.get("Start date", "")), str(metadata.get("End date", "")))
    finally:
        workbook.close()


def build_inquiry_export(rows: list[dict[str, Any]], period_label: str, start_date: str, end_date: str) -> bytes:
    """Create a formatted, date-scoped owner export with its selected period recorded."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = SHEET_NAME
    raw_rows = list(rows)
    rows = customer_summary_rows(raw_rows)
    headers = list(CUSTOMER_SUMMARY_HEADERS)
    worksheet.append(headers)
    for row in rows:
        worksheet.append([_excel_text(row.get(header)) for header in headers])
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087D78")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = f"A1:{worksheet.cell(1, len(headers)).column_letter}{worksheet.max_row}"
    for index, header in enumerate(headers, start=1):
        if header in {"User inquiry", "Assistant response", "Recent conversation context", "Property details / tool results", "Details shared by customer", "Advisor notes (owner)"}:
            width = 52
        elif header in {"Search criteria", "Customer budget / price stated", "Purchase value / offer stated", "Next follow-up action (owner)"}:
            width = 36
        elif header in {"Inquiry ID", "Conversation ID", "Timestamp (Asia/Kolkata)", "User ID"}:
            width = 28
        else:
            width = 24
        worksheet.column_dimensions[worksheet.cell(1, index).column_letter].width = width
    responses = workbook.create_sheet("Mira responses")
    responses.append(list(MIRA_RESPONSE_HEADERS))
    for row in sorted(raw_rows, key=lambda item: str(item.get("Timestamp (Asia/Kolkata)") or "")):
        response = str(row.get("Assistant response") or "").strip()
        if response:
            responses.append([
                _excel_text(row.get("Inquiry ID")),
                _excel_text(row.get("Conversation ID")),
                _excel_text(row.get("Timestamp (Asia/Kolkata)")),
                _excel_text(row.get("Language")),
                _excel_text(row.get("Response type")),
                _excel_text(response),
            ])
    for cell in responses[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087D78")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in responses.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    responses.freeze_panes = "A2"
    responses.auto_filter.ref = f"A1:{responses.cell(1, len(MIRA_RESPONSE_HEADERS)).column_letter}{responses.max_row}"
    for index, header in enumerate(MIRA_RESPONSE_HEADERS, start=1):
        responses.column_dimensions[get_column_letter(index)].width = 72 if header == "Mira response" else 28
    info = workbook.create_sheet("Export details")
    info.append(["Selected date filter", period_label])
    info.append(["Start date", start_date])
    info.append(["End date", end_date])
    info.append(["Conversations exported", len(rows)])
    info.append(["Mira responses exported", responses.max_row - 1])
    info.append(["Format", "One row per conversation. Yes means recorded evidence; No means not recorded. Both interest fields are No when interest is unstated. Email follow-ups means consent recorded, not delivery confirmed."])
    info.append(["Exported at (Asia/Kolkata)", datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")])
    info.column_dimensions["A"].width = 34
    info.column_dimensions["B"].width = 36
    for cell in info[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087D78")
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def build_conversation_transcript_export(rows: list[dict[str, Any]], period_label: str) -> bytes:
    """Create an owner-only workbook containing every saved customer and Mira chat."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Complete chats"
    headers = list(CONVERSATION_TRANSCRIPT_HEADERS)
    worksheet.append(headers)
    conversations = conversation_transcript_rows(list(rows))
    for conversation in conversations:
        worksheet.append([_excel_text(conversation.get(header)) for header in headers])
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087D78")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = f"A1:{worksheet.cell(1, len(headers)).column_letter}{worksheet.max_row}"
    for index, header in enumerate(headers, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = 88 if header == "Complete chat transcript" else 28
    details = workbook.create_sheet("Export details")
    details.append(["Selected date filter", period_label])
    details.append(["Conversations exported", len(conversations)])
    details.append(["Privacy", "Private owner review: includes saved customer messages and Mira replies."])
    details.append(["Exported at (Asia/Kolkata)", datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")])
    details.column_dimensions["A"].width = 32
    details.column_dimensions["B"].width = 88
    for cell in details[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087D78")
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()
