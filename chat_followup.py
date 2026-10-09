"""Collect follow-up details in chat, without redirecting to a form."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Kolkata")


def followup_turn(text, state=None, now=None, tamil=False):
    query = text.casefold()
    state = dict(state or {})
    requested = re.search(r"\b(?:follow[- ]?ups?|remind(?:ers?)?|check back with me|email me later)\b|நினைவூட்ட|நினைவுபடுத்து|பின்னர் தொடர்பு", query)
    email_request = re.search(r"\b(?:email|e-mail|mail)\b.{0,80}\b(?:me|send|share|suggestions|properties|results)\b|\b(?:send|share)\b.{0,80}\b(?:email|e-mail|mail)\b", query)
    if not state and not (requested or email_request):
        return None
    if state and not (requested or email_request) and re.search(r"\b(?:show|find|search|browse)\b.{0,60}\b(?:flats?|houses?|plots?|homes?|properties|auctions?)\b", query):
        return {"state": {}, "reply": "", "action": None, "resume": True}
    def result(reply, action=None):
        return {"state": state, "reply": reply, "action": action}
    if re.search(r"\b(?:cancel|never mind|don't|do not|no thanks)\b|\bno\s+(?:(?:more|further|another|any)\s+)?(?:follow[- ]?ups?|reminders?|emails?)\b|வேண்டாம்", query) or query.strip() in {"no", "இல்லை"}:
        cancel_saved = bool(requested and not state and re.search(r"\bcancel\b", query))
        state.clear()
        value = result("சரி, follow-up சேமிக்கவில்லை." if tamil else "Okay, I haven’t saved a follow-up.")
        value["cancel_saved"] = cancel_saved
        return value
    if not state:
        state = {"summary": text[:500], "method": "email" if re.search(r"\b(?:email|e-mail|mail)\b|மின்னஞ்சல்", query) else "in_app"}
    elif re.search(r"\b(?:in[- ]app|browser)\b", query):
        state["method"] = "in_app"
        state.pop("timing", None)
    elif re.search(r"\b(?:email|e-mail)\b|[^\s@]+@[^\s@]+\.[^\s@]+", query):
        state["method"] = "email"
    if state["method"] == "email":
        address = re.search(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@.,!?]+", text)
        if address:
            state["email"] = address.group().rstrip(".,!?")
        if not state.get("email"):
            return result("எந்த மின்னஞ்சல் முகவரிக்கு அனுப்ப வேண்டும்?" if tamil else "Which email address should I use for the follow-up?")
        if state.get("stage") != "consent" or address:
            state["stage"] = "consent"
            return result((f"{state['email']} முகவரிக்கு 3 நாட்களில் ஒரு follow-up மின்னஞ்சல் அனுப்ப ஒப்புக்கொள்கிறீர்களா? அனுப்புதல் முடக்கப்பட்டிருந்தால் கோரிக்கை மட்டும் சேமிக்கப்படும்." if tamil else f"May I save one follow-up email to {state['email']} for three days from now? If email delivery is off, I’ll save the request for review without sending it."))
        if not re.fullmatch(r"[\W_]*(?:yes|yeah|sure|please|okay|ok|go ahead|ஆம்|ஆமாம்|சரி)[\W_]*", query):
            return result("மின்னஞ்சல் அனுப்ப ஒப்புதல் வேண்டுமா? ஆம் அல்லது வேண்டாம் என்று சொல்லுங்கள்." if tamil else "Please say yes to opt in, or cancel to stop.")
        return result("", dict(state))
    now = now or datetime.now(TZ)
    previous_timing = state.get("timing", "")
    # A newly stated day replaces the earlier day instead of competing with it.
    date_words = r"\d{4}-\d{2}-\d{2}|\btoday\b|\btomorrow\b|நாளை|இன்று|\b(?:next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\b(?:in|after) \d+ days?\b|\bnext week\b"
    if re.search(date_words, query):
        previous_timing = re.sub(date_words, "", previous_timing)
    time_words = r"\b(?:1[0-2]|[1-9])(?:[:.]\d{2})?\s*(?:am|pm)\b|\b(?:[01]?\d|2[0-3]):[0-5]\d\b"
    if re.search(time_words, query):
        previous_timing = re.sub(time_words, "", previous_timing)
    combined = query + " " + previous_timing
    clock = re.search(r"\b(1[0-2]|[1-9])(?:[:.](\d{2}))?\s*(am|pm)\b", combined)
    clock24 = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", combined) if not clock else None
    day = None
    date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", combined)
    if date:
        try:
            day = datetime.strptime(date.group(), "%Y-%m-%d").date()
        except ValueError:
            pass
    elif re.search(r"tomorrow|நாளை", combined):
        day = (now + timedelta(days=1)).date()
    else:
        weekday = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", combined)
        if weekday:
            target = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(weekday.group())
            day = (now + timedelta(days=(target - now.weekday()) % 7)).date()
            if day == now.date() and re.search(r"\bnext\s+" + weekday.group() + r"\b", combined):
                day += timedelta(days=7)
            if (clock or clock24) and day == now.date():
                hour = int(clock.group(1)) % 12 + (12 if clock.group(3) == "pm" else 0) if clock else int(clock24.group(1))
                minute = int(clock.group(2) or 0) if clock else int(clock24.group(2))
                if (hour, minute) <= (now.hour, now.minute):
                    day += timedelta(days=7)
        elif re.search(r"\btoday\b|இன்று", combined):
            day = now.date()
        else:
            days = re.search(r"\b(?:in|after) (\d+) days?\b", combined)
            if days:
                try:
                    day = (now + timedelta(days=int(days.group(1)))).date()
                except (ValueError, OverflowError):
                    day = None
            elif re.search(r"\bnext week\b", combined):
                day = (now + timedelta(days=7)).date()
    state["timing"] = combined.strip()
    if day is None or (clock is None and clock24 is None):
        return result("எந்த நாள், எந்த நேரத்தில் follow-up வேண்டும்? உதாரணம்: நாளை 10 AM (IST)." if tamil else "When should I follow up? For example, tomorrow at 10 AM (IST), or a date like 2026-10-15 at 6 PM.")
    hour = int(clock.group(1)) % 12 + (12 if clock.group(3) == "pm" else 0) if clock else int(clock24.group(1))
    minute = int(clock.group(2) or 0) if clock else int(clock24.group(2))
    try:
        due = datetime.combine(day, datetime.min.time(), tzinfo=TZ).replace(hour=hour, minute=minute)
    except ValueError:
        due = now
    if due <= now:
        state.pop("timing", None)
        return result("எதிர்கால நாள் மற்றும் நேரத்தைச் சொல்லுங்கள்." if tamil else "Please give me a future date and time for the follow-up.")
    return result("", {**state, "due_at": due.isoformat(timespec="minutes")})
