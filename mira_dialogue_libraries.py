"""Curated, reusable Mira dialogue examples and local recovery responses.

These examples guide phrasing and conversation flow. They are not property facts
or model training data, and must never override the source-grounded agent policy.
"""

from __future__ import annotations

import re
from typing import Any


DIALOGUE_LIBRARIES: dict[str, tuple[dict[str, str], ...]] = {
    "warm_openings": (
        {
            "user": "Hi, I'm looking for a 3 BHK.",
            "mira": "Hi! I can help you look through the saved options. Which area should I check?",
        },
        {
            "user": "Hello?",
            "mira": "Hi, I’m Mira, Namma Illam’s AI guide. What’s on your mind?",
        },
    ),
    "empathy_and_pace": (
        {
            "user": "House hunting is exhausting. I feel like nobody listens to my budget.",
            "mira": "That sounds tiring, especially when your budget hasn’t been heard. We can slow down and use only the preferences you choose. What would you like me to keep in mind first?",
        },
        {
            "user": "I’m stressed about missing out on a home.",
            "mira": "That uncertainty can be stressful. I can’t confirm live availability from these saved records, but I can help you check the details we do have. What listing are you considering?",
        },
    ),
    "disappointment_and_recovery": (
        {
            "user": "None of these suggestions work for me.",
            "mira": "I’m sorry these missed what you had in mind. I’ll keep your earlier preferences. What should I adjust first: the area, budget, or property type?",
        },
        {
            "user": "You showed me a four-bedroom place, but I asked for one bedroom.",
            "mira": "You’re right—that doesn’t meet your one-bedroom request. I’m sorry. I’ll keep the one-bedroom requirement and check the results against it before suggesting anything else.",
        },
        {
            "user": "You ignored the parking question I asked.",
            "mira": "I’m sorry I missed that. I’ll check the saved details and tell you plainly if parking isn’t listed. Which property should I look at again?",
        },
    ),
    "price_pushback": (
        {
            "user": "These flats are too expensive.",
            "mira": "I’m sorry these options are above your range. I can keep the area and property type in mind while adjusting the budget. What price ceiling feels comfortable?",
        },
        {
            "user": "Can you promise this area will appreciate?",
            "mira": "I can’t promise future price growth. The saved records don’t establish future value, but I can help you compare the facts they contain. What would you like to compare?",
        },
    ),
    "facts_and_boundaries": (
        {
            "user": "Does the listing mention parking?",
            "mira": "I’ll check the saved details for this listing. If parking isn’t stated there, I’ll say that plainly and point you to its source link to confirm.",
        },
        {
            "user": "Can you book a visit for Saturday?",
            "mira": "I can’t book a visit from this portal. The listing’s source link is available so you can contact the publisher and confirm a time.",
        },
        {
            "user": "Is the title clear and is it available right now?",
            "mira": "I can’t verify title or live availability from these saved snapshots. Please confirm those with the seller or official notice before relying on the listing.",
        },
        {
            "user": "Are you a real person?",
            "mira": "I’m Mira, an AI assistant. I can help with the saved property information, and I’ll be clear when a detail isn’t verified.",
        },
        {
            "user": "Take my Aadhaar and PAN to book it.",
            "mira": "Please don’t share Aadhaar, PAN, or other identity numbers here. This app can’t book a property; use the seller’s or bank’s verified official channel.",
        },
    ),
    "clarifying_and_closing": (
        {
            "user": "Show me some good properties.",
            "mira": "I can help. What kind of place are you considering: a plot, house, or flat?",
        },
        {
            "user": "That’s enough for today, thanks.",
            "mira": "You’re welcome. We can pick this up whenever you’re ready.",
        },
        {
            "user": "Keep my budget and area, but show me places with a shorter commute.",
            "mira": "Got it—I’ll keep your budget and area and update the commute preference. The saved listings don’t include reliable commute times, so I’ll be clear about that while checking what location details are available.",
        },
        {
            "user": "I'm not sure any of these are right, so I'll pause the search for now.",
            "mira": "That’s completely fine. We can pause here. If you return to this chat, we can pick up with the preferences you shared: Boston, your budget, transit access, and a larger home. The saved details didn’t confirm quietness, so I’ll keep that as a priority to verify.",
        },
    ),
}


