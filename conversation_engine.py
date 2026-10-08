"""Shared conversational state and grounded essential intents for AI and fallback."""
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

from conversation_memory import update_preferences
from buyer_memory import shown_records, resolve_reference

TZ = ZoneInfo("Asia/Kolkata")


def document_guidance_turn(query, language, answer, context, memory):
    """Helpful, bounded replies distilled from the approved Mira scenario library.

    These cover explanation and emotional-support questions before an AI provider is
    needed. They deliberately do not invent availability, rates, legal outcomes, or
    live portal actions.
    """
    def say(english, tamil, tanglish):
        return {"English": english, "Tamil": tamil, "Tanglish": tanglish}[language]

    if re.search(r"(?:(?:don't|do not) know (?:anything|where|what)|first[- ]time buyer|starting my search|start.*buying)", query):
        return answer("first_time_buyer",
            "That’s completely fine—many first-time buyers start there. A simple path is budget, loan comfort, shortlist, visit, document checks, then payment and registration. Would you like to start with budget or area?",
            "அது முற்றிலும் சரி. முதல் முறை வாங்குபவர்களுக்கு இது இயல்பானது. பட்ஜெட், கடன் வசதி, தேர்வு, நேரில் பார்வை, ஆவணச் சரிபார்ப்பு, பின்னர் பதிவு என்று படிப்படியாகப் பார்க்கலாம். பட்ஜெட்டிலா அல்லது பகுதியிலா தொடங்கலாம்?",
            "Adhu totally okay—first-time buyers neraya per ippadi thaan start pannuvaanga. Budget, loan comfort, shortlist, visit, documents check, apram payment and registration-nu step-by-step pogalaam. Budget-la illa area-la start pannalama?")
    if re.search(r"(?:just looking|just browsing|not sure what i want|exploring)", query):
        return answer("exploring",
            "No pressure. We can begin with either a rough area or a budget, and change it later. Which is easier to share?",
            "எந்த அழுத்தமும் இல்லை. ஒரு பகுதி அல்லது பட்ஜெட்டில் தொடங்கி பிறகு மாற்றிக்கொள்ளலாம். எது சொல்ல எளிதாக இருக்கும்?",
            "No pressure. Rough area illa budget rendu-la edhu easy-aa solla mudiyumo adhil start pannalaam; apram maathikkalaam.")
    if re.search(r"(?:set|choose|filter).{0,30}(?:my )?preferences|preferences.{0,20}(?:set|choose|filter)", query):
        memory["preference_setup_active"] = True
        return answer("preference_setup",
            "Let’s set your preferences one at a time: area, property type, BHK, budget, size, and sale or auction. Which city or area should we start with?",
            "உங்கள் விருப்பங்களை ஒவ்வொன்றாக அமைப்போம்: பகுதி, சொத்து வகை, BHK, பட்ஜெட், அளவு, விற்பனை அல்லது ஏலம். எந்த நகரம் அல்லது பகுதியில் தொடங்கலாம்?",
            "Preferences-ai one by one set pannalaam: area, property type, BHK, budget, size, sale illa auction. Endha city illa area-la start pannalaam?")
    if re.search(r"(?:need (?:a )?(?:flat|home|house).{0,12}(?:fast|urgent)|urgent.{0,20}(?:flat|home|house))", query):
        return answer("urgent_search",
            "I’ll keep this quick. Which area are you looking at?",
            "சுருக்கமாக உதவுகிறேன். எந்தப் பகுதியில் வீடு தேடுகிறீர்கள்?",
            "Quick-aa help panren. Endha area-la veedu thedureenga?")
    if re.search(r"(?:what (?:can|do) you help|what all can you help|what do you do)", query):
        return answer("scope",
            "I can help search the saved homes-for-sale records, explain home-loan and buying steps, retain your preferences, set a reviewable reminder, and help request an advisor callback. I can’t verify live availability, negotiate, make payments, or give legal or tax advice.",
            "சேமிக்கப்பட்ட விற்பனை வீட்டு பதிவுகளைத் தேடவும், வீட்டுக் கடன் மற்றும் வாங்கும் படிகளை விளக்கவும், உங்கள் விருப்பங்களை வைத்திருக்கவும், சரிபார்த்து சேமிக்கக்கூடிய நினைவூட்டலை முன்மொழியவும் உதவலாம். நேரடி கிடைப்பை உறுதிப்படுத்தவோ, விலை பேச்சுவார்த்தை நடத்தவோ, பணம் செலுத்தவோ, சட்ட அல்லது வரி ஆலோசனை வழங்கவோ முடியாது.",
            "Saved sale-listings search panna, home-loan/buying steps explain panna, preferences remember panna, review panni save panna reminder propose panna, advisor callback request help panna mudiyum. Live availability verify, negotiate, payment, legal/tax advice panna mudiyadhu.")
    if re.search(r"(?:salary|earn).{0,40}(?:buy|afford)|(?:can i afford|can i buy).{0,40}(?:lakh|crore|flat|home)", query):
        return answer("affordability",
            "It may be possible, but I can’t tell from salary alone. Existing EMIs, down payment, credit history and the loan term matter too. What down payment and monthly EMI would feel comfortable?",
            "சம்பளத்தை மட்டும் வைத்து உறுதியாகச் சொல்ல முடியாது. ஏற்கனவே உள்ள EMI, முன்பணம், கடன் வரலாறு, கடன் காலம் ஆகியவையும் முக்கியம். உங்களுக்கு வசதியான முன்பணம் மற்றும் மாத EMI எவ்வளவு?",
            "Salary mattum vechu sure-aa solla mudiyadhu. Existing EMI, down payment, credit history, loan term-um matter aagum. Comfortable-aana down payment, monthly EMI evlo?")
    if re.search(r"(?:stretch|increase).{0,30}(?:budget|price)|(?:better flat).{0,30}(?:budget|afford)", query):
        return answer("budget_tradeoff",
            "A higher budget can help, but only if the EMI still leaves room for regular costs and emergencies. I can compare saved prices within two budgets; what are the comfortable and stretch limits?",
            "அதிக பட்ஜெட் உதவலாம்; ஆனால் EMI, அன்றாட செலவுகள் மற்றும் அவசரத் தேவைகளுக்குப் பிறகும் வசதியாக இருக்க வேண்டும். இரண்டு பட்ஜெட்டில் உள்ள பதிவான விலைகளை ஒப்பிடலாம். உங்கள் வசதியான மற்றும் அதிகபட்ச வரம்பு என்ன?",
            "Higher budget help pannalaam, aana EMI-ku apram regular expense, emergency-ku space irukkanum. Rendu budget-la saved prices compare pannalaam. Comfortable limit, stretch limit enna?")
    if re.search(r"(?:which bank|best bank|fixed or floating|pre[- ]?approval|processing fee|prepayment)", query):
        return answer("loan_education",
            "There isn’t one best lender or loan type for everyone. Compare the current rate, processing fee, prepayment terms, reset terms, and the total cost for your profile; confirm the final terms with the lender. Which option are you considering?",
            "அனைவருக்கும் ஒரே சிறந்த வங்கியோ கடன் வகையோ இல்லை. தற்போதைய வட்டி, processing fee, முன்கூட்டியே செலுத்தும் விதிமுறைகள், மாற்றம் வரும் விதிமுறைகள் மற்றும் மொத்தச் செலவை ஒப்பிட்டு, இறுதி நிபந்தனைகளை வங்கியிடம் உறுதி செய்யுங்கள். எந்த விருப்பத்தைப் பார்க்கிறீர்கள்?",
            "Ellarukkum ore best bank/loan type illa. Current rate, processing fee, prepayment terms, reset terms, total cost compare panni lender-kitta final terms confirm pannunga. Endha option paakureenga?")
    if re.search(r"(?:cibil|credit score|low score|existing (?:car|personal) loan)", query):
        return answer("credit_guidance",
            "A lower credit score or an existing EMI can affect eligibility, but it isn’t an automatic rejection. Avoid guessing: check your current report, keep repayments current, and ask a lender what loan amount fits your full profile.",
            "குறைந்த credit score அல்லது ஏற்கனவே உள்ள EMI தகுதியை பாதிக்கலாம்; ஆனால் அது தானாக மறுப்பு அல்ல. ஊகிக்காமல் தற்போதைய அறிக்கையைப் பார்த்து, தவணைகளை நேரத்தில் செலுத்தி, உங்கள் முழு விவரத்திற்கு ஏற்ற கடன் தொகையை வங்கியிடம் கேளுங்கள்.",
            "Low credit score illa existing EMI eligibility-ai affect pannalaam, aana automatic rejection illa. Current report check panni, repayments on-time maintain panni, full profile-ku suitable loan amount lender-kitta kelunga.")
    if re.search(r"(?:title.{0,35}clear|encumbrance|\bec\b|patta|chitta|power of attorney|survey number.*(?:match|mismatch)|agricultural land|owner.*(?:aadhaar|address))", query):
        return answer("legal_verification",
            "That is too important to guess. I can explain the saved record, but a qualified property lawyer should verify title, approvals, encumbrances and the seller’s authority before money changes hands. I can’t share someone’s private address or identity documents.",
            "இது ஊகிக்கக் கூடாத முக்கியமான விஷயம். சேமித்த பதிவை விளக்கலாம்; ஆனால் பணம் செலுத்தும் முன் title, approvals, encumbrance மற்றும் விற்பவரின் அதிகாரத்தை தகுதியான சொத்து வழக்கறிஞர் சரிபார்க்க வேண்டும். ஒருவரின் தனிப்பட்ட முகவரி அல்லது அடையாள ஆவணங்களைப் பகிர முடியாது.",
            "Idhu guess panna koodaadha important matter. Saved record explain pannalaam; aana money kudukkara munna title, approvals, encumbrance, seller authority-ai qualified property lawyer verify pannanum. Private address/ID documents share panna mudiyadhu.")
    if re.search(r"(?:occupancy certificate|model flat|builder delay|under[- ]construction|ready[- ]to[- ]move)", query):
        return answer("project_due_diligence",
            "It’s sensible to check this before committing. A model flat may differ from the delivered home, and timelines or approvals need independent verification. Ask for the written specifications, possession terms and the project’s official registration details; have the agreement reviewed before signing.",
            "உறுதி செய்வதற்கு முன் இதைச் சரிபார்ப்பது நல்லது. Model flat கிடைக்கும் வீட்டிலிருந்து மாறுபடலாம்; காலக்கெடு மற்றும் அனுமதிகளை தனியாகச் சரிபார்க்க வேண்டும். எழுத்துப்பூர்வ specifications, possession terms மற்றும் அதிகாரப்பூர்வ project registration விவரங்களை கேட்டு, கையெழுத்துக்கு முன் ஒப்பந்தத்தை ஆய்வு செய்யுங்கள்.",
            "Commit pannara munna idha check pannradhu nalladhu. Model flat delivered home-oda differ aagalam; timeline/approvals independent-aa verify pannanum. Written specs, possession terms, official registration details kelunga; sign panna munna agreement review pannunga.")
    if re.search(r"(?:overwhelmed|exhausting|stress(?:ed)?|confused|too many (?:options|brokers)|scam|cheated|spam)", query):
        return answer("emotional_support",
            "That sounds exhausting. We can slow this down and work through one decision at a time. I won’t pressure you into a property or payment; would it help to narrow the search to your top two priorities?",
            "இது மிகவும் சோர்வாக இருப்பது புரிகிறது. ஒரு நேரத்தில் ஒரு முடிவாக மெதுவாகப் பார்க்கலாம். ஒரு சொத்து அல்லது பணம் செலுத்த அழுத்தம் கொடுக்க மாட்டேன். உங்கள் முக்கியமான இரண்டு விருப்பங்களுக்குள் தேடலைக் குறைக்கலாமா?",
            "Idhu romba exhausting-nu puriyudhu. Oru time-la oru decision-aa slow-aa paakalam. Property/payment-ku pressure panna maatten. Top two priorities-ku search narrow pannalama?")
    if re.search(r"(?:still available|availability|live availability)", query):
        return answer("availability",
            "I can only describe what the saved record says; I can’t confirm live availability. Please verify with the listing source or an advisor before arranging a visit or making plans.",
            "சேமித்த பதிவு சொல்வதை மட்டுமே விளக்க முடியும்; தற்போதைய கிடைப்பை உறுதிப்படுத்த முடியாது. நேரில் பார்வை அல்லது திட்டம் செய்வதற்கு முன் listing source அல்லது advisor மூலம் சரிபார்க்கவும்.",
            "Saved record-la irukkuradhai mattum solla mudiyum; live availability confirm panna mudiyadhu. Visit plan pannara munna listing source/advisor-kitta verify pannunga.")
    if re.search(r"(?:stamp duty|registration (?:cost|fee)|tax benefit|income tax)", query):
        return answer("current_costs",
            "Those amounts and rules can change, so I won’t quote them from memory. Use the current official registration or tax source, and confirm property-specific amounts with the registration office or a qualified professional.",
            "இந்தத் தொகைகளும் விதிமுறைகளும் மாறலாம்; நினைவில் இருந்து சொல்ல மாட்டேன். தற்போதைய அதிகாரப்பூர்வ பதிவு அல்லது வரி ஆதாரத்தைப் பயன்படுத்தி, குறிப்பிட்ட சொத்துக்கான தொகையை பதிவு அலுவலகம் அல்லது தகுதியான நிபுணரிடம் உறுதி செய்யுங்கள்.",
            "Indha amounts/rules change aagalam; memory-la irundhu quote panna maatten. Current official registration/tax source use panni, specific property amount-ai registration office illa qualified professional-kitta confirm pannunga.")
    if re.search(r"(?:random|do you actually know|can i trust|are you sure)", query):
        return answer("trust_boundary",
            "I’m an AI assistant, so I can be useful for the saved information and next steps, but I can be wrong or lack a live fact. I’ll say when something needs verification instead of making it up. What would you like me to check from the saved record?",
            "நான் AI உதவியாளர். சேமித்த தகவல் மற்றும் அடுத்த படிகளில் உதவலாம்; ஆனால் தவறாக இருக்கலாம் அல்லது நேரடி தகவல் இல்லாமல் இருக்கலாம். ஊகிக்காமல் சரிபார்க்க வேண்டியதைத் தெளிவாகச் சொல்வேன். சேமித்த பதிவிலிருந்து எதைப் பார்க்க வேண்டும்?",
            "Naan AI assistant. Saved information, next steps-la help pannalaam; aana wrong-aagalam illa live fact illaama irukkalam. Invent pannaama verify pannanum-nu clear-aa sollren. Saved record-la enna check pannanum?")
    return None


