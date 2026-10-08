"""Consent-based advisor requests; no call or appointment is promised."""
import re


def advisor_reply(text, state=None, tamil=False, handoff=False):
    state = dict(state or {})
    query = text.casefold().strip()
    def reply(english, tamil_text, stage=None):
        if stage:
            state["stage"] = stage
        return state, tamil_text if tamil else english
    callback = bool(re.search(r"\b(?:callback|call back|follow.up|call me|human only|prefer.*human)\b|பின்னர்.*அழை|தொடர்பு", query))
    decline = bool(re.fullmatch(r"(?:no|no thanks|not now|cancel|never mind|வேண்டாம்|இப்போது வேண்டாம்)[.! ]*", query))
    stage = state.get("stage")
    if stage and re.search(r"\b(?:help me instead|let'?s (?:keep chatting|continue)|forget the callback|no callback)\b", query):
        return {}, "சரி, கோரிக்கை சேமிக்கப்படவில்லை. எதில் உதவலாம்?" if tamil else "Of course—no callback request was saved. What would you like help with?"
    if decline and stage:
        return {}, "சரி, தொடர்பு கோரிக்கை சேமிக்கப்படவில்லை. வேறு உதவி வேண்டுமெனில் சொல்லுங்கள்." if tamil else "Of course—no callback request was saved. I’m here if you need anything else."
    if handoff and not stage:
        if callback:
            return reply("I can save a callback request for owner review, though a call isn’t guaranteed. How would you prefer to be contacted—phone or email?", "உரிமையாளர் பார்வைக்கு தொடர்பு கோரிக்கையைச் சேமிக்கலாம்; அழைப்பு உறுதியில்லை. தொலைபேசியிலா மின்னஞ்சலிலா தொடர்பு கொள்ள விரும்புகிறீர்கள்?", "method")
        return reply("A human advisor isn’t available through this app right now. Before we consider a follow-up, can I help another way—perhaps check a listing or explain a detail? If you prefer a callback request, just say so.", "இப்போது இந்தச் செயலியில் மனித ஆலோசகர் கிடைக்கவில்லை. பின்னர் தொடர்பு கோருவதற்கு முன், பட்டியலைச் சரிபார்ப்பது அல்லது விவரத்தை விளக்குவது போன்ற வேறு வழியில் உதவலாமா? பின்னர் தொடர்பு வேண்டுமெனில் சொல்லுங்கள்.", "offer_help")
    if not stage:
        return state, None
    if stage == "offer_help":
        if callback:
            return reply("I can save a request for owner review; it won’t confirm a call. Would you prefer phone or email?", "உரிமையாளர் பார்வைக்கு கோரிக்கையைச் சேமிக்கலாம்; அழைப்பை உறுதிப்படுத்தாது. தொலைபேசியா மின்னஞ்சலா?", "method")
        if re.fullmatch(r"(?:yes|sure|okay|ok|help me|ஆம்|சரி)[.! ]*", query):
            return reply("What would you like help with?", "எதில் உதவி வேண்டும்?")
        return {}, None  # A substantive question continues the ordinary chat.
    if stage == "method":
        if re.search(r"\b(?:phone|call|mobile)\b|தொலைபேசி", query):
            state["method"] = "Phone"
        elif re.search(r"\bemail\b|மின்னஞ்சல்", query):
            state["method"] = "Email"
        else:
            return reply("Would you prefer phone or email?", "தொலைபேசியா மின்னஞ்சலா?")
        return reply("What contact number or email should the owner use for this request?", "இந்தக் கோரிக்கைக்கு உரிமையாளர் பயன்படுத்த வேண்டிய தொலைபேசி எண் அல்லது மின்னஞ்சல் என்ன?", "contact")
    if stage == "contact":
        valid = re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text.strip()) if state["method"] == "Email" else re.fullmatch(r"\+?[\d ()-]{8,22}", text.strip())
        if not valid:
            return reply("Please enter a valid contact for your chosen method, or say cancel.", "தேர்ந்தெடுத்த முறைக்குச் சரியான தொடர்பை உள்ளிடுங்கள் அல்லது ரத்து செய்யுங்கள்.")
        state["contact"] = text.strip()
        return reply("When would you prefer a follow-up? Please include the day and time; this is a preference, not a booking.", "எந்த நாள், எந்த நேரத்தில் தொடர்பு விரும்புகிறீர்கள்? இது விருப்ப நேரம் மட்டுமே; முன்பதிவு அல்ல.", "time")
    if stage == "time":
        state["preferred_time"] = text.strip()[:200]
        return reply(f"May I save your {state['method'].lower()} contact and preferred time ({state['preferred_time']}) in the private owner dashboard for a callback request? A response isn’t guaranteed.", f"உங்கள் தொடர்பையும் விருப்ப நேரத்தையும் ({state['preferred_time']}) தனிப்பட்ட உரிமையாளர் டாஷ்போர்டில் சேமிக்கலாமா? பதில் உறுதியில்லை.", "confirm")
    if stage == "confirm":
        if re.fullmatch(r"(?:yes|yes please|confirm|save|save it|okay|ok|ஆம்|சரி)[.! ]*", query):
            state["stage"] = "confirmed"
            return reply("Your callback request is saved for owner review. Your preferred time isn’t a confirmed appointment, and a response isn’t guaranteed.", "உரிமையாளர் பார்வைக்கு தொடர்பு கோரிக்கை சேமிக்கப்பட்டது. விருப்ப நேரம் உறுதியான சந்திப்பு அல்ல; பதிலும் உறுதியில்லை.")
        return reply("Should I save this request, or cancel it?", "கோரிக்கையைச் சேமிக்கவா ரத்து செய்யவா?")
    return state, None