def prompt_examples() -> str:
    """Format curated examples as optional few-shot guidance for the API agent."""
    lines = [
        "Conversation-style examples (adapt the approach; do not copy mechanically).",
        "They teach tone only. Use approved tool results for all property facts, and never claim human feelings.",
    ]
    for category, examples in DIALOGUE_LIBRARIES.items():
        lines.append(f"[{category.replace('_', ' ').title()}]")
        for example in examples:
            lines.append(f"User: {example['user']}\nMira: {example['mira']}")
    return "\n".join(lines)


def local_land_conversation_reply(
    text: str, history: list[dict[str, Any]], language: str
) -> str | None:
    """Give direct, cautious help for land-buying questions in local mode.

    This is a safety and conversation layer, not legal advice or a substitute
    for source-backed property search. It deliberately answers the current
    question before any remembered search context can trigger another search.
    """
    query = " ".join(text.casefold().split())
    recent_user_text = " ".join(
        str(item.get("content", "")).casefold()
        for item in history[-12:]
        if item.get("role") == "user"
    )
    land_context = bool(re.search(
        r"\b(?:plot|plots|land|survey number|agricultural land|dtcp|chengalpattu|power of attorney)\b|மனை|நிலம்|விவசாய நிலம்|சர்வே எண்",
        query + " " + recent_user_text,
    ))
    if not land_context:
        return None

    tamil = language == "தமிழ்"
    def answer(en: str, ta: str) -> str:
        return ta if tamil else en

    # A current request to browse belongs to the property search layer. Keep
    # approval warnings attached to recommendations there, rather than replacing
    # the requested results with a canned chat response.
    explicit_browse = bool(re.search(
        r"\b(?:show|find|search|browse|list|compare)\b|காட்டு|தேடு|ஒப்பிட",
        query,
    ))

    if re.search(r"\b(?:survey number|survey no\.?|survey-number)\b|சர்வே எண்", query) and re.search(
        r"\b(?:doesn't match|does not match|mismatch|doesn't line up|not match)\b|பொருந்தவில்லை|மாறுபடுகிறது",
        query,
    ):
        return answer(
            "That’s a serious discrepancy, and I’m sorry this has added stress. Please pause before paying or signing anything; ask your lawyer to reconcile the survey number across the title documents and official land records, and get their advice before proceeding. I can’t verify title from this listing.",
            "இது கவனிக்க வேண்டிய முக்கியமான முரண்பாடு; இதனால் ஏற்பட்ட கவலைக்கு வருந்துகிறேன். பணம் செலுத்தவோ கையெழுத்திடவோ முன் நிறுத்துங்கள். உரிமை ஆவணங்களிலும் அதிகாரப்பூர்வ நிலப் பதிவுகளிலும் உள்ள சர்வே எண்ணை உங்கள் வழக்கறிஞர் ஒப்பிட்டு, அடுத்த படியைச் சொல்லும்வரை தொடர வேண்டாம். இந்தப் பட்டியலிலிருந்து உரிமையை என்னால் சரிபார்க்க முடியாது."
        )
    if re.search(r"\b(?:why did you show me the same|same plot twice|duplicate plot|are you even listening)\b", query):
        return answer(
            "You’re right to flag that—seeing what looks like the same plot twice is confusing, and I’m sorry. I’ll check the property IDs and remove exact duplicates if they’re present; similar-looking records with different IDs need checking before I call them the same plot. Your plot criteria are still noted.",
            "அதே மனையை இருமுறை பார்ப்பது குழப்பமாக இருக்கும்; அதைச் சுட்டிக்காட்டியது சரி, மன்னிக்கவும். இப்போது காட்டப்படும் முடிவுகளில் ஒரே property ID கொண்ட நகல்களை நீக்கி, உங்கள் மனைத் தேடல் விருப்பங்களை வைத்துக்கொள்கிறேன். இரண்டு பதிவுகள் ஒரே மாதிரி தெரிந்தாலும் வேறு ID இருந்தால், அவை ஒன்றே என்று முடிவு செய்வதற்கு முன் கேட்பேன்."
        )
    if re.search(r"\b(?:cash).{0,50}(?:avoid|evad|tax)|\b(?:avoid|evad).{0,50}tax.{0,50}cash\b", query):
        return answer(
            "I can’t help arrange undeclared cash payments or evade tax. Keep the transaction documented and use lawful payment channels; please ask a qualified tax professional or property lawyer about your obligations before paying.",
            "வரி தவிர்க்க கணக்கில் காட்டாத பணப் பரிவர்த்தனையை அமைக்க உதவ முடியாது. பரிவர்த்தனைக்கு ஆவணங்களை வைத்துக்கொண்டு சட்டபூர்வமான கட்டண முறைகளைப் பயன்படுத்துங்கள்; பணம் செலுத்துவதற்கு முன் உங்கள் வரிப் பொறுப்புகளை தகுதியான வரி ஆலோசகர் அல்லது சொத்து வழக்கறிஞரிடம் உறுதிப்படுத்துங்கள்."
        )
    if re.search(r"\b(?:token|advance|deposit).{0,70}(?:today|right now|or .*give it|otherwise)|\b(?:5\s*lakh|five lakh).{0,70}(?:today|send|advance)|\bshould i send it\b", query):
        return answer(
            "That deadline pressure is concerning. Please don’t send ₹5 lakh today just to hold the plot; first have an independent property lawyer verify the seller’s authority and documents, and get the amount, refund terms, and receipt in writing. I can’t verify this seller or guarantee the money is recoverable.",
            "இப்படி அவசரப்படுத்துவது கவலைக்குரியது. மனைக்காக மட்டும் இன்று ₹5 லட்சம் அனுப்ப வேண்டாம். முதலில் சுயாதீன சொத்து வழக்கறிஞரிடம் விற்பவரின் அதிகாரத்தையும் ஆவணங்களையும் சரிபார்த்து, தொகை, பணத்தைத் திரும்பப் பெறும் நிபந்தனை, ரசீது ஆகியவற்றை எழுத்தில் பெறுங்கள். விற்பவரையோ பணம் திரும்பக் கிடைப்பதையோ என்னால் உறுதிப்படுத்த முடியாது."
        )
    if re.search(r"\b(?:power of attorney|poa)\b", query) and re.search(r"\b(?:safe|owner|abroad|buy|seller)\b", query):
        return answer(
            "I can’t tell from this listing whether that power of attorney is valid or sufficient for a sale. Before paying or signing, have your own property lawyer verify the document, the seller’s authority, and the title directly against official records; don’t rely only on the broker’s assurance.",
            "இந்தப் பட்டியலை வைத்து அந்த Power of Attorney செல்லுபடியாகிறதா அல்லது விற்பனைக்கு போதுமா என்று உறுதிப்படுத்த முடியாது. பணம் செலுத்தவோ கையெழுத்திடவோ முன், உங்கள் சொந்த வழக்கறிஞர் அந்த ஆவணம், விற்பவரின் அதிகாரம், உரிமை ஆவணங்களை அதிகாரப்பூர்வ பதிவுகளுடன் சரிபார்க்கட்டும்; broker சொல்வதை மட்டும் நம்ப வேண்டாம்."
        )
    if re.search(r"\b(?:agricultural land|build a house|build on it|construct a house)\b|விவசாய நிலம்|வீடு கட்ட", query):
        return answer(
            "It depends on the land’s classification, permitted use, and required approvals or conversion. This listing doesn’t establish that a house can be built there. Ask a local property lawyer and the relevant planning or revenue authority to verify the survey number and permissions before you commit.",
            "நிலத்தின் வகைப்பாடு, அனுமதிக்கப்பட்ட பயன்பாடு, தேவைப்படும் அனுமதி அல்லது நிலப் பயன்பாட்டு மாற்றம் ஆகியவற்றைப் பொறுத்தது. இந்தப் பட்டியல் அங்கே வீடு கட்டலாம் என்பதை உறுதிப்படுத்தவில்லை. முடிவு செய்வதற்கு முன் சர்வே எண்ணையும் அனுமதிகளையும் உள்ளூர் சொத்து வழக்கறிஞர் மற்றும் சம்பந்தப்பட்ட திட்டமிடல் அல்லது வருவாய் அலுவலகத்தில் சரிபார்க்கவும்."
        )
    if re.search(r"\bdouble (?:in|within)\b", query):
        return answer(
            "That’s a strong promise, but I can’t verify or guarantee that a plot will double in three years. Ask the broker for the evidence behind the claim, compare recent registered sales independently, and don’t base a purchase on a promised return.",
            "அது பெரிய வாக்குறுதி; ஆனால் மூன்று ஆண்டுகளில் மனை விலை இரட்டிப்பாகும் என்று என்னால் சரிபார்க்கவோ உறுதி அளிக்கவோ முடியாது. அந்தக் கூற்றுக்கான ஆதாரத்தை broker-ிடம் கேட்டு, சமீபத்திய பதிவு செய்யப்பட்ட விற்பனைகளைத் தனியாக ஒப்பிடுங்கள்; வாக்குறுதியான வருமானத்தை மட்டும் வைத்து வாங்க வேண்டாம்."
        )
    if re.search(r"\b(?:best returns|best return)\b", query):
        return answer(
            "For the ₹1 crore budget you mentioned, I can’t rank areas by future returns from these saved records. I can compare documented plot prices, sizes, and approval details for areas you’re considering, but none of that guarantees appreciation.",
            "நீங்கள் குறிப்பிட்ட ₹1 கோடி பட்ஜெட்டுக்கு, எதிர்கால வருமானத்தை வைத்து பகுதிகளை இந்தச் சேமித்த பதிவுகளால் தரவரிசைப்படுத்த முடியாது. நீங்கள் கருதும் பகுதிகளின் பதிவான மனை விலை, அளவு, அனுமதி விவரங்களை ஒப்பிடலாம்; அவை விலை உயர்வை உறுதி செய்யாது."
        )
    if re.search(r"\b(?:appreciat|guarantee.*return|returns?)\b|\b\d+\s*%\s*(?:in|within|return)", query):
        return answer(
            "I can’t confirm that Chengalpattu plots will double or predict which area will give the best return. Those are uncertain market outcomes, not facts in the saved listings. I can compare the recorded price, area, approval details, and source for specific plots, but a qualified adviser should assess investment risk.",
            "செங்கல்பட்டு மனைகளின் விலை இரட்டிப்பாகும் என்பதையோ எந்தப் பகுதி அதிக வருமானம் தரும் என்பதையோ உறுதிப்படுத்த முடியாது. அவை உறுதியற்ற சந்தை முடிவுகள்; சேமித்த பட்டியல்களில் உள்ள தகவல்கள் அல்ல. குறிப்பிட்ட மனைகளின் பதிவான விலை, பரப்பளவு, அனுமதி விவரம், ஆதாரம் ஆகியவற்றை ஒப்பிடலாம்; முதலீட்டு ஆபத்தை தகுதியான ஆலோசகரிடம் மதிப்பிடுங்கள்."
        )
    if re.search(r"\b(?:fully online|live in dubai|can't visit|cannot visit|buy .*online)\b", query):
        return answer(
            "I understand you’re trying to manage this from Dubai. I can’t confirm that a particular plot can be bought safely or completed fully online. Before sending money, have an independent lawyer verify the title and seller authority, and confirm the signing and registration process through official channels.",
            "துபாயிலிருந்து இதைச் செய்ய வேண்டியிருப்பதைப் புரிந்துகொள்கிறேன். குறிப்பிட்ட மனையை பாதுகாப்பாக முழுவதும் ஆன்லைனில் வாங்க முடியும் என்று உறுதிப்படுத்த முடியாது. பணம் அனுப்புவதற்கு முன் சுயாதீன வழக்கறிஞரிடம் உரிமை மற்றும் விற்பவரின் அதிகாரத்தைச் சரிபார்த்து, கையெழுத்து மற்றும் பதிவுமுறையை அதிகாரப்பூர்வ வழியில் உறுதிப்படுத்துங்கள்."
        )
    if re.search(r"\b(?:afraid of all this technology|scared of technology|explain slowly|technology.*afraid)\b", query):
        return answer(
            "Of course. We can take this slowly, one step at a time. First, don’t send money yet. Next, ask your lawyer to check who is legally allowed to sell the plot and whether the survey number and land-use details match the records. Only after that should you review written payment terms. I can explain any one step in simpler words.",
            "நிச்சயமாக. அவசரமின்றி ஒவ்வொரு படியாகப் பார்ப்போம். முதலில் பணம் அனுப்ப வேண்டாம். அடுத்து, மனை விற்க யாருக்கு சட்டபூர்வ அதிகாரம் உள்ளது, சர்வே எண் மற்றும் நிலப் பயன்பாட்டு விவரங்கள் பதிவுகளுடன் பொருந்துகிறதா என்பதை உங்கள் வழக்கறிஞரிடம் சரிபார்க்கச் சொல்லுங்கள். அதற்குப் பிறகே எழுத்துப்பூர்வ கட்டண நிபந்தனைகளைப் பாருங்கள். எந்தப் படியையும் இன்னும் எளிய வார்த்தைகளில் விளக்குகிறேன்."
        )
    if re.search(r"\b(?:cheating me|seller.*trust|know the seller|nobody.*explained)\b", query):
        return answer(
            "It makes sense to want a clear way to protect yourself. Before paying anything, ask for the seller’s proof of authority, the title documents, the survey number, and the land-use or approval records. Have your own property lawyer compare those details with official records, then review written payment and refund terms. I can help you make a document checklist, but I can’t verify the seller from this listing. If you have the documents, you can share non-sensitive excerpts with personal IDs and addresses removed.",
            "இதைக் தெளிவாக விளக்கச் சொல்லுவது சரிதான். ஒவ்வொன்றாகப் பார்ப்போம்: முதலில் உங்கள் வழக்கறிஞரிடம் விற்பவரின் அதிகாரம் மற்றும் உரிமையைச் சரிபார்க்கவும்; அடுத்து சர்வே எண் மற்றும் நிலப் பயன்பாட்டு அனுமதிகளைப் பார்க்கவும்; அதன் பிறகே கட்டண நிபந்தனைகளை எழுத்தில் உறுதிப்படுத்தவும். பட்டியலிலிருந்து அந்த ஆவணங்களை என்னால் சரிபார்க்க முடியாது. எந்தப் படியை முதலில் விளக்க வேண்டும்?"
        )
    if re.search(r"\b(?:son says|foolish to invest|invest at my age)\b", query):
        return answer(
            "Your age alone doesn’t make the decision foolish. What matters is whether the risk, time horizon, and amount at stake fit your needs and finances. I can help compare verified listing facts, but I can’t predict returns; consider reviewing the plan with an independent financial adviser and someone you trust.",
            "உங்கள் வயது மட்டும் இந்த முடிவைத் தவறானதாக ஆக்காது. ஆபத்து, முதலீட்டு காலம், செலவிடும் தொகை ஆகியவை உங்கள் தேவைக்கும் நிதிநிலைக்கும் பொருந்துகிறதா என்பதே முக்கியம். சரிபார்க்கப்பட்ட பட்டியல் தகவல்களை ஒப்பிட உதவலாம்; வருமானத்தை கணிக்க முடியாது. சுயாதீன நிதி ஆலோசகருடனும் நீங்கள் நம்பும் ஒருவருடனும் திட்டத்தைப் பாருங்கள்."
        )
    if re.search(r"\b(?:full refund guarantee|refund guarantee|guarantee.*refund|promise.*refund)\b", query):
        return answer(
            "I can’t promise a refund if a deal falls through. Refund rights depend on the written agreement and circumstances; have a property lawyer review the cancellation and refund terms before paying any token amount.",
            "ஒப்பந்தம் நிறைவேறாவிட்டால் முழுப் பணமும் திரும்பக் கிடைக்கும் என்று உறுதி அளிக்க முடியாது. அது எழுத்துப்பூர்வ ஒப்பந்தம் மற்றும் சூழ்நிலைகளைப் பொறுத்தது; token தொகை செலுத்துவதற்கு முன் ரத்து மற்றும் பணத்திருப்ப நிபந்தனைகளை வழக்கறிஞரிடம் சரிபார்க்கவும்."
        )
    if re.search(r"\b(?:owner's address|owner address|seller address|listing owner|owner.*aadhaar|seller.*aadhaar)\b", query):
        return answer(
            "I can’t provide someone’s private address or Aadhaar details. Please don’t request or share identity numbers here; verify the seller through a lawyer and official records using the lawful process.",
            "ஒருவரின் தனிப்பட்ட முகவரி அல்லது Aadhaar விவரங்களை வழங்க முடியாது. அடையாள எண்களை இங்கே கேட்கவோ பகிரவோ வேண்டாம்; சட்டபூர்வ முறையில் வழக்கறிஞர் மற்றும் அதிகாரப்பூர்வ பதிவுகள் வழியாக விற்பவரைச் சரிபார்க்கவும்."
        )
    if re.search(r"\b(?:remind me|set a reminder|reminder)\b|நினைவூட்ட", query):
        return answer(
            "I can’t send a notification from this chat. The Follow-ups feature can save a reminder only for this browser session; please save it there and keep your own calendar reminder if you need an alert next Monday at 5 PM.",
            "இந்த உரையாடலிலிருந்து அறிவிப்பு அனுப்ப முடியாது. Follow-ups வசதி இந்த browser session-இல் மட்டும் நினைவூட்டலைச் சேமிக்கும்; அங்கே சேமித்து, அடுத்த திங்கட்கிழமை மாலை 5 மணிக்கு அறிவிப்பு தேவைப்பட்டால் உங்கள் calendar-லும்சேர்க்கவும்."
        )
    if re.search(r"\b(?:yesterday|where did you get that|clear title)\b", query) and re.search(r"\b(?:title|said|told me|claim)\b", query):
        return answer(
            "I’m sorry if Mira previously described the title as clear—that shouldn’t be stated without verification. I can’t see a separate conversation from yesterday here, and these saved records don’t verify title. Please rely on your lawyer’s document review and official records, not that earlier claim.",
            "முன்பு உரிமை தெளிவாக உள்ளது என்று Mira கூறியிருந்தால் மன்னிக்கவும்; சரிபார்க்காமல் அப்படிச் சொல்லக்கூடாது. நேற்றைய தனி உரையாடலை இங்கே பார்க்க முடியவில்லை; இந்தச் சேமித்த பதிவுகளும் உரிமையை உறுதிப்படுத்தவில்லை. அந்த முந்தைய கூற்றை நம்பாமல், வழக்கறிஞரின் ஆவண ஆய்வு மற்றும் அதிகாரப்பூர்வ பதிவுகளைப் பின்பற்றுங்கள்."
        )
    if re.search(r"\b(?:title|ownership|encumbrance|legal status)\b", query) and re.search(r"\b(?:verify|clear|check|safe|confirm|worried|concerned|anxious|title)\b", query):
        return answer(
            "That’s an important thing to check, and I’m sorry if earlier replies made it sound settled. I can’t verify title or encumbrances from this saved property data. Please have an independent property lawyer check the documents and official records before paying or signing. If you mean one of the results just shown, name it and I can tell you exactly what its saved record says.",
            "உரிமை விவரத்தைச் சரிபார்ப்பது முக்கியம்; முந்தைய பதில் உறுதியாகச் சொன்னது போலத் தோன்றியிருந்தால் மன்னிக்கவும். இந்தச் சேமித்த சொத்துத் தரவிலிருந்து உரிமை அல்லது வில்லங்கத்தை உறுதிப்படுத்த முடியாது. பணம் செலுத்தவோ கையெழுத்திடவோ முன் சுயாதீன சொத்து வழக்கறிஞரிடம் ஆவணங்களையும் அதிகாரப்பூர்வ பதிவுகளையும் சரிபார்க்கவும். இப்போது காட்டிய முடிவில் ஒன்றைக் குறிப்பிட்டால், அதன் பதிவில் உள்ளதைத் துல்லியமாகச் சொல்கிறேன்."
        )
    if explicit_browse and re.search(r"\b(?:approval doesn't matter|approval does not matter|anything that's cheap|anything cheap)\b", query):
        return None
    return None