def response_language(text, previous="English"):
    query = text.casefold()
    if re.search(r"tanglish|தங்கிலிஷ்", query):
        return "Tanglish"
    if re.search(r"english (?:only|please)|in english|ஆங்கிலத்தில்", query):
        return "English"
    if re.search(r"tamil.*(?:mattum|only|pes|please)|தமிழில்|தமிழ்.*மட்டும்", query):
        return "Tamil"
    if previous != "English":
        return previous
    if re.search(r"enakku|vaanganum|venum|pann|podanum|pesunga|irukk|sollunga|veenaam|venaam", query):
        return "Tanglish"
    if re.search(r"[\u0b80-\u0bff]", text):
        return "Tamil"
    return previous


def conversational_turn(text, data, chat, context=None, memory=None, language="English", now=None):
    """Interpret current intent first; retain state independently of provider availability."""
    query = " ".join(text.casefold().replace("’", "'").split())
    previous_context = dict(context or {})
    replacement_property_type = bool(re.search(
        r"\b(?:add|set|keep|want|prefer)\s+(?:a\s+)?(?:flat|apartment|house|plot)\b",
        query,
    ))
    context = update_preferences(text, data, previous_context)
    # Apply explicit removals once more at the intent boundary so a parser
    # match in the same sentence cannot re-add a preference the customer just
    # removed.
    removal_clause = r"(?:remove|ignore|forget|drop|no longer want|don't want|do not want)[^.?!\n]{0,55}"
    if re.search(r"\b(?:remove|ignore|forget|drop|no longer want|don't want|do not want)\b[^.?!\n]{0,80}\b(?:flat|house|plot|property type)\b", query) and not replacement_property_type:
        context.pop("property_type", None)
    if re.search(r"(?:remove|ignore|forget|drop)[^.?!\n]{0,40}(?:flat|house|plot)", query) and not re.search(r"keep[^.?!\n]{0,20}(?:flat|house|plot)", query) and not replacement_property_type:
        context.pop("property_type", None)
    if re.search(rf"{removal_clause}(?:\d+\s*bhk|bedroom(?:s)?|bhk)\b", query) and not re.search(r"\bkeep\b[^.?!\n]{0,25}(?:\d+\s*bhk|bedroom(?:s)?|bhk)", query):
        context.pop("bedrooms", None)
    if re.search(rf"{removal_clause}(?:budget|lakh|crore|price)\b", query) and not re.search(r"\bkeep\b[^.?!\n]{0,25}(?:budget|lakh|crore|price|\d+\s*(?:lakh|crore))", query):
        context.pop("max_budget", None)
    replacement_area = re.search(r"\b(?:add|instead|replace|switch to)\s+(?:the\s+)?([a-z][a-z-]*)\b", query)
    if replacement_area and re.search(rf"{removal_clause}[^.?!\n]{{0,40}}(?:area|location|[a-z][a-z-]*)", query):
        candidate = replacement_area.group(1).strip()
        if candidate not in {"instead", "the", "area", "location", "flat", "apartment", "house", "plot", "bhk", "budget", "east", "east-facing", "facing"}:
            context["location"] = candidate.upper()
    memory = deepcopy(memory or {})
    for key, value in (("preferences", {}), ("rejected", []), ("corrections", []), ("selected", None)):
        memory.setdefault(key, value)
    language = response_language(text, memory.get("response_language", language))
    memory["response_language"] = language
    def say(english, tamil, tanglish):
        return {"English": english, "Tamil": tamil, "Tanglish": tanglish}[language]
    def answer(intent, english, tamil, tanglish, **actions):
        memory["last_intent"] = intent
        memory["requirements"] = dict(context)
        return {"reply": say(english, tamil, tanglish), "context": context, "memory": memory, "intent": intent, **actions}
    amount = re.search(r"(?:budget|around|under|within|maximum|up to).*?(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr)\b", query)
    if not amount:
        # Tanglish customers often put the amount before the noun: “50 lakh
        # budget”. Accept that natural order as the same budget preference.
        amount = re.search(r"(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr)\s*(?:budget|varamb[ue]|limit)?\b", query)
    if amount:
        context["max_budget"] = float(amount.group(1)) * (10000000 if amount.group(2).startswith("cr") else 100000)
    if re.search(r"flat|apartment|குடியிருப்பு", query) and not re.search(
        r"(?:remove|ignore|forget|drop|no longer want|don't want|do not want)[^.?!\n]{0,80}(?:flat|house|plot|property type)",
        query,
    ):
        context["property_type"] = "Flat"
    bhk = re.search(r"([1-9])\s*bhk", query)
    if bhk:
        context["bedrooms"] = int(bhk.group(1))
        if not context.get("_property_type_cleared"):
            context.setdefault("property_type", "Flat")
    workplace = re.search(r"(?:office|workplace)\s+([a-z][a-z ]{2,30}?)(?:\s+la|\s+is|[.,]|$)", query)
    if workplace:
        memory["workplace"] = workplace.group(1).strip().title()
    records = shown_records(chat)
    selected = resolve_reference(text, records, memory.get("selected"))
    if selected:
        memory["selected"] = selected
    selected = memory.get("selected")
    if re.fullmatch(r"[\W_]*(?:hi|hello|hey|good morning|good afternoon|good evening|vanakkam|வணக்கம்|ஹாய்)(?:[\s,]+mira)?[\W_]*", query):
        return answer("greeting", "Hi! What would you like help with today?", "வணக்கம்! இன்று எதில் உதவலாம்?", "Vanakkam! Innikku enna help venum?")
    if re.search(r"\b(?:thank(?:s| you)?|appreciate(?: it)?|that(?:'s| is) helpful|great suggestion|good suggestion|nice suggestion|good job|well done|awesome|super helpful)\b|நன்றி|ரொம்ப நல்லா", query):
        return answer(
            "appreciation",
            "Thank you—that means a lot. I’m glad the suggestion helped. What would you like to look at next?",
            "நன்றி! அந்தப் பரிந்துரை உதவியாக இருந்ததில் மகிழ்ச்சி. அடுத்து எதைப் பார்க்க விரும்புகிறீர்கள்?",
            "Thank you! Suggestion useful-aa irundhadhu sandhosham. Next enna paakalaam?",
        )
    if re.search(r"(?:explain|verify|check|review).{0,45}(?:listing|property).{0,70}(?:pay|payment|advance|before committing)|(?:listing|property).{0,70}(?:before paying|before payment|before committing)", query):
        return answer(
            "listing_verification",
            "To verify a listing before paying: confirm the current source listing and availability, check title and approval or RERA details, inspect the property, review written payment and refund terms, and have a qualified professional review the documents. Do not send an advance under pressure.",
            "பணம் செலுத்தும் முன் பட்டியலைச் சரிபார்க்கவும்: தற்போதைய மூலப் பதிவு மற்றும் கிடைப்பை உறுதி செய்து, title, approval அல்லது RERA விவரங்களைப் பாருங்கள்; சொத்தை நேரில் ஆய்வு செய்து, பணம் மற்றும் திருப்பித் தரும் நிபந்தனைகளை எழுத்துப்பூர்வமாகப் பெற்று, தகுதியான நிபுணரிடம் ஆவணங்களை ஆய்வு செய்யுங்கள். அழுத்தத்தில் முன்பணம் அனுப்ப வேண்டாம்.",
            "Payment panna munna listing verify pannunga: current source listing/availability confirm panni, title, approval/RERA details check pannunga; property visit panni, written payment/refund terms vaangi, qualified professional documents review pannattum. Pressure-la advance anuppaadheenga.",
        )
    if re.search(r"\b(?:email|e-mail|mail)\b.{0,50}\b(?:send|share|suggestion|suggestions|option|options|result|results|property|properties)\b|\b(?:send|share)\b.{0,50}\b(?:email|e-mail|mail)\b", query):
        return answer(
            "email_followup_request",
            "I can help you set up an email follow-up for the suggestions. I’ve opened Follow-ups: choose Email, enter the address you want to use, and explicitly opt in before anything is sent. I won’t send an email automatically.",
            "பரிந்துரைகளுக்கான மின்னஞ்சல் follow-up அமைக்க உதவுகிறேன். Follow-ups பகுதியைத் திறந்துள்ளேன்: Email தேர்வு செய்து, பயன்படுத்த வேண்டிய முகவரியை உள்ளிட்டு வெளிப்படையாக ஒப்புதல் அளிக்கவும். தானாக எந்த மின்னஞ்சலும் அனுப்பப்படாது.",
            "Suggestions-ku email follow-up set panna help panren. Follow-ups open pannirukken: Email select panni address enter panni explicit-aa opt-in pannunga. Automatic-aa email anuppa maatten.",
            open_followups=True,
        )
    remove_suggestions = bool(re.search(
        r"\b(?:remove|ignore|hide|delete|clear|skip|don't show|do not show)\b.{0,45}\b(?:suggestions?|options?|results?|recommendations?|previous (?:ones|suggestions?|results?))\b|"
        r"(?:இந்த|முந்தைய).{0,18}(?:பரிந்துரை|முடிவு|விருப்பம்).{0,18}(?:வேண்டாம்|நீக்கு|அகற்று)",
        query,
    ))
    if remove_suggestions:
        removed = 0
        for record in records:
            identifier = str(record.get("property_id") or record.get("title") or "")
            if identifier and identifier not in memory["rejected"]:
                memory["rejected"].append(identifier)
                removed += 1
        memory["selected"] = None
        return answer(
            "remove_suggestions",
            "I’ve removed the previous suggestions from this conversation and will not bring them back unless you ask. Would you like a fresh search with a different area, budget, or property type?",
            "முந்தைய பரிந்துரைகளை இந்த உரையாடலிலிருந்து நீக்கிவிட்டேன். நீங்கள் கேட்காமல் அவற்றை மீண்டும் காட்டமாட்டேன். வேறு பகுதி, பட்ஜெட் அல்லது சொத்து வகையுடன் புதிய தேடல் வேண்டுமா?",
            "Previous suggestions-ai remove pannitten; neenga ketkaama adha thirumba kaatta maatten. Different area, budget, illa property type-oda fresh search venuma?",
            removed_suggestions=removed,
        )
    # Capture non-catalogue constraints before returning the consolidated
    # preference acknowledgement, so later turns retain them as well.
    if re.search(r"lift.*(?:need|required|must|venum|வேண்டும்)|(?:need|required|must).*lift", query) and not re.search(r"(?:remove|ignore|forget|drop|don't need|not needed).*lift", query):
        memory["preferences"]["lift"] = "required"
    if re.search(r"hospital|மருத்துவமனை", query):
        memory["preferences"]["hospital_access"] = "verify"
    if re.search(r"east[- ]?facing|கிழக்கு", query):
        memory["facing"] = "East"
    if re.search(r"(?:remove|ignore|forget|drop|don't need|not needed).*lift", query):
        memory["preferences"].pop("lift", None)
    if re.search(r"(?:remove|ignore|forget|drop|don't need|not needed).{0,30}hospital", query):
        memory["preferences"].pop("hospital_access", None)
    explicit_search = bool(re.search(r"\b(?:find|search|show|list|browse|filter|refine|narrow)\b|காட்டு|தேடு", query))
    preference_signal = bool(re.search(
        r"\b(?:prefer|preference|want|need|keep|add|remove|ignore|forget|drop|set|under|around|near|bhk|bedroom|flat|house|plot|lift|hospital|east[- ]?facing|budget|lakh|crore)\b|விருப்பம்|வேண்டும்|பட்ஜெட்|அருகில்",
        query,
    ))
    context_changed = context != previous_context
    named_preference_change = bool(re.search(
        r"\b(?:remove|ignore|forget|drop|no longer want|don't want|do not want|add|also|keep|prefer)\b",
        query,
    ))
    if preference_signal and (context_changed or named_preference_change) and not explicit_search:
        # Collect all changes from one message, then invite the next change
        # instead of forcing the customer through a one-field-at-a-time loop.
        additions = []
        property_type_removed = bool(re.search(r"(?:remove|ignore|forget|drop)[^.?!\n]{0,60}(?:flat|house|plot)", query))
        property_type_added = bool(re.search(r"\b(?:add|set|keep|want|prefer)\s+(?:a\s+)?(?:flat|apartment|house|plot)\b", query))
        if context.get("location"):
            additions.append(str(context["location"]))
        if context.get("property_type") not in (None, "Any") and (not property_type_removed or property_type_added):
            additions.append(str(context["property_type"]))
        if context.get("bedrooms"):
            additions.append(f"{context['bedrooms']} BHK")
        if context.get("max_budget") is not None:
            additions.append(f"₹{context['max_budget'] / 100000:g} lakh budget")
        if re.search(r"lift", query) and not re.search(r"(?:remove|ignore|forget|drop|don't need|not needed).{0,30}lift", query):
            additions.append("a building with a lift")
        if re.search(r"hospital", query) and not re.search(r"(?:remove|ignore|forget|drop|don't need|not needed).{0,30}hospital", query):
            additions.append("hospital access")
        if re.search(r"east[- ]?facing|கிழக்கு", query):
            additions.append("east-facing")
        if memory.get("preferences", {}).get("lift") == "required" and "a building with a lift" not in additions:
            additions.append("a building with a lift")
        if memory.get("preferences", {}).get("hospital_access") == "verify" and "hospital access" not in additions:
            additions.append("hospital access")
        if memory.get("facing") == "East" and "east-facing" not in additions:
            additions.append("east-facing")
        removed = [label for key, label in (
            ("location", "the previous area"),
            ("property_type", "the previous property type"),
            ("bedrooms", "the previous BHK"),
            ("max_budget", "the previous budget"),
        ) if previous_context.get(key) and not context.get(key)]
        added_text = ", ".join(additions)
        removed_text = ", ".join(removed)
        mixed_frustration = bool(re.search(r"frustrat|not helpful|going in circles|slow|seekiram|கோப|புரியவில்லை", query))
        if language == "Tamil":
            reply = (("உங்களுக்கு இது சிரமமாக இருந்தது புரிகிறது. " if mixed_frustration else "")
                     + f"சரி, ஒரே செய்தியில் மாற்றிய விருப்பங்களைப் புதுப்பித்துவிட்டேன்: {added_text or 'புதிய விருப்பங்கள் இல்லை'}. "
                     f"{removed_text + ' நீக்கப்பட்டது. ' if removed_text else ''}அடுத்து வேறு விருப்பம் சேர்க்கவா அல்லது இந்த விருப்பங்களுடன் தேடவா?")
        elif language == "Tanglish":
            reply = (("Idhu frustrating-aa irundhadhu puriyudhu. " if mixed_frustration else "")
                     + f"Seri, ore message-la preferences update pannitten: {added_text or 'new preference illa'}. "
                     f"{removed_text + ' remove pannitten. ' if removed_text else ''}Next vera preference add pannalama, illa indha preferences-oda search pannalama?")
        else:
            reply = (("I hear you—this has been frustrating. " if mixed_frustration else "")
                     + f"Got it—I updated these preferences together: {added_text or 'no new preference'}. "
                     f"{removed_text + ' was removed. ' if removed_text else ''}Would you like to add another preference, or should I search with these now?")
        return answer("preference_update", reply, reply, reply)
    guidance = document_guidance_turn(query, language, answer, context, memory)
    if guidance:
        return guidance
    frustration_signal = bool(re.search(r"frustrat|not helpful|going in circles|slow|seekiram|கோப|புரியவில்லை", query))
    payment_concern_signal = bool(re.search(
        r"advance|deposit|token|முன்பணம்", query
    )) and bool(re.search(
        r"send|pay|transfer|anupp|urgent|செலுத்த|அனுப்ப", query
    ))
    search_request_signal = bool(re.search(
        r"\b(?:show|find|search|list|browse|recommend|suggest)\b.{0,70}"
        r"(?:property|properties|home|house|flat|apartment|plot|land|listing|bhk|option|வீடு|சொத்து|மனை)"
        r"|(?:property|properties|home|house|flat|apartment|plot|land|listing|bhk|வீடு|சொத்து|மனை).{0,70}"
        r"\b(?:show|find|search|list|browse|recommend|suggest)\b",
        query,
    ))
    # Payment requests are consequential: let the safety response below run
    # even when the customer also says they are frustrated or rushed.
    if frustration_signal and not payment_concern_signal:
        memory["emotion"] = "frustration signal"
        if not search_request_signal:
            return answer(
                "feedback_offer",
                "I’m sorry this has not been helpful. Tell me what Mira missed—such as the area, budget, language, or type of answer—and I’ll use that to improve this chat and adjust the next step.",
                "இது உதவியாக இல்லாததற்கு மன்னிக்கவும். பகுதி, பட்ஜெட், மொழி அல்லது பதிலின் வகை—Mira எதைத் தவறவிட்டது என்று சொல்லுங்கள்; இந்த உரையாடலை மேம்படுத்தி அடுத்த படியைச் சரிசெய்கிறேன்.",
                "Helpful-aa illa-nu ketka varuthama irukku. Area, budget, language, illa answer type-la Mira enna miss pannuchu-nu sollunga; indha chat-ai improve panni next step-ai adjust panren.",
                offer_feedback=True,
            )
    elif re.search(r"urgent|worried|கவலை|பயம்", query):
        memory["emotion"] = "concern signal"

    # Consequential questions take precedence over searches and buying preferences.
    if payment_concern_signal:
        return answer("payment_concern", "I’m sorry this feels urgent and stressful. Please pause before sending the advance under pressure. I can’t verify this payment request: independently confirm the seller, property documents, written payment/refund terms and recipient through trusted channels; have a qualified professional review the documents before committing money. Never share OTPs or banking credentials.",
            "அவசரப்படுத்துகிறார்கள் என்பதற்காக முன்பணத்தை அனுப்ப வேண்டாம். இந்தக் கோரிக்கையை என்னால் சரிபார்க்க முடியாது; விற்பவர், சொத்து ஆவணங்கள், எழுத்துப்பூர்வ பணம்/திருப்பித் தரும் நிபந்தனைகள் மற்றும் பெறுநரை தனியாக உறுதிப்படுத்தி, தகுதியான நிபுணரிடம் ஆவணங்களை ஆய்வு செய்யுங்கள். OTP அல்லது வங்கி ரகசியங்களைப் பகிர வேண்டாம்.",
            "Urgent-nu pressure panninaalum advance anuppa avasarappadaadheenga. Indha payment request-ai naan verify panna mudiyadhu; seller, property documents, written payment/refund terms, recipient-ai independent-aa check panni qualified professional review vaangunga. OTP, banking password share pannaadheenga.")
    if re.search(r"bye|goodbye|that's all|இன்னைக்கு போதும்|naalaiku pesalam|நாளை பேச", query):
        return answer("closing", "Of course—we’ll stop here. Take care! You can start a new conversation when you return.", "சரி, இன்றைக்கு இத்துடன் முடிக்கலாம். மீண்டும் வரும்போது புதிய உரையாடலைத் தொடங்கலாம். நன்றி!", "Seri, innikku inga mudichukkalaam. Naalaiku thirumbi vandha pudhu conversation start pannunga. Bye!", close=True)
    if re.search(r"remind|reminder|நினைவூட்ட|நினைவுபடுத்து", query):
        now = now or datetime.now(TZ)
        due = None
        weekday = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", query)
        clock = re.search(r"\b(1[0-2]|[1-9])(?:[:.](\d{2}))?\s*(am|pm)\b", query)
        if weekday and clock:
            day = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(weekday.group(1))
            hour = int(clock.group(1)) % 12 + (12 if clock.group(3) == "pm" else 0)
            due = (now + timedelta(days=(day - now.weekday()) % 7)).replace(hour=hour, minute=int(clock.group(2) or 0), second=0, microsecond=0)
            if due <= now:
                due += timedelta(days=7)
        if due:
            label = due.strftime("%d %b %Y, %I:%M %p IST")
            return answer("reminder", f"I can propose a browser-session reminder for {label}. Review it in Follow-ups and press Save follow-up to confirm; it isn’t saved yet and won’t notify you after this session ends.", f"{label} நேரத்திற்கு இந்த உலாவி அமர்வில் நினைவூட்டலை முன்மொழிகிறேன். Follow-ups பகுதியில் பார்த்து Save follow-up மூலம் உறுதிப்படுத்துங்கள்; இன்னும் சேமிக்கப்படவில்லை, அமர்வு முடிந்தால் அறிவிப்பு வராது.", f"{label}-ku in-app reminder propose panren. Follow-ups-la review panni Save follow-up press pannunga; innum save aagala, browser session mudinja notification varaadhu.", reminder_due=due.isoformat(), reminder_summary=text)
        return answer("reminder", "What date and time should I propose for the reminder? Please include your timezone.", "எந்த தேதி, நேரத்திற்கு நினைவூட்டல் வேண்டும்? நேர மண்டலத்தையும் சொல்லுங்கள்.", "Endha date, time-ku reminder venum? Timezone-um sollunga.", open_followups=True)
    if re.search(r"tanglish|tamil.*(?:mattum|pes|only)|தமிழில்|தமிழ்.*மட்டும்|in english|english only", query):
        return answer("language", "Of course—I’ll continue in English.", "நிச்சயமாக, இனிமேல் தமிழில் மட்டும் பேசுகிறேன்.", "Seri, inimel Tanglish-la pesalaam. Ungaloda preferences-ai marakka maatten.")
    if re.search(r"(?:loan|கடன்).*(?:guarantee|approve|approval|உறுதி)", query):
        return answer("loan_guarantee", "I can’t guarantee loan approval. The lender decides after checking eligibility, credit, income and property documents; I can help you prepare questions for the bank.", "கடன் ஒப்புதலுக்கு என்னால் உத்தரவாதம் தர முடியாது. தகுதி, வருமானம், கடன் வரலாறு மற்றும் சொத்து ஆவணங்களைச் சரிபார்த்து வங்கிதான் முடிவு செய்யும்; வங்கியிடம் கேட்க வேண்டிய கேள்விகளில் உதவலாம்.", "Loan approve aagum-nu guarantee kudukka mudiyadhu. Bank thaan income, eligibility, credit history, property documents check panni decide pannum; bank-kitta kekka vendiya questions prepare panna udhavalaam.")
    if re.search(r"real person|human or|robot|உண்மையான ஆள்|உண்மையான ஆளா", query):
        return answer("identity", "I’m Mira, an AI assistant, not a human. I can explain saved records, but I can’t personally inspect properties or confirm live availability.", "நான் Mira, ஒரு AI உதவியாளர்; மனிதர் அல்ல. சேமித்த விவரங்களை விளக்கலாம்; நேரில் ஆய்வு செய்யவோ தற்போதைய கிடைப்பை உறுதிப்படுத்தவோ முடியாது.", "Naan Mira, AI assistant; human illa. Saved details explain pannalaam, aana property-ai nerla inspect pannavo live availability confirm pannavo mudiyadhu.")
    if re.search(r"maintenance|பராமரிப்பு", query):
        value = str((selected or {}).get("maintenance_fee") or "").strip()
        if value:
            return answer("maintenance", f"The saved record reports maintenance as {value}; confirm the amount and billing period with the association.", f"சேமித்த பதிவில் பராமரிப்பு {value} என்று உள்ளது; தொகை மற்றும் கட்டண காலத்தை சங்கத்திடம் உறுதிப்படுத்துங்கள்.", f"Saved record-la maintenance {value}-nu irukku; amount, billing period association-kitta confirm pannunga.")
        return answer("maintenance", "The saved records don’t confirm monthly maintenance, so I can’t give you a sure amount. Ask the builder or association for the written monthly charges and what they include.", "மாத பராமரிப்புக் கட்டணம் சேமித்த பதிவுகளில் உறுதிப்படுத்தப்படவில்லை; நிச்சயமான தொகையைச் சொல்ல முடியாது. தொகை மற்றும் அதில் அடங்கும் சேவைகளை எழுத்துப்பூர்வமாக builder அல்லது சங்கத்திடம் கேளுங்கள்.", "Monthly maintenance saved records-la confirm aagala; sure-aa amount solla mudiyadhu. Builder/association-kitta written monthly charges-um enna include aagum-nu kelunga.")
    if re.search(r"rera|ரேரா", query):
        number = str((selected or {}).get("rera_number") or "").strip()
        return answer("rera", f"The selected record lists RERA reference {number}; verify it against the official Tamil Nadu RERA register. A saved number isn’t independent verification." if number else "I need the project name or a selected listing to check its saved RERA reference. Registration must still be verified on the official Tamil Nadu RERA register.",
            f"தேர்ந்தெடுத்த பதிவில் RERA குறிப்பு {number} உள்ளது; அதிகாரப்பூர்வ தமிழ்நாடு RERA பதிவில் சரிபார்க்க வேண்டும்." if number else "சேமித்த RERA குறிப்பைப் பார்க்க திட்டத்தின் பெயர் அல்லது தேர்ந்தெடுத்த பட்டியல் தேவை. அதிகாரப்பூர்வ தமிழ்நாடு RERA பதிவிலும் உறுதிப்படுத்த வேண்டும்.",
            f"Selected record-la RERA reference {number} irukku; official Tamil Nadu RERA register-la verify pannunga." if number else "Project name illa selected listing sollunga; saved RERA reference check pannalaam. Official Tamil Nadu RERA register-la confirm pannanum.")
    if re.search(r"owner.*(?:number|phone|contact|pesanum)|(?:number|contact).*owner|உரிமையாளர்.*(?:எண்|தொடர்பு)", query):
        contacts = [str((selected or {}).get(field) or "").strip() for field in ("public_contact_phone", "contact_phone", "listing_contact_phone")]
        contact = next((value for value in contacts if value), "")
        if contact:
            return answer("contact", f"The selected saved listing publishes {contact}; it isn’t independently verified or guaranteed current. I can’t guarantee that any agent fee is waived.", f"தேர்ந்தெடுத்த சேமித்த பட்டியலில் {contact} உள்ளது; தற்போதைய தொடர்பு உறுதிப்படுத்தப்படவில்லை. agent கட்டணம் விலக்கப்படும் என்றும் உறுதி தர முடியாது.", f"Selected saved listing-la {contact} irukku; current-aa irukka-nu verify pannunga. Agent fee waive aagum-nu guarantee illa.")
        return answer("contact", "I don’t have a verified owner number to share. Which listing or project do you mean? I can check its public contact fields or saved source link; I won’t invent a number.", "உறுதிப்படுத்தப்பட்ட உரிமையாளர் எண் என்னிடம் இல்லை. எந்தப் பட்டியல் அல்லது திட்டம்? அதன் பொதுத் தொடர்பு விவரங்கள் அல்லது மூல இணைப்பைப் பார்க்கலாம்; எண்ணை உருவாக்கிச் சொல்ல மாட்டேன்.", "Verified owner number ennidam illa. Endha listing/project-nu sollunga; public contact field illa source link check pannalaam. Number invent panna maatten.")
    if re.search(r"safe|night.*(?:women|girl|ponnunga)|பாதுகாப்பு", query):
        return answer("area_safety", "I understand why night-time safety matters. These records don’t establish personal safety, so I can’t guarantee it; check local information, lighting and transport, and inspect the surroundings with someone you trust.", "இரவு பாதுகாப்பு முக்கியம் என்பது புரிகிறது. இந்தப் பதிவுகளால் தனிநபர் பாதுகாப்பை உறுதிப்படுத்த முடியாது; உள்ளூர் தகவல், தெருவிளக்குகள், போக்குவரத்து ஆகியவற்றைப் பார்த்து நம்பகமான ஒருவருடன் சுற்றுப்புறத்தை ஆய்வு செய்யுங்கள்.", "Night safety mukkiyam-nu puriyudhu. Saved records-la personal safety verify panna mudiyadhu; guarantee kudukka maatten. Local information, street lights, transport check panni trusted person-oda area visit pannunga.")
    if re.search(r"ground floor.*(?:venaam|veenaam|vendam|don't|not)|(?:do not want|don't want|avoid|exclude|no|not|without)(?: a| the)? ground floor|தரை.*வேண்டாம்", query):
        memory["avoid_ground_floor"] = True
    elif re.search(r"ground floor.*(?:okay|fine|acceptable|paravailla)|include ground floor", query):
        memory["avoid_ground_floor"] = False
    if re.search(r"(?:don't need|no need for|remove).*lift|lift.*(?:venaam|vendam|not needed)", query):
        memory["preferences"].pop("lift", None)
    if re.search(r"lift.*(?:venum|thaan|must|required|வேண்டும்)|(?:need|must|required).*lift", query):
        memory["preferences"]["lift"] = "required"
    if re.search(r"east facing|கிழக்கு", query):
        memory["facing"] = "East"
    if re.search(r"hospital|மருத்துவமனை", query):
        memory["preferences"]["hospital_access"] = "verify"
        return answer("hospital_access", "I’ll keep hospital access as a priority for your family. The records don’t verify distances or travel times; which hospital or maximum distance should we check?", "உங்கள் குடும்பத்திற்காக மருத்துவமனை அணுகலை முக்கிய விருப்பமாக வைத்திருக்கிறேன். தூரம் அல்லது பயண நேரம் பதிவுகளில் உறுதிப்படுத்தப்படவில்லை; எந்த மருத்துவமனை அல்லது அதிகபட்ச தூரத்தைப் பார்க்க வேண்டும்?", "Parents-kaga hospital access priority-aa note panren. Saved records-la distance/travel time confirm aagala; endha hospital illa maximum distance check pannanum?")
    if re.search(r"vastu|வாஸ்து|east facing", query):
        return answer("facing", "I’ll retain east-facing as a requirement and check only recorded facing details. Facing alone doesn’t establish Vastu compliance; the plan needs separate review.", "கிழக்கு நோக்கைத் தேவையாக வைத்துப் பதிவில் உள்ள திசையை மட்டுமே சரிபார்ப்பேன். திசை மட்டும் வாஸ்து இணக்கத்தை நிரூபிக்காது; வரைபடத்தை தனியாக ஆய்வு செய்ய வேண்டும்.", "East-facing requirement-ai note panren; recorded facing mattum check pannalaam. Facing mattum vechu Vastu correct-nu guarantee panna mudiyadhu; floor plan separate-aa review pannanum.")
    if re.search(r"costly|too expensive|price.*reduce|குறைக்க முடியுமா", query):
        return answer("price_concern", "I understand the price feels high. I can compare recorded prices within your budget, but only the seller can agree to a discount; I can’t negotiate or promise one.", "விலை அதிகமாக இருப்பது புரிகிறது. உங்கள் பட்ஜெட்டிற்குள் பதிவான விலைகளை ஒப்பிடலாம்; தள்ளுபடிக்கு விற்பவர்தான் ஒப்புக்கொள்ள வேண்டும், என்னால் பேச்சுவார்த்தை நடத்தவோ உறுதி தரவோ முடியாது.", "Price adhigama irukku-nu puriyudhu. Ungal budget-kulla saved prices compare pannalaam; discount seller thaan agree pannanum, naan negotiate pannavo promise pannavo mudiyadhu.")
    if memory.get("avoid_ground_floor") and re.search(r"ground floor|lift", query):
        return answer("constraints", "I’ll exclude ground-floor listings and require recorded lift availability. Listings with missing floor or lift details cannot be treated as confirmed matches.", "தரைத் தளத்தைத் தவிர்த்து, lift இருப்பது பதிவில் உறுதியான பட்டியல்களையே பொருத்தமாகக் கருதுவேன். தளம் அல்லது lift விவரம் இல்லாதவற்றை உறுதிப்படுத்தப்பட்ட பொருத்தமாகக் காட்ட மாட்டேன்.", "Ground floor-ai avoid panren; lift irukku-nu recorded evidence venum. Floor/lift detail missing-na confirmed match-nu kaatta maatten.")
    if re.search(r"slow|seekiram|சீக்கிரம்|not listening|going in circles", query):
        return answer("frustration", "Sorry for the delay. I’ll keep this brief and retain your preferences; I can also help save a callback request for the support team if you prefer.", "தாமதத்திற்கு மன்னிக்கவும். சுருக்கமாகப் பதிலளித்து உங்கள் விருப்பங்களை வைத்திருக்கிறேன்; வேண்டுமெனில் ஆதரவு குழுவுக்கான தொடர்பு கோரிக்கையிலும் உதவலாம்.", "Delay-ku sorry. Short-aa sollren; ungal preferences marakkala. Neenga virumbina support team-kaga callback request save panna help pannalaam.")
    if amount and re.search(r"loan|கடன்", query):
        memory["loan_needed"] = True
        return answer("budget_loan", f"I’ve kept your budget at ₹{context['max_budget']/100000:g} lakh and noted that you need a loan. Which area would you prefer?" if not context.get("location") else f"I’ve kept your ₹{context['max_budget']/100000:g} lakh budget and {context['location']} preference, and noted the loan need. What locality would suit you best?", "₹45 லட்சம் பட்ஜெட்டையும் கடன் தேவையையும் வைத்திருக்கிறேன். எந்தப் பகுதியில் வீடு வேண்டும்?" if context.get("max_budget") == 4500000 else "பட்ஜெட்டையும் கடன் தேவையையும் வைத்திருக்கிறேன். எந்தப் பகுதி வேண்டும்?", f"₹{context['max_budget']/100000:g} lakh budget-um loan need-um note pannitten. Endha locality convenient-aa irukkum?")
    explicit_search = bool(re.search(r"\b(?:show|find|search|list|browse)\b|காட்டு|தேடு", query))
    buying = bool(re.search(r"vaanganum|venum|வேணும்|வாங்க|looking for|want to buy|need a flat|property to purchase|help me get started", query))
    if buying and not explicit_search:
        if not context.get("location"):
            return answer("gather_location", "Which city or locality would you prefer?", "எந்த நகரம் அல்லது பகுதியில் வீடு வேண்டும்?", "Endha city illa locality-la flat venum?")
        if not context.get("max_budget"):
            return answer("gather_budget", "What maximum budget should I keep in mind?", "அதிகபட்ச பட்ஜெட் எவ்வளவு?", "Maximum budget evlo-nu sollunga?")
    if not explicit_search and context.get("location") and re.search(r"பக்கத்துல|இருக்கணும்|office|near|preferred (?:area|location)", query):
        place = context["location"]
        workplace = memory.get("workplace", "")
        return answer("location_preference", f"I’ll keep {place} as your home location" + (f" and {workplace} as your workplace" if workplace else "") + ". Would you like me to search with your existing budget and BHK preferences?",
            f"வீட்டிற்கான பகுதி {place}" + (f", வேலை செய்யும் பகுதி {workplace}" if workplace else "") + " என்று தனியாக வைத்திருக்கிறேன். உங்கள் பட்ஜெட் மற்றும் BHK விருப்பங்களுடன் தேடவா?",
            f"Home location {place}" + (f", office {workplace}" if workplace else "") + "-nu separate-aa note pannitten. Ungal budget/BHK preferences-oda search pannalama?")
    memory["requirements"] = dict(context)
    return {"context": context, "memory": memory, "intent": "agent"}


def unavailable_reply(memory):
    """A truthful, useful fallback rather than repeatedly offering another search."""
    language = memory.get("response_language", "English")
    return {"English": "I’m having trouble answering that fully right now, but your preferences are still here. You can name a listing or ask about its price, amenities or source; I can also help with a callback request for the support team.",
            "Tamil": "இப்போது அந்தக் கேள்விக்கு முழுமையாகப் பதிலளிப்பதில் சிக்கல் உள்ளது; உங்கள் விருப்பங்கள் இங்கே உள்ளன. பட்டியலின் பெயர், விலை, வசதிகள் அல்லது ஆதாரம் பற்றி கேட்கலாம்; உரிமையாளர் பார்வைக்கு தொடர்பு கோரிக்கையிலும் உதவலாம்.",
            "Tanglish": "Indha question-ku full-aa answer panna ippo konjam difficulty irukku; ungal preferences inga irukku. Listing name, price, amenities illa source pathi kelunga; support team-kaga callback request-kum help pannalaam."}[language]