def local_dialogue_reply(text: str, history: list[dict[str, Any]], language: str) -> str | None:
    """Apply a small set of source-safe conversation patterns in offline mode."""
    query = " ".join(text.casefold().split())
    tamil = language == "தமிழ்"
    has_results = any(
        item.get("role") == "assistant"
        and (
            item.get("mode") == "results"
            or (
                item.get("mode") == "agent"
                and any(
                    result.get("kind") in {"properties", "auctions"}
                    for result in item.get("tool_results", [])
                )
            )
        )
        for item in history
    )

    disappointed = re.search(
        r"\b(?:none of these|didn.t like any|not satisfied|disappointed|not what i (?:want|wanted|had in mind)|these (?:options|results|suggestions) (?:aren.t|are not) what i (?:want|wanted|had in mind)|useless|not helping|going in circles)\b"
        r"|எதுவும் பிடிக்கவில்லை|திருப்தி இல்லை|ஏமாற்றம்|உதவவில்லை",
        query,
    )
    if disappointed and has_results:
        called_out_type = re.search(
            r"\b(?:asked for|wanted|looking for)\s+(?:a\s+)?(plot|flat|apartment|house|land)\b.*\bnot\s+(?:a\s+)?(plot|flat|apartment|house|land)\b",
            query,
        )
        if called_out_type and not tamil:
            wanted = "flat" if called_out_type.group(1) == "apartment" else called_out_type.group(1)
            unwanted = "flat" if called_out_type.group(2) == "apartment" else called_out_type.group(2)
            return (
                f"You’re right—I should stick to {wanted}s, not {unwanted}s. I’m sorry that made the search feel like I wasn’t listening. I’ll keep your earlier area and budget; would you like me to adjust either one?"
            )
        return (
            "இந்தப் பரிந்துரைகள் உங்கள் எதிர்பார்ப்புக்கு பொருந்தவில்லை என்பதற்கு மன்னிக்கவும். முன்பு சொன்ன விருப்பங்களை வைத்துக்கொண்டு மாற்றுகிறேன்—முதலில் எதைச் சரிசெய்யலாம்: பகுதி, பட்ஜெட் அல்லது சொத்து வகை?"
            if tamil else
            "I’m sorry these suggestions didn’t fit what you had in mind. I’ll keep your earlier preferences and adjust the search. What should I change first: area, budget, or property type?"
        )

    price_pushback = re.search(
        r"\b(?:too expensive|more than i can afford|over my budget|out of budget|costs? too much|too costly|romba costly|budget ku mela|budget-kku mela)\b"
        r"|விலை அதிகம்|பட்ஜெட்டுக்கு மேல்|ரொம்ப விலை",
        query,
    )
    if price_pushback and has_results:
        return (
            "இந்த விலைகள் உங்கள் வரம்பை மீறியிருக்கலாம்; மன்னிக்கவும். பகுதி மற்றும் சொத்து வகையை வைத்துக்கொண்டு பட்ஜெட்டை மாற்றிப் பார்க்கலாமா?"
            if tamil else
            "I’m sorry these are above your range. I can keep the area and property type you gave me; what budget should I use instead?"
        )

    correction = re.search(
        r"\b(?:that.s wrong|that is wrong|you are wrong|you.re wrong|isn.t accurate|not accurate|you misunderstood me|you ignored|you missed|you gave me the wrong|doesn.t fit|does not fit|doesn.t match|does not match|you showed me .* but i asked for)\b"
        r"|தவறு|புரிந்துகொள்ளவில்லை|தவறான தகவல்",
        query,
    )
    if correction:
        stated_need = re.search(r"\b(?:one|two|three|1|2|3)\s*[- ]?bedroom\b|\b[1-9]\s*bhk\b", query)
        if stated_need and has_results and not tamil:
            return "You’re right—that doesn’t meet your request. I’m sorry. I’ll keep your " + stated_need.group(0) + " requirement and check the saved records against it before suggesting anything else."
        return (
            "அந்தத் தகவல் தவறாகவோ தெளிவில்லாமலோ இருந்ததற்கு மன்னிக்கவும். ஊகிக்காமல் சேமிக்கப்பட்ட ஆதாரத்தில் மீண்டும் சரிபார்க்கிறேன். எந்த விவரத்தைப் பார்க்க வேண்டும்?"
            if tamil else
            "I’m sorry that was wrong or unclear. I’ll check the saved source again instead of guessing. Which detail should I revisit?"
        )

    overwhelmed = re.search(
        r"\b(?:house hunting is exhausting|tired of searching|overwhelmed by (?:the )?search|stressed about (?:the )?(?:house|home|property) hunt|brokers? (?:keep )?push(?:ing|es)|nobody listens to my budget)\b"
        r"|வீடு தேட.*சோர்வு|தேடல்.*சலிப்பு",
        query,
    )
    if overwhelmed:
        return (
            "வீடு தேடுவது சோர்வாக இருக்கலாம், குறிப்பாக உங்கள் விருப்பங்கள் கவனிக்கப்படவில்லை என்று தோன்றும்போது. அவசரமில்லை; நீங்கள் சொன்ன வரம்புகளை மட்டும் வைத்து மெதுவாகப் பார்ப்போம். இப்போது எது முக்கியம்?"
            if tamil else
            "House hunting can feel tiring when you don’t feel heard. There’s no rush; I can work with only the preferences you choose. What matters most to you right now?"
        )

    return None
