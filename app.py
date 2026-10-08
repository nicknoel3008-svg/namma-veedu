"""Namma Illam — a local, chat-first Tamil Nadu property guide."""

from __future__ import annotations

from html import escape
from pathlib import Path
from datetime import datetime, timedelta
import base64
import hmac
import json
import logging
import os
import re
from uuid import uuid4
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from agent import friendly_reply, parse_request
from conversation_memory import update_preferences, contextual_reply
from ai_config import select_ai_config
from advisor_followup import advisor_reply
from buyer_memory import update_buyer_memory, shown_records as current_shown_records, record_detail_reply, prepare_inventory, grounded_search_reply
from mira_understanding import understand_request
from conversation_engine import conversational_turn, unavailable_reply
from agent_policy import (
    FRIENDLY_CMDA_NOTE,
    FRIENDLY_CMDA_NOTE_TAMIL,
    is_cmda_price_or_availability_question,
    is_pausing_property_search,
)
from agent_runtime import INDIA_TZ, run_openai_agent
from area_utils import convert_area, price_per_sqm
from followup_service import cancel_email_followup, cancel_followup_from_link, cancel_user_followups, email_config_ready, list_email_followups, schedule_email_followup
from inquiry_log import INQUIRY_ARCHIVE_DIR, INQUIRY_LOG_PATH, append_inquiry as local_append_inquiry, archive_inquiry_export, build_conversation_transcript_export, build_inquiry_export, customer_summary_rows, structured_archive_export, read_inquiries as local_read_inquiries, update_conversation_fields as local_update_conversation_fields, update_inquiry_fields as local_update_inquiry_fields
import storage_backend
from mira_dialogue_libraries import local_dialogue_reply, local_land_conversation_reply
from mira_quality import quality_flags
from mira_learning_library import active_learning_guidance, load_learning_rules as local_load_learning_rules, merge_suggested_drafts, save_learning_rules as local_save_learning_rules, suggested_draft_rules


def read_inquiries() -> list[dict]:
    return storage_backend.read_inquiries(local_read_inquiries)


def append_inquiry(record: dict) -> None:
    # Keep a local mirror when a database is configured so owner exports remain
    # available during local development; the database is the hosted source of truth.
    storage_backend.append_inquiry(record, local_append_inquiry)


def update_inquiry_fields(inquiry_id: str, fields: dict) -> bool:
    return storage_backend.update_inquiry_fields(inquiry_id, fields, local_update_inquiry_fields)


def update_conversation_fields(conversation_id: str, fields: dict) -> int:
    return storage_backend.update_conversation_fields(conversation_id, fields, local_update_conversation_fields)


def load_learning_rules() -> list[dict]:
    return storage_backend.load_learning_rules(local_load_learning_rules)


def save_learning_rules(rules: list[dict]) -> list[dict]:
    return storage_backend.save_learning_rules(rules, local_save_learning_rules)
from property_search import format_price_for_card, load_properties, rank_matches, search_properties

ROOT = Path(__file__).parent
SOURCE_FILE = ROOT / "data" / "sources.csv"


def _asset_data_uri(path: Path, mime_type: str) -> str:
    """Embed brand assets so hosted CSS is independent of static URL mounting."""
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:{mime_type};base64,{encoded}"


HERO_IMAGE_URL = _asset_data_uri(ROOT / "static" / "property-hero.png", "image/png")
WATERMARK_IMAGE_URL = _asset_data_uri(ROOT / "static" / "namma-illam-watermark.svg", "image/svg+xml")
LOGO_IMAGE_URL = _asset_data_uri(ROOT / "static" / "namma-illam-logo.svg", "image/svg+xml")
ASSISTANT_AVATAR = ROOT / "assets" / "assistant-guide.png"
PROPERTIES_FILE = ROOT / "data" / "properties.csv"
PRICE_NORMALIZER_VERSION = 3
SOFT_SEARCH_PREFERENCE_PATTERNS = {
    "balcony details": r"\bbalcon(?:y|ies)\b",
    "garden details": r"\bgardens?\b",
    "pool details": r"\bpools?\b|\bswimming\b",
    "bus or transit access": (
        r"\b(?:near|close to|with)\s+(?:(?:a|the)\s+)?"
        r"(?:public transport|transit|metro|train|bus)(?:\s+(?:route|stop|station))?\b"
        r"|\bpublic transport access\b"
    ),
    "a quieter area": r"\b(?:quiet(?:er)?|peaceful|calm|noisy|less noisy)\b",
}


def remember_soft_search_preferences(text: str) -> list[str]:
    """Keep amenities users mention, even when saved records cannot filter on them."""
    normalized = " ".join(text.casefold().split())
    remembered = list(st.session_state.get("soft_search_preferences", []))
    for label, pattern in SOFT_SEARCH_PREFERENCE_PATTERNS.items():
        if re.search(pattern, normalized) and label not in remembered:
            remembered.append(label)
    st.session_state.soft_search_preferences = remembered
    return remembered


def keep_mira_chat_at_latest() -> None:
    """Keep a new reply in view without removing access to older messages."""
    components.html(
        """
        <script>
          const panel = window.parent.document.querySelector('.st-key-mira-content-wash');
          if (panel) {
            const showLatest = () => { panel.scrollTop = panel.scrollHeight; };
            requestAnimationFrame(showLatest);
            setTimeout(showLatest, 80);
          }
        </script>
        """,
        height=0,
        width=0,
    )


@st.cache_data(show_spinner=False)
def cached_properties(file_version: int, current_date: str, normalizer_version: int) -> pd.DataFrame:
    """Reuse parsed property records until the CSV or auction date changes."""
    return load_properties(PROPERTIES_FILE)


@st.cache_data(show_spinner=False)
def cached_sources(file_version: int) -> pd.DataFrame:
    """Reuse parsed sources until the source CSV changes."""
    return pd.read_csv(SOURCE_FILE, keep_default_na=False)


def cached_inquiries(file_version: int, file_size: int) -> list[dict]:
    """Read current inquiry data from the configured persistent backend."""
    return read_inquiries()


def configured_value(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, "") or os.environ.get(name, default) or default)
    except Exception:
        return os.environ.get(name, default)


st.set_page_config(page_title="Namma Illam | Tamil Nadu Property Guide", page_icon="⌂", layout="wide", initial_sidebar_state="expanded")
AI_PROVIDER, AI_API_KEY, AI_MODEL = select_ai_config(configured_value)
FOLLOWUP_EMAIL_CONFIG = {
    key: configured_value(key)
    for key in (
        "FOLLOWUP_SMTP_HOST", "FOLLOWUP_SMTP_PORT", "FOLLOWUP_SMTP_USERNAME",
        "FOLLOWUP_SMTP_PASSWORD", "FOLLOWUP_SMTP_FROM", "FOLLOWUP_PUBLIC_URL",
    )
}
FOLLOWUP_EMAIL_READY = email_config_ready(FOLLOWUP_EMAIL_CONFIG)


def owner_dashboard_password() -> str:
    """Read the owner-only dashboard password from Streamlit secrets."""
    try:
        return str(st.secrets.get("OWNER_DASHBOARD_PASSWORD", "") or "")
    except Exception:
        return ""


def is_local_owner_request() -> bool:
    """Allow the owner console only from this computer's loopback address."""
    try:
        host = str(st.context.headers.get("host", "")).strip().casefold()
    except Exception:
        return False
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    else:
        host = host.split(":", 1)[0]
    return host in {"127.0.0.1", "localhost", "::1"}


configured_dashboard_password = owner_dashboard_password()
owner_request_is_local = is_local_owner_request()
if "owner_dashboard_authenticated" not in st.session_state:
    st.session_state.owner_dashboard_authenticated = False
if "owner_dashboard_login_open" not in st.session_state:
    st.session_state.owner_dashboard_login_open = False
if not owner_request_is_local:
    # A public tunnel can serve the customer experience, but never the owner
    # sign-in or the private inquiry dashboard.
    st.session_state.owner_dashboard_authenticated = False
    st.session_state.owner_dashboard_login_open = False
if "user_id" not in st.session_state:
    st.session_state.user_id = f"NMI-USER-{uuid4().hex[:12].upper()}"
st.session_state.setdefault("customer_name", "")
st.session_state.setdefault("preferred_form_of_address", "")
st.session_state.setdefault("awaiting_address_preference", True)
st.session_state.setdefault("conversation_started_at", datetime.now(INDIA_TZ).isoformat(timespec="seconds"))
st.session_state.setdefault("conversation_closed", False)
st.session_state.setdefault("end_chat_confirmation_pending", False)
st.session_state.setdefault("conversation_close_reason", "")
st.session_state.setdefault("conversation_ended_at", "")
st.session_state.setdefault("mira_rating", None)
st.session_state.setdefault("mira_rating_saved", False)
st.session_state.setdefault("followup_schedule", {})

try:
    followup_stop_token = str(st.query_params.get("stop_followup", "") or "")
except Exception:
    followup_stop_token = ""
if followup_stop_token:
    if cancel_followup_from_link(followup_stop_token):
        st.session_state.followup_schedule = {**st.session_state.get("followup_schedule", {}), "status": "Stopped by user", "next_at": ""}
        st.success("Your scheduled Namma Illam follow-up emails have been stopped.")
    else:
        st.info("There are no active follow-up emails for this link.")
    try:
        del st.query_params["stop_followup"]
    except Exception:
        pass

with st.sidebar:
    st.markdown(f'<div class="language-heading">{"மொழி விருப்பம்" if st.session_state.get("language") == "தமிழ்" else "Language preference"} <span>மொழி</span></div>', unsafe_allow_html=True)
    language = st.selectbox("Language / மொழி", ["English", "தமிழ்"], key="language", label_visibility="collapsed")

# Keep a visible confirmation when the user changes languages mid-conversation.
# Historical user-authored text remains verbatim; current UI and Mira replies use
# the newly selected language immediately.
previous_chat_language = st.session_state.get("chat_language_applied")
if previous_chat_language and previous_chat_language != language:
    st.session_state.language_switch_notice = language
st.session_state.chat_language_applied = language

TAMIL_UI = {
    "Any": "அனைத்தும்", "English": "ஆங்கிலம்", "Plot": "மனை", "House": "வீடு", "Flat": "அடுக்குமாடி வீடு",
    "Existing sale": "விற்பனைப் பதிவு", "Project reference": "திட்டத் தகவல்", "Auction": "ஏலம்", "Auction ended": "ஏலம் முடிந்தது", "Auction date not listed": "ஏலத் தேதி குறிப்பிடப்படவில்லை",
    "Find your kind of place": "உங்களுக்கான இடத்தைத் தேடுங்கள்", "Choose what matters to you": "உங்களுக்கு முக்கியமானதைத் தேர்ந்தெடுக்கவும்",
    "City or district": "நகரம் அல்லது மாவட்டம்", "Property type": "சொத்து வகை", "Listing kind": "பட்டியல் வகை",
    "Preferred budget (₹ lakh)": "விருப்பமான பட்ஜெட் (₹ லட்சம்)", "Preferred size (m²)": "விருப்பமான அளவு (மீ²)",
    "Include ended auctions": "முடிந்த ஏலங்களையும் சேர்க்கவும்", "Choose filters and results will update automatically.": "வடிகட்டிகளைத் தேர்ந்தெடுத்தால் முடிவுகள் தானாகப் புதுப்பிக்கப்படும்.",
    "Apply filters": "வடிகட்டிகளைப் பயன்படுத்து", "Filters changed. Apply them to refresh results.": "வடிகட்டிகள் மாறியுள்ளன. முடிவுகளைப் புதுப்பிக்க அவற்றைப் பயன்படுத்துங்கள்.",
    "Set a preferred budget": "விருப்பமான பட்ஜெட்டை அமைக்கவும்", "Set a preferred size": "விருப்பமான அளவை அமைக்கவும்",
    "Set a bedroom count": "படுக்கையறை எண்ணிக்கையை அமைக்கவும்", "Bedrooms (BHK)": "படுக்கையறைகள் (BHK)",
    "Choose locations": "பகுதிகளைத் தேர்ந்தெடுக்கவும்", "Choose property types": "சொத்து வகைகளைத் தேர்ந்தெடுக்கவும்", "Choose listing kinds": "பட்டியல் வகைகளைத் தேர்ந்தெடுக்கவும்",
    "Search locations": "பகுதிகளைத் தேடுங்கள்", "All": "அனைத்தும்", "Include ended auctions in this search": "இந்தத் தேடலில் முடிந்த ஏலங்களையும் சேர்க்கவும்", "No locations match": "பொருந்தும் பகுதிகள் இல்லை", "Showing the first 40 locations; type more to narrow the list.": "முதல் 40 பகுதிகள் காட்டப்படுகின்றன; பட்டியலைச் சுருக்க மேலும் தட்டச்சு செய்யுங்கள்.",
    "Mira Studio": "மீரா ஸ்டூடியோ", "Mira Studio sign-in": "மீரா ஸ்டூடியோ உள்நுழைவு", "Close sign-in": "உள்நுழைவை மூடு", "Include all districts": "அனைத்து மாவட்டங்களையும் சேர்க்கவும்",
    "A careful note": "கவனிக்க வேண்டியது", "Language preference": "மொழி விருப்பம்",
    "Chat": "உரையாடல்", "Property search": "சொத்து தேடல்", "Auction properties": "ஏலச் சொத்துகள்",
    "Home loans": "வீட்டுக் கடன்", "Area & price": "அளவும் விலையும்", "Sources": "ஆதாரங்கள்", "Follow-ups": "தொடர் நினைவூட்டல்கள்",
    "Browse by listing type": "பட்டியல் வகையைத் தேர்ந்தெடுக்கவும்", "All listings": "அனைத்துப் பட்டியல்கள்", "Sale & projects": "விற்பனை மற்றும் திட்டங்கள்",
    "Here when you’re ready": "நீங்கள் தயாராகும் போது இங்கே இருக்கிறேன்", "Share what’s on your mind, at your own pace.": "உங்கள் மனதில் இருப்பதை உங்கள் வேகத்தில் பகிருங்கள்.",
    "Browse the saved property list": "சேமிக்கப்பட்ட சொத்துப் பட்டியலைப் பாருங்கள்", "Search results": "தேடல் முடிவுகள்", "Reported area": "பதிவான பரப்பளவு",
    "Property": "சொத்து", "Price / reserve": "விலை / முன்பதிவுத் தொகை", "Starting price": "தொடக்க விலை",
    "Exact price": "துல்லியமான விலை", "Reported rate": "பதிவான விகிதம்", "Published prices": "வெளியிடப்பட்ட விலைகள்",
    "Not provided": "வழங்கப்படவில்லை", "Price not provided": "விலை வழங்கப்படவில்லை", "Not reported": "பதிவாகவில்லை",
    "Project directory entry; this does not confirm an available individual unit.": "இது திட்டப் பட்டியல் குறிப்பு மட்டுமே; தனிப்பட்ட வீடு தற்போது கிடைப்பதை இது உறுதிப்படுத்தாது.",
    "Saved sale listing; prior ownership and current availability are not independently verified.": "சேமிக்கப்பட்ட விற்பனைப் பதிவு; முந்தைய உரிமையும் தற்போதைய கிடைப்பும் தனியாகச் சரிபார்க்கப்படவில்லை.",
    "Matches your area": "நீங்கள் விரும்பிய பகுதியுடன் பொருந்துகிறது", "Within budget": "பட்ஜெட்டுக்குள் உள்ளது",
    "Property type and available details": "சொத்து வகையும் கிடைத்த விவரங்களும்",
    "Open source / verify details ↗": "ஆதாரத்தைத் திறந்து விவரங்களைச் சரிபார்க்கவும் ↗",
    "Showing {count:,} matches. Auctions past their end date are hidden unless you enable them in the sidebar.": "{count:,} பொருத்தங்கள் காட்டப்படுகின்றன. பக்கப்பட்டியில் தேர்வு செய்யாவிட்டால் முடிந்த ஏலங்கள் மறைக்கப்படும்.",
    "No records match these filters. Try widening the location, budget, or size.": "இந்த வடிகட்டிகளுக்கு பதிவுகள் பொருந்தவில்லை. பகுதி, பட்ஜெட் அல்லது அளவை விரிவுபடுத்திப் பாருங்கள்.",
    "Explore auction properties": "ஏலச் சொத்துகளைப் பாருங்கள்", "Home loan helper": "வீட்டுக் கடன் உதவி",
    "Official lender information": "வங்கிகளின் அதிகாரப்பூர்வ தகவல்", "Make area and price easier to compare": "அளவையும் விலையையும் எளிதாக ஒப்பிடுங்கள்",
    "Official places to verify details": "விவரங்களைச் சரிபார்க்க அதிகாரப்பூர்வ தளங்கள்", "Your follow-up reminders": "உங்கள் தொடர் நினைவூட்டல்கள்",
}

def tr(text: str) -> str:
    return TAMIL_UI.get(text, text) if language == "தமிழ்" else text


def localized_listing_title(value: str) -> str:
    """Translate generic listing descriptors while preserving names and place names."""
    if language != "தமிழ்":
        return value
    replacements = (
        (r"\bAgriculture Land\b", "விவசாய நிலம்"), (r"\bFarm House\b", "பண்ணை வீடு"),
        (r"\bIndividual House\b", "தனி வீடு"), (r"\bIndustrial Plot\b", "தொழிற்சாலை மனை"),
        (r"\bPlot\b", "மனை"), (r"\bLand\b", "நிலம்"), (r"\bHouse\b", "வீடு"), (r"\bFlat\b", "அடுக்குமாடி வீடு"),
        (r"\bfor sale in\b", "விற்பனைக்கு ·"), (r"\bsq feet\b", "சதுர அடி"),
        (r"\bsq ft\b", "சதுர அடி"), (r"\bacres?\b", "ஏக்கர்"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value


TAMIL_PLACE_NAMES = {
    "Chennai": "சென்னை", "Coimbatore": "கோயம்புத்தூர்", "Madurai": "மதுரை", "Trichy": "திருச்சி",
    "Tiruchirappalli": "திருச்சிராப்பள்ளி", "Salem": "சேலம்", "Erode": "ஈரோடு", "Vellore": "வேலூர்",
    "Tiruvallur": "திருவள்ளூர்", "Kancheepuram": "காஞ்சிபுரம்", "Kanchipuram": "காஞ்சிபுரம்",
    "Chengalpattu": "செங்கல்பட்டு", "Tirunelveli": "திருநெல்வேலி", "Dindigul": "திண்டுக்கல்",
    "Thoothukudi": "தூத்துக்குடி", "Krishnagiri": "கிருஷ்ணகிரி", "Dharmapuri": "தருமபுரி",
    "Namakkal": "நாமக்கல்", "Ranipet": "ராணிப்பேட்டை", "Tirupathur": "திருப்பத்தூர்",
    "Tiruppur": "திருப்பூர்", "Villupuram": "விழுப்புரம்", "Cuddalore": "கடலூர்",
    "Thanjavur": "தஞ்சாவூர்", "Kanniyakumari": "கன்னியாகுமரி", "Kanyakumari": "கன்னியாகுமரி",
    "Tenkasi": "தென்காசி", "Ariyalur": "அரியலூர்", "Karur": "கரூர்", "Perambalur": "பெரம்பலூர்",
    "Pudukkottai": "புதுக்கோட்டை", "Sivaganga": "சிவகங்கை", "Virudhunagar": "விருதுநகர்",
    "Ramanathapuram": "ராமநாதபுரம்", "Nilgiris": "நீலகிரி", "The Nilgiris": "நீலகிரி",
}


def localized_place_name(value: str) -> str:
    if language != "தமிழ்":
        return value
    for english, tamil in sorted(TAMIL_PLACE_NAMES.items(), key=lambda item: len(item[0]), reverse=True):
        value = re.sub(rf"\b{re.escape(english)}\b", tamil, value, flags=re.IGNORECASE)
    return value.replace("Not Published", "வெளியிடப்படவில்லை")


def localized_price_text(value: str) -> str:
    value = tr(value)
    if language != "தமிழ்":
        return value
    return re.sub(r"\b(lakh|lakhs)\b", "லட்சம்", value, flags=re.IGNORECASE).replace(" onwards", " முதல்")


def select_all_auction_types() -> None:
    """Keep the BAANKNET All checkbox mutually exclusive with individual types."""
    for property_type in ("Plot", "House", "Flat"):
        st.session_state[f"auction_type_{property_type.casefold()}"] = False


def select_specific_auction_type() -> None:
    st.session_state.auction_type_all = False

_base_styles = """
<style>
:root{--navy:#102D35;--teal:#007B78;--teal-bright:#009C98;--coral:#F05D43;--cream:#FFF8EB;--paper:#FFFFFF;--ink:#17313A;--muted:#435A60;--line:#C7DCD6;color-scheme:light}
.stApp{background-color:#102631;background-image:url('__WATERMARK_IMAGE__'),url('__HERO_IMAGE__');background-position:center 48vh,center center;background-size:min(72vw,900px),cover;background-repeat:no-repeat;background-attachment:fixed;color:#F4F7F4}
div[data-testid="stAppViewContainer"],section[data-testid="stMain"],section[data-testid="stMain"]>div{background:transparent!important}
html,body,[class*="css"]{font-family:'Aptos','Segoe UI',Arial,sans-serif;color:var(--ink)}
.block-container{max-width:1320px;padding:1.15rem 1.45rem 2rem;background:transparent!important;border:0;border-radius:24px;box-shadow:none;backdrop-filter:none}
header[data-testid="stHeader"]{background:transparent!important}
.hero{min-height:286px;padding:22px 26px;border-radius:22px;background-image:linear-gradient(90deg,rgba(9,28,37,.78) 0%,rgba(9,28,37,.48) 48%,rgba(9,28,37,.08) 100%),linear-gradient(0deg,rgba(9,28,37,.42),transparent 48%),url('__HERO_IMAGE__');background-size:cover;background-position:center 58%;border:1px solid #FFFFFFA8;position:relative;overflow:hidden;margin-bottom:14px;display:flex;flex-direction:column;justify-content:space-between;box-shadow:0 16px 36px #16343B20}
.hero-topline{display:flex;align-items:center;justify-content:space-between;color:#fff;font-size:13px;font-weight:700;letter-spacing:.03em}
.hero-brand{display:flex;align-items:center;gap:9px;padding:3px 0;border:0;border-radius:13px;background:transparent;box-shadow:none}.hero-brand img{display:block;width:min(310px,48vw);height:auto;filter:drop-shadow(0 3px 9px #091C25A0)}.hero-mark{display:grid;place-items:center;width:34px;height:34px;border-radius:11px;background:var(--coral);font-size:19px}.hero-pill{border:1px solid #FFFFFF80;border-radius:20px;padding:7px 12px;background:transparent;font-size:11px;text-shadow:0 1px 5px #091C25}
.hero-main{max-width:570px;margin:32px 0 22px}.eyebrow{letter-spacing:.16em;text-transform:uppercase;font-size:10px;font-weight:800;color:#FFB19F}
.hero h1{font:800 clamp(34px,5vw,58px)/1.02 'Aptos Display','Aptos','Segoe UI',sans-serif;letter-spacing:-.045em;margin:12px 0;color:#fff}.hero h1 em{font-style:normal;color:#FFD1C7}.hero .hero-main p{margin:0;color:#F7FBF9;font-size:15px;line-height:1.65;max-width:480px;text-shadow:0 1px 5px #07192080}
.hero-cta{display:inline-flex;align-items:center;gap:12px;margin-top:19px;padding:11px 16px;border-radius:12px;background:var(--coral);color:#fff!important;font-size:12px;font-weight:800;text-decoration:none!important;box-shadow:0 7px 18px #091C2535}.hero-cta:hover{background:#D94F3B}
.hero-panel{position:absolute;right:24px;bottom:22px;width:min(320px,32%);padding:15px 16px;border-radius:17px;background:transparent;color:var(--ink);border:1px solid #FFFFFFB0;border-top:4px solid var(--coral);box-shadow:none;backdrop-filter:none}
.hero-panel-top{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:9px;font-weight:800;letter-spacing:.12em;color:#FFFFFF;text-shadow:0 1px 7px #091C25}.hero-ai{padding:4px 8px;border-radius:20px;background:transparent;color:#FFFFFF;letter-spacing:.02em}
.hero-panel h2{font:750 20px/1.15 'Aptos Display','Aptos','Segoe UI',sans-serif;margin:12px 0 6px;color:#FFFFFF;text-shadow:0 1px 8px #091C25}.hero-panel p{font-size:12px;line-height:1.5;color:#FFFFFF;text-shadow:0 1px 8px #091C25;margin:0}
.hero-steps{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:15px;padding-top:13px;border-top:1px solid #FFFFFF75}.hero-step strong{display:block;color:#FF9B7E;font-size:14px;text-shadow:0 1px 5px #091C25}.hero-step span{font-size:9px;line-height:1.3;color:#FFFFFF;text-shadow:0 1px 7px #091C25}
.trust-row{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 18px}.trust-pill{font-size:10px;background:transparent;border:1px solid transparent;border-radius:20px;padding:7px 11px;color:#102D35;text-shadow:0 1px 4px #FFFFFF}
.section-kicker{font-size:10px;color:var(--teal);letter-spacing:.12em;text-transform:uppercase;font-weight:800}
.property-title{font:700 16px 'Aptos Display','Aptos','Segoe UI',sans-serif;color:var(--ink);margin-bottom:4px}
.property-sub,.small,.footnote{font-size:12px;color:#53666B}.small,.footnote{font-size:11px}
.price{font-size:19px;font-weight:750;color:var(--teal)}
.status{display:inline-block;border:1px solid #FFFFFF90;border-radius:20px;padding:4px 9px;font-size:10px;font-weight:700;background:transparent;color:#07575B}
.status.auction{background:transparent;color:#394B9B}.status.expired{background:transparent;color:#445258}.status.sale{background:transparent;color:#8E3E2F}.status.undated{background:#FFF1CF;color:#744A00}
.block-container{color:#102D35;text-shadow:0 1px 4px rgba(255,255,255,.92)}
.block-container h1,.block-container h2,.block-container h3,.block-container h4,.block-container h5,.block-container h6{color:#102D35!important;font-weight:800!important;text-shadow:0 1px 5px rgba(255,255,255,.98),0 0 10px rgba(255,255,255,.72)}
.block-container [data-testid="stMarkdownContainer"] p,.block-container [data-testid="stMarkdownContainer"] li,.block-container [data-testid="stCaptionContainer"],.block-container [data-testid="stCaptionContainer"] p{color:#183840!important;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.75)}
.block-container [data-testid="stCaptionContainer"],.block-container [data-testid="stCaptionContainer"] p,section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{font-size:12px!important;line-height:1.5!important}
.block-container label,.block-container [data-testid="stMetricLabel"],.block-container [data-testid="stMetricValue"]{font-weight:700!important;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.78)}
.property-title{color:#102D35;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.8)}
.property-sub,.small,.footnote{color:#203C43;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.8)}
.price{color:#006C68;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.8)}
.status{color:#064E50;text-shadow:0 1px 3px rgba(255,255,255,.98)}
[data-testid="stTabPanel"]:has([data-testid="stChatInput"]){padding:16px;border:1px solid transparent;border-radius:20px;background:transparent!important;box-shadow:none}
[data-testid="stChatMessage"]{width:100%;box-sizing:border-box;background:transparent!important;border:1px solid #FFFFFF75;border-radius:17px;padding:12px 14px;box-shadow:none;backdrop-filter:none;color:#102D35!important;font-size:14px;line-height:1.55;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.78)}
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]){background:transparent!important;border-color:#F2A48E}
div[data-testid="column"]:has([data-testid="stChatMessage"]){align-self:start;background:transparent!important;border:1px solid transparent;border-radius:20px;padding:14px;box-shadow:none;backdrop-filter:none}
[data-testid="stForm"]:has([data-testid="stFormSubmitButton"]){background:transparent!important;border:1px solid #FFFFFF70!important;border-radius:14px!important;padding:10px!important;box-shadow:none!important}
[data-testid="stButton"] button{background:var(--coral)!important;color:#FFFFFF!important;border:1px solid var(--coral)!important;border-radius:12px!important;box-shadow:0 4px 12px #843A2C1A!important;font-weight:750!important;min-height:46px!important;transition:all .16s ease}
[data-testid="stButton"] button p{color:#FFFFFF!important}
[data-testid="stButton"] button:hover{background:#D9513B!important;border-color:#D9513B!important;transform:translateY(-1px)}
[data-testid="stButton"] button:focus{box-shadow:0 0 0 3px #EF684F55!important}
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li{color:var(--ink)}
[data-testid="stMetric"] label{color:#52656A!important}
[data-testid="stMetricValue"]{color:var(--teal)!important}
section[data-testid="stSidebar"]{background:transparent!important;border-right:0!important;backdrop-filter:none}
section[data-testid="stSidebar"]>div,section[data-testid="stSidebar"] [data-testid="stSidebarContent"]{max-height:calc(100vh - 3.5rem)!important;min-height:0!important;overflow-y:auto!important;overscroll-behavior:contain;scrollbar-gutter:stable;background:transparent!important;color:#102D35;backdrop-filter:none}
section[data-testid="stSidebar"] .st-key-filter-panel-scroll{height:auto!important;max-height:none!important;min-height:0!important;overflow:visible!important;overscroll-behavior:auto}
section[data-testid="stSidebar"] .st-key-filter-panel-scroll::-webkit-scrollbar{width:11px}
section[data-testid="stSidebar"] .st-key-filter-panel-scroll::-webkit-scrollbar-track{background:#FFF3E3;border-radius:10px}
section[data-testid="stSidebar"] .st-key-filter-panel-scroll::-webkit-scrollbar-thumb{background:#D88D72;border:2px solid #FFF3E3;border-radius:10px}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar{width:9px}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb{background:#D88D72;border:2px solid #FFF3E3;border-radius:10px}
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3,section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] label,section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"]{color:#102D35!important;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.85)}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#183840!important;opacity:1!important;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.85)}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"]>div,section[data-testid="stSidebar"] [data-testid="stNumberInput"] input,section[data-testid="stSidebar"] [data-testid="stTextInput"] input{background:transparent!important;color:#102D35!important;border:1px solid #527D75!important;border-radius:10px!important}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] *{color:#102D35!important;opacity:1!important;text-shadow:0 1px 3px rgba(255,255,255,.98)}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"],section[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"] *{color:#102D35!important;-webkit-text-fill-color:#102D35!important;opacity:1!important;text-shadow:0 1px 3px rgba(255,255,255,.98)}
section[data-testid="stSidebar"] [data-testid="stNumberInput"] button{background:#E85D43!important;color:#FFFFFF!important;border-color:#E85D43!important}
section[data-testid="stSidebar"] [data-testid="stNumberInput"] button svg{fill:#FFFFFF!important}
section[data-testid="stSidebar"] [data-testid="stForm"]{background:transparent!important;border:1px solid transparent!important;border-radius:16px!important;padding:11px!important;box-shadow:none!important;backdrop-filter:none}
.filter-heading{display:flex;align-items:center;gap:10px;margin:0 0 12px;padding:10px 11px;border-radius:12px;background:transparent!important;border-left:2px solid #087C78}
.filter-heading-icon{display:grid;place-items:center;width:31px;height:31px;flex:0 0 31px;border-radius:10px;background:transparent;color:#087C78;font-weight:800}
.filter-heading-copy{display:flex;flex-direction:column;gap:2px}.filter-heading-title{color:#17313A;font-weight:800;font-size:15px;line-height:1.2;background:transparent!important}.filter-heading-subtitle{color:#3E565B;font-size:11px;line-height:1.3}
.language-heading{display:flex;align-items:center;justify-content:space-between;margin:0 0 7px;padding:8px 11px;border-radius:10px;background:transparent!important;color:#102D35;font-size:12px;font-weight:750;letter-spacing:.01em}.language-heading span{color:#45645F;font-size:11px;font-weight:650}
::selection{background:#FFD0C2;color:#17313A}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"]:focus-within,section[data-testid="stSidebar"] [data-testid="stNumberInput"]:focus-within{outline:3px solid #009C9844!important;border-color:#007B78!important}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label{color:#17313A!important}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label>div:first-of-type{width:19px!important;height:19px!important;min-width:19px!important;border:2px solid #167A76!important;border-radius:5px!important;background:#FFFFFF!important;box-shadow:0 1px 2px #102D3520!important}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked)>div:first-of-type{background:#007B78!important;border-color:#007B78!important}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked)>div:first-of-type svg{fill:#FFFFFF!important;color:#FFFFFF!important}
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label:focus-within>div:first-of-type{outline:3px solid #F05D4370!important;outline-offset:2px!important}
div[data-testid="stMetric"]{background:transparent!important;border:1px solid #FFFFFF70;border-top:2px solid #16847F;padding:10px 13px;border-radius:13px;box-shadow:none;backdrop-filter:none}
div[data-testid="stMetric"] label{color:#52656A!important;font-size:11px!important;font-weight:650!important}
div[data-testid="stMetricValue"]{color:#087C78!important;font-size:19px!important;font-weight:800!important}
div[data-testid="stVerticalBlockBorderWrapper"]{border-color:#FFFFFF70!important;background:transparent!important;border-radius:17px;box-shadow:none;transition:transform .16s ease,box-shadow .16s ease;backdrop-filter:none}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{box-shadow:none}
[data-testid="stTabs"] button{color:#355056!important}
[data-testid="stTabs"] button[aria-selected="true"]{color:var(--teal)!important;border-bottom-color:var(--coral)!important}
[data-testid="stImage"] img{border-radius:22px;box-shadow:0 10px 30px #18383C18}
.ai-label{display:inline-block;margin:0 0 5px;padding:4px 10px;border-radius:20px;background:#BCEBE0;color:#064E50;font-size:10px;font-weight:800;letter-spacing:.04em}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{color:#183840!important;text-shadow:0 1px 4px rgba(255,255,255,.98),0 0 8px rgba(255,255,255,.82)}
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input,[data-testid="stSelectbox"] div,[data-testid="stTextArea"] textarea{color:#102D35!important;background:transparent!important;font-weight:650!important;text-shadow:0 1px 3px rgba(255,255,255,.98)}
[data-testid="stTextInput"] input::placeholder,[data-testid="stTextArea"] textarea::placeholder{color:#354F54!important;opacity:1!important;text-shadow:0 1px 3px rgba(255,255,255,.98)}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#53666B!important}
/* Transparent panels let the softened property photo and teal watermark show through. */
.block-container{font-family:'Segoe UI','Nirmala UI',Arial,sans-serif!important;color:#102D35!important;text-shadow:0 1px 2px rgba(255,255,255,.9)!important;-webkit-font-smoothing:antialiased}
.block-container h1,.block-container h2,.block-container h3,.block-container h4,.block-container h5,.block-container h6{color:#102D35!important;font-weight:800!important;text-shadow:0 1px 3px rgba(255,255,255,.92)!important;font-family:'Segoe UI Semibold','Segoe UI','Nirmala UI',Arial,sans-serif!important}
.block-container [data-testid="stMarkdownContainer"] p,.block-container [data-testid="stMarkdownContainer"] li,.block-container [data-testid="stCaptionContainer"],.block-container [data-testid="stCaptionContainer"] p,.block-container label{color:#142F36!important;text-shadow:0 1px 3px rgba(255,255,255,.94)!important;font-size:15px!important;line-height:1.55!important}
.block-container [data-testid="stCaptionContainer"],.block-container [data-testid="stCaptionContainer"] p{font-size:13px!important;color:#203C43!important}
.block-container .property-title{color:#102D35!important;font-size:17px!important;font-weight:750!important;text-shadow:0 1px 3px rgba(255,255,255,.96)!important}
.block-container .property-sub,.block-container .small,.block-container .footnote{color:#203C43!important;font-size:12px!important;text-shadow:0 1px 3px rgba(255,255,255,.96)!important}
.block-container .price{color:#00635F!important;font-weight:800!important;text-shadow:0 1px 3px rgba(255,255,255,.96)!important}
.block-container [data-testid="stChatMessage"]{font-size:15px!important;line-height:1.6!important;color:#102D35!important;text-shadow:0 1px 3px rgba(255,255,255,.96)!important;background:transparent!important;border:1px solid rgba(8,87,83,.24)!important}
.block-container [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]){background:transparent!important;border-color:rgba(220,98,69,.42)!important}
.block-container [data-testid="stChatMessage"] p,.block-container [data-testid="stChatMessage"] li{color:#102D35!important;text-shadow:0 1px 3px rgba(255,255,255,.96)!important;font-size:15px!important;line-height:1.6!important}
div[data-testid="column"]:has([data-testid="stChatMessage"]){background:transparent!important;border:1px solid transparent!important;box-shadow:none!important;backdrop-filter:none!important}
section[data-testid="stSidebar"],section[data-testid="stSidebar"]>div,section[data-testid="stSidebar"] [data-testid="stSidebarContent"]{background:transparent!important;backdrop-filter:none!important}
section[data-testid="stSidebar"] .st-key-filter-panel-scroll,section[data-testid="stSidebar"] .stVerticalBlockBorderWrapper{background:transparent!important;border-color:transparent!important;backdrop-filter:none!important}
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3,section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] label,section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#102D35!important;text-shadow:0 1px 3px rgba(255,255,255,.96)!important;font-size:14px!important;line-height:1.5!important}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{font-size:13px!important;color:#203C43!important}
section[data-testid="stSidebar"] [data-testid="stTextInput"] input,section[data-testid="stSidebar"] [data-testid="stNumberInput"] input,section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"]>div{color:#102D35!important;-webkit-text-fill-color:#102D35!important;font-size:14px!important;font-weight:650!important;text-shadow:0 1px 2px rgba(255,255,255,.98)!important;background:transparent!important}
section[data-testid="stSidebar"] [data-testid="stTextInput"] input::placeholder{color:#354F54!important;opacity:1!important}
div[data-testid="stVerticalBlockBorderWrapper"]{background:transparent!important;border-color:rgba(255,255,255,.44)!important;box-shadow:none!important;backdrop-filter:none!important}
.hero-panel{background:transparent!important;border:1px solid rgba(255,255,255,.56)!important;border-top:3px solid #F05D43!important;backdrop-filter:none!important}
.hero-panel h2,.hero-panel p,.hero-panel-top,.hero-step span{color:#102D35!important;text-shadow:0 1px 3px rgba(255,255,255,.98)!important}
.hero-panel .hero-step strong{color:#B44832!important;text-shadow:0 1px 3px rgba(255,255,255,.98)!important}
.trust-pill{color:#102D35!important;text-shadow:0 1px 3px rgba(255,255,255,.96)!important;background:transparent!important;border-color:transparent!important}
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input,[data-testid="stSelectbox"] div,[data-testid="stTextArea"] textarea{font-family:'Segoe UI','Nirmala UI',Arial,sans-serif!important;font-size:15px!important;font-weight:600!important;color:#102D35!important;text-shadow:0 1px 2px rgba(255,255,255,.98)!important;background:transparent!important}
[data-testid="stTextInput"] input::placeholder,[data-testid="stTextArea"] textarea::placeholder{color:#354F54!important;opacity:1!important;text-shadow:0 1px 2px rgba(255,255,255,.98)!important}
/* Keep the photo and watermark visible through every Streamlit surface. */
div[data-testid="stAppViewContainer"],section[data-testid="stMain"],section[data-testid="stMain"]>div,
section[data-testid="stMain"] [data-testid="stMainBlockContainer"],section[data-testid="stMain"] [data-testid="stVerticalBlock"],
section[data-testid="stMain"] [data-testid="stElementContainer"],section[data-testid="stMain"] [data-testid="stTabPanel"],
section[data-testid="stSidebar"],section[data-testid="stSidebar"]>div,section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"],section[data-testid="stSidebar"] [data-testid="stElementContainer"],
div[data-testid="stVerticalBlockBorderWrapper"],div[data-testid="stForm"],[data-testid="stChatMessage"],
[data-testid="stTabPanel"]:has([data-testid="stChatInput"]),div[data-testid="column"]:has([data-testid="stChatMessage"]){
  background-color:transparent!important;background-image:none!important;backdrop-filter:none!important
}
/* Dark ink stays readable on the lightly softened photo; accents use teal and coral. */
.block-container,.block-container [data-testid="stMarkdownContainer"],.block-container [data-testid="stChatMessage"],
section[data-testid="stSidebar"],section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"]{
  color:#102D35!important
}
.block-container h1,.block-container h2,.block-container h3,.block-container h4,.block-container h5,.block-container h6,
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3{
  color:#0E3038!important;text-shadow:0 1px 2px rgba(255,255,255,.98),0 0 9px rgba(255,255,255,.72)!important
}
.block-container [data-testid="stMarkdownContainer"] p,.block-container [data-testid="stMarkdownContainer"] li,
.block-container [data-testid="stCaptionContainer"] p,.block-container [data-testid="stChatMessage"] p,
section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] label{
  color:#17363D!important;text-shadow:0 1px 2px rgba(255,255,255,.98),0 0 7px rgba(255,255,255,.76)!important
}
.hero-panel h2,.hero-panel p,.hero-panel-top,.hero-step span{color:#FFFFFF!important;text-shadow:0 1px 5px rgba(5,22,30,.95),0 0 10px rgba(5,22,30,.65)!important}
.hero-panel .hero-step strong{color:#FFD0C3!important;text-shadow:0 1px 4px rgba(5,22,30,.95)!important}
[data-testid="stChatMessage"]{border-color:rgba(8,87,83,.4)!important;text-shadow:0 1px 2px rgba(255,255,255,.98),0 0 7px rgba(255,255,255,.76)!important}
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]){border-color:rgba(220,98,69,.68)!important}
/* Cinematic photo stays untouched outside the content column; a light dark veil sits only beneath content. */
.block-container{background:transparent!important;border-radius:22px!important;color:#F4F7F4!important;text-shadow:0 1px 3px rgba(0,0,0,.72)!important}
.block-container h1,.block-container h2,.block-container h3,.block-container h4,.block-container h5,.block-container h6,
.block-container label,.block-container [data-testid="stMarkdownContainer"],.block-container [data-testid="stMarkdownContainer"] p,
.block-container [data-testid="stMarkdownContainer"] li,.block-container [data-testid="stCaptionContainer"],.block-container [data-testid="stCaptionContainer"] p,
.block-container [data-testid="stMetricLabel"],.block-container [data-testid="stMetricValue"],.block-container [data-testid="stChatMessage"],.block-container [data-testid="stChatMessage"] p{
  color:#F4F7F4!important;text-shadow:0 1px 3px rgba(0,0,0,.78)!important
}
.block-container .property-title,.block-container .property-sub,.block-container .small,.block-container .footnote{color:#F4F7F4!important;text-shadow:0 1px 3px rgba(0,0,0,.8)!important}
.block-container .price,.block-container [data-testid="stMetricValue"]{color:#B8F0E6!important}
section[data-testid="stSidebar"]{background:transparent!important;color:#F4F7F4!important}
section[data-testid="stSidebar"]>div,section[data-testid="stSidebar"] [data-testid="stSidebarContent"],section[data-testid="stSidebar"] .st-key-filter-panel-scroll,
section[data-testid="stSidebar"] .stVerticalBlockBorderWrapper{background:transparent!important}
section[data-testid="stSidebar"] .st-key-filter-panel-scroll{background:rgba(7,27,36,.42)!important;border:1px solid rgba(226,240,234,.32)!important;border-radius:18px!important;padding:10px!important;box-shadow:0 12px 32px rgba(3,18,25,.16)!important}
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3,section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{
  color:#F4F7F4!important;text-shadow:0 1px 3px rgba(0,0,0,.82)!important
}
section[data-testid="stSidebar"] [data-testid="stTextInput"] input,section[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"]>div,
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input,[data-testid="stSelectbox"] div,[data-testid="stTextArea"] textarea{
  color:#F4F7F4!important;-webkit-text-fill-color:#F4F7F4!important;text-shadow:0 1px 2px rgba(0,0,0,.82)!important;background:transparent!important;border-color:#D2E3DD!important
}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"],section[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"] *{color:#F4F7F4!important;-webkit-text-fill-color:#F4F7F4!important;text-shadow:0 1px 2px rgba(0,0,0,.82)!important}
[data-testid="stTextInput"] input::placeholder,[data-testid="stTextArea"] textarea::placeholder,section[data-testid="stSidebar"] input::placeholder{color:#DCE8E2!important;opacity:1!important}
section[data-testid="stMain"] .status{color:#F4F7F4!important;border-color:#D7E6E0!important;text-shadow:0 1px 3px rgba(0,0,0,.82)!important}
section[data-testid="stMain"] .status.auction{color:#D8E4FF!important}
section[data-testid="stMain"] .status.sale{color:#FFD0C3!important}
section[data-testid="stMain"] .status.undated{color:#FFE3A3!important;border-color:#E9C36E!important}
[data-testid="stTabs"] button{color:#EAF2EF!important}
[data-testid="stTabs"] button[aria-selected="true"]{color:#B8F0E6!important;border-bottom-color:#F05D43!important}
[data-testid="stVerticalBlockBorderWrapper"],[data-testid="stForm"],[data-testid="stChatMessage"],[data-testid="stTabPanel"]:has([data-testid="stChatInput"]){background:transparent!important}
.st-key-results-content-wash-active,.st-key-mira-content-wash{
  background:rgba(7,27,36,.42)!important;border:1px solid rgba(226,240,234,.32)!important;border-radius:18px!important;padding:13px!important;box-shadow:0 12px 32px rgba(3,18,25,.16)!important
}
/* Give the results and conversation surfaces a clearer edge over the photo. */
.st-key-results-content-wash-active{
  border-color:rgba(231,245,239,.58)!important;
  box-shadow:0 18px 42px rgba(2,14,20,.32),0 3px 12px rgba(2,14,20,.20),inset 0 1px 0 rgba(255,255,255,.16)!important
}
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]{
  border:1px solid rgba(236,246,241,.54)!important;
  border-radius:15px!important;
  box-shadow:0 8px 20px rgba(2,14,20,.24),inset 0 1px 0 rgba(255,255,255,.12)!important;
  transition:transform .16s ease,box-shadow .16s ease!important
}
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:hover{
  transform:translateY(-2px);
  box-shadow:0 13px 26px rgba(2,14,20,.34),inset 0 1px 0 rgba(255,255,255,.16)!important
}
.st-key-mira-content-wash{
  border-color:rgba(231,245,239,.62)!important;
  box-shadow:0 18px 44px rgba(2,14,20,.36),0 4px 14px rgba(2,14,20,.22),inset 0 1px 0 rgba(255,255,255,.18)!important
}
.st-key-mira-content-wash [data-testid="stChatMessage"]{
  border-color:rgba(226,242,236,.58)!important;
  box-shadow:0 5px 14px rgba(2,14,20,.24),inset 0 1px 0 rgba(255,255,255,.12)!important
}
.st-key-mira-content-wash [data-testid="stForm"]:has([data-testid="stFormSubmitButton"]){
  border-color:rgba(231,245,239,.72)!important;
  box-shadow:0 8px 22px rgba(2,14,20,.30),inset 0 1px 0 rgba(255,255,255,.14)!important
}
.st-key-mira-content-wash [data-testid="stTextInput"] input{
  border:1px solid rgba(236,246,241,.78)!important;
  border-radius:11px!important;
  box-shadow:inset 0 2px 5px rgba(2,14,20,.18),0 3px 10px rgba(2,14,20,.20)!important;
  transition:border-color .16s ease,box-shadow .16s ease!important
}
.st-key-mira-content-wash [data-testid="stTextInput"] input:focus{
  border-color:#9BE8DB!important;
  box-shadow:0 0 0 3px rgba(155,232,219,.25),inset 0 2px 5px rgba(2,14,20,.16),0 5px 14px rgba(2,14,20,.24)!important
}
.st-key-mira-content-wash [data-testid="stTextInput"] input,
.st-key-mira-content-wash [data-testid="stTextInput"] input:focus{
  color:#102F38!important;-webkit-text-fill-color:#102F38!important;
  background:rgba(255,255,255,.96)!important;font-weight:700!important;text-shadow:none!important
}
.st-key-mira-content-wash [data-testid="stTextInput"] input::placeholder{
  color:#42636A!important;-webkit-text-fill-color:#42636A!important;opacity:1!important;text-shadow:none!important
}
.st-key-toggle_mira_chat_size button{
  min-width:42px!important;width:42px!important;min-height:42px!important;padding:0!important;
  border-radius:12px!important;font-size:22px!important;line-height:1!important
}
.st-key-listing_view_all button,.st-key-listing_view_sales button,.st-key-listing_view_auctions button,
.st-key-info_panel_auction button,.st-key-info_panel_loan button,.st-key-info_panel_area button,
.st-key-info_panel_sources button,.st-key-info_panel_followups button,
.st-key-results_start_0 button,.st-key-results_start_1 button,.st-key-results_start_2 button{
  min-height:52px!important;border-radius:15px!important;padding:9px 12px!important;
  background:rgba(8,31,39,.56)!important;color:#F6FBF9!important;-webkit-text-fill-color:#F6FBF9!important;
  border:1px solid rgba(231,245,239,.42)!important;border-bottom:3px solid rgba(231,245,239,.32)!important;
  box-shadow:0 7px 20px rgba(2,14,20,.24),inset 0 1px 0 rgba(255,255,255,.12)!important;
  backdrop-filter:blur(9px)!important;transition:transform .16s ease,background .16s ease,border-color .16s ease,box-shadow .16s ease!important
}
.st-key-listing_view_all button p,.st-key-listing_view_sales button p,.st-key-listing_view_auctions button p,
.st-key-info_panel_auction button p,.st-key-info_panel_loan button p,.st-key-info_panel_area button p,
.st-key-info_panel_sources button p,.st-key-info_panel_followups button p,
.st-key-results_start_0 button p,.st-key-results_start_1 button p,.st-key-results_start_2 button p{color:#F6FBF9!important;-webkit-text-fill-color:#F6FBF9!important;font-weight:750!important}
.st-key-listing_view_all [data-testid="stBaseButton-primary"],.st-key-listing_view_sales [data-testid="stBaseButton-primary"],.st-key-listing_view_auctions [data-testid="stBaseButton-primary"],
.st-key-info_panel_auction [data-testid="stBaseButton-primary"],.st-key-info_panel_loan [data-testid="stBaseButton-primary"],.st-key-info_panel_area [data-testid="stBaseButton-primary"],
.st-key-info_panel_sources [data-testid="stBaseButton-primary"],.st-key-info_panel_followups [data-testid="stBaseButton-primary"],
.st-key-results_start_0 [data-testid="stBaseButton-primary"],.st-key-results_start_1 [data-testid="stBaseButton-primary"],.st-key-results_start_2 [data-testid="stBaseButton-primary"]{
  background:linear-gradient(135deg,rgba(12,120,113,.96),rgba(7,80,78,.96))!important;
  border-color:rgba(155,232,219,.86)!important;border-bottom-color:#F07859!important;
  box-shadow:0 10px 24px rgba(1,17,23,.34),inset 0 1px 0 rgba(255,255,255,.24)!important
}
.st-key-listing_view_all button:hover,.st-key-listing_view_sales button:hover,.st-key-listing_view_auctions button:hover,
.st-key-info_panel_auction button:hover,.st-key-info_panel_loan button:hover,.st-key-info_panel_area button:hover,
.st-key-info_panel_sources button:hover,.st-key-info_panel_followups button:hover,
.st-key-results_start_0 button:hover,.st-key-results_start_1 button:hover,.st-key-results_start_2 button:hover{
  transform:translateY(-2px);background:rgba(18,76,79,.9)!important;border-color:#9BE8DB!important;
  box-shadow:0 12px 25px rgba(2,14,20,.34),inset 0 1px 0 rgba(255,255,255,.2)!important
}
.st-key-listing_view_all [data-testid="stBaseButton-primary"]:hover,.st-key-listing_view_sales [data-testid="stBaseButton-primary"]:hover,
.st-key-listing_view_auctions [data-testid="stBaseButton-primary"]:hover,.st-key-info_panel_auction [data-testid="stBaseButton-primary"]:hover,
.st-key-info_panel_loan [data-testid="stBaseButton-primary"]:hover,.st-key-info_panel_area [data-testid="stBaseButton-primary"]:hover,
.st-key-info_panel_sources [data-testid="stBaseButton-primary"]:hover,.st-key-info_panel_followups [data-testid="stBaseButton-primary"]:hover,
.st-key-results_start_0 [data-testid="stBaseButton-primary"]:hover,.st-key-results_start_1 [data-testid="stBaseButton-primary"]:hover,.st-key-results_start_2 [data-testid="stBaseButton-primary"]:hover{
  background:linear-gradient(135deg,#128B82,#08625F)!important
}
.start-option-help{
  min-height:72px;margin:8px 0 2px;padding:10px 12px;border-radius:12px;
  color:#102F38!important;-webkit-text-fill-color:#102F38!important;
  background:rgba(255,249,239,.94)!important;border:1px solid rgba(16,47,56,.24)!important;
  box-shadow:0 4px 13px rgba(3,18,25,.16)!important;
  font-size:13px!important;font-weight:700!important;line-height:1.48!important;
  text-shadow:none!important
}
.start-option-help *{color:#102F38!important;-webkit-text-fill-color:#102F38!important;text-shadow:none!important}
section[data-testid="stMain"] [data-testid="stTabPanel"]{
  background:rgba(7,27,36,.40)!important;border:1px solid rgba(226,240,234,.30)!important;border-radius:18px!important;padding:16px!important;box-shadow:0 12px 30px rgba(3,18,25,.14)!important
}
.st-key-filter-panel-scroll .filter-heading-title,.st-key-filter-panel-scroll .filter-heading-subtitle,
.st-key-filter-panel-scroll .language-heading,.st-key-filter-panel-scroll .language-heading span,
section[data-testid="stSidebar"] .filter-heading-title,section[data-testid="stSidebar"] .filter-heading-subtitle,
section[data-testid="stSidebar"] .language-heading,section[data-testid="stSidebar"] .language-heading span{
  color:#FFFFFF!important;opacity:1!important;font-weight:700!important;text-shadow:0 1px 3px rgba(0,0,0,.88)!important
}
.st-key-filter-panel-scroll .filter-heading-icon,section[data-testid="stSidebar"] .filter-heading-icon{color:#9BE8DB!important;opacity:1!important;text-shadow:0 1px 3px rgba(0,0,0,.8)!important}
.st-key-results-content-wash-active [data-testid="stCaptionContainer"],.st-key-results-content-wash-active [data-testid="stCaptionContainer"] p,
.st-key-results-content-wash-active [data-testid="stMarkdownContainer"] p,.st-key-results-content-wash-active [data-testid="stMarkdownContainer"] li,
.st-key-mira-content-wash [data-testid="stCaptionContainer"],.st-key-mira-content-wash [data-testid="stCaptionContainer"] p,
.st-key-mira-content-wash [data-testid="stMarkdownContainer"] p,.st-key-mira-content-wash [data-testid="stMarkdownContainer"] li,
.st-key-filter-panel-scroll [data-testid="stCaptionContainer"],.st-key-filter-panel-scroll [data-testid="stCaptionContainer"] p{
  color:#FFFFFF!important;opacity:1!important;font-weight:550!important;text-shadow:0 1px 3px rgba(0,0,0,.9)!important
}
.trust-pill{color:#FFFFFF!important;opacity:1!important;text-shadow:0 1px 3px rgba(0,0,0,.88)!important}
.st-key-results-content-wash-active .property-sub,.st-key-results-content-wash-active .small,.st-key-results-content-wash-active .footnote,
.st-key-mira-content-wash .property-sub,.st-key-mira-content-wash .small,.st-key-mira-content-wash .footnote{
  color:#F1F7F4!important;opacity:1!important;font-weight:550!important;text-shadow:0 1px 3px rgba(0,0,0,.9)!important
}
/* Match the filter panel's dark glass surface so result controls and text stay legible. */
.st-key-results-content-wash-active{
  background:rgba(7,27,36,.82)!important;
  border:1px solid rgba(226,240,234,.48)!important;
  border-radius:20px!important;
  padding:16px 18px!important;
  box-shadow:0 14px 34px rgba(3,18,25,.28)!important;
  backdrop-filter:blur(12px)!important;
  -webkit-backdrop-filter:blur(12px)!important;
  color:#F4F7F4!important;
  text-shadow:none!important
}
section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-results-content-wash-active){
  background:rgba(7,27,36,.78)!important;
  border:1px solid rgba(226,240,234,.48)!important;
  border-radius:20px!important;
  padding:16px!important;
  box-shadow:0 14px 34px rgba(3,18,25,.28)!important;
  backdrop-filter:blur(12px)!important;
  -webkit-backdrop-filter:blur(12px)!important
}
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]{
  background:rgba(255,255,255,.92)!important;
  border-color:rgba(27,93,91,.28)!important;
  box-shadow:0 7px 18px rgba(20,58,60,.18),inset 0 1px 0 rgba(255,255,255,.96)!important
}
.st-key-results-content-wash-active [data-testid="stCaptionContainer"],
.st-key-results-content-wash-active [data-testid="stCaptionContainer"] p,
.st-key-results-content-wash-active [data-testid="stMarkdownContainer"] p,
.st-key-results-content-wash-active [data-testid="stMarkdownContainer"] li,
.st-key-results-content-wash-active [data-testid="stMarkdownContainer"] h1,
.st-key-results-content-wash-active [data-testid="stMarkdownContainer"] h2,
.st-key-results-content-wash-active [data-testid="stMarkdownContainer"] h3,
.st-key-results-content-wash-active [data-testid="stMarkdownContainer"] h4,
.st-key-results-content-wash-active .property-title,.st-key-results-content-wash-active .property-sub,
.st-key-results-content-wash-active .small,.st-key-results-content-wash-active .footnote,
.st-key-results-content-wash-active [data-testid="stMetricLabel"],
.st-key-results-content-wash-active [data-testid="stMetricValue"]{
  color:#F4F7F4!important;
  opacity:1!important;
  text-shadow:0 1px 3px rgba(0,0,0,.72)!important
}
.st-key-results-content-wash-active [data-testid="stMetric"]{background:rgba(245,251,248,.96)!important;border-color:rgba(18,104,99,.24)!important}
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stCaptionContainer"],
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stCaptionContainer"] p,
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stMarkdownContainer"],
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stMarkdownContainer"] p,
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .property-title,
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .property-sub,
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .small,
.st-key-results-content-wash-active [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .footnote{
  color:#17353B!important;
  text-shadow:none!important
}
.st-key-results-content-wash-idle{background:transparent!important;border:0!important;box-shadow:none!important;padding:0!important}
/* Property cards can render outside the main results wrapper (for example in
   the auction panel), so wash the card itself wherever a listing is displayed. */
section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title){
  background:rgba(224,241,235,.98)!important;
  border:1px solid rgba(24,91,87,.26)!important;
  border-radius:16px!important;
  box-shadow:0 9px 24px rgba(9,39,43,.20),inset 0 1px 0 rgba(255,255,255,.88)!important;
  backdrop-filter:blur(10px)!important;
  -webkit-backdrop-filter:blur(10px)!important
}
section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .property-title,
section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .property-sub,
section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .small,
section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .footnote,
section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stCaptionContainer"],
section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stCaptionContainer"] p{
  color:#17353B!important;
  opacity:1!important;
  text-shadow:none!important
}
/* Apply the same readable pastel surface to whichever utility panel is open. */
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4){
  background:rgba(224,241,235,.97)!important;
  color:#17353B!important;
  border:1px solid rgba(24,91,87,.28)!important;
  border-radius:18px!important;
  padding:18px!important;
  box-shadow:0 12px 30px rgba(9,39,43,.22),inset 0 1px 0 rgba(255,255,255,.88)!important;
  backdrop-filter:blur(10px)!important;
  -webkit-backdrop-filter:blur(10px)!important
}
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMarkdownContainer"],
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMarkdownContainer"] p,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMarkdownContainer"] li,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMarkdownContainer"] h1,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMarkdownContainer"] h2,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMarkdownContainer"] h3,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMarkdownContainer"] h4,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stCaptionContainer"],
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stCaptionContainer"] p,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) label,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMetricLabel"],
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stMetricValue"],
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) .footnote{
  color:#17353B!important;
  opacity:1!important;
  text-shadow:none!important
}
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stTextInput"] input,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stNumberInput"] input,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stTextArea"] textarea,
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stSelectbox"] [data-baseweb="select"]>div{
  background:rgba(255,255,255,.94)!important;
  color:#17353B!important;
  -webkit-text-fill-color:#17353B!important;
  text-shadow:none!important;
  border-color:rgba(24,91,87,.32)!important
}
section[data-testid="stMain"] .st-key-info-panel-content:has([data-testid="stMarkdownContainer"] h4) [data-testid="stVerticalBlockBorderWrapper"]{
  background:rgba(255,255,255,.72)!important;
  border-color:rgba(24,91,87,.22)!important;
  box-shadow:0 6px 16px rgba(9,39,43,.12)!important
}
@media(max-width:760px){[data-testid="stHorizontalBlock"]:not(:has(.st-key-results-content-wash-active)){display:grid!important;grid-template-columns:minmax(0,1fr)!important;gap:1rem!important}[data-testid="stHorizontalBlock"]:not(:has(.st-key-results-content-wash-active))>[data-testid="column"]{width:100%!important;min-width:0!important;max-width:100%!important}}
@media(max-width:820px){.hero{min-height:410px;padding:20px;background-position:57% center}.hero-main{margin-top:22px;max-width:100%}.hero-panel{position:relative;right:auto;bottom:auto;width:min(100%,360px);margin:0 0 0 auto}.hero-pill{display:none}}
@media(max-width:700px){.block-container{padding:.85rem;background:transparent!important;border-radius:18px}.hero{min-height:450px;padding:16px;border-radius:18px;background-position:55% center}.hero h1{font-size:36px}.hero-panel{width:100%;padding:14px}.hero-topline{font-size:11px}[data-testid="stTabPanel"]:has([data-testid="stChatInput"]){padding:11px}}
/* Compact the masthead and keep long content inside its own panel. */
.block-container{padding-top:.55rem!important;padding-bottom:.65rem!important}
.hero{min-height:132px!important;height:132px!important;padding:12px 18px!important;margin-bottom:7px!important;justify-content:center!important;background-position:center 48%!important}
.hero-topline{position:absolute;top:8px;left:15px;right:15px;font-size:11px!important}
.hero-brand img{width:min(280px,44vw)!important}
.hero-pill{font-size:10px!important;padding:4px 8px!important}
.hero-main{margin:18px 0 0!important;max-width:75%!important}
.hero-main .eyebrow,.hero-main p,.hero-cta,.hero-panel,.trust-row{display:none!important}
.hero-panel{display:none!important}
.hero-main{width:100%!important}
.hero h1{font-size:clamp(20px,2.4vw,29px)!important;line-height:1.1!important;margin:0!important;letter-spacing:-.025em!important}
.hero h1 br{display:none!important}
.st-key-results-content-wash-active,.st-key-mira-content-wash{max-height:calc(100vh - 245px)!important;min-height:0!important;overflow-y:auto!important;overscroll-behavior:contain!important;scrollbar-width:thin;scrollbar-color:#70B9AD rgba(255,255,255,.12)}
.st-key-results-content-wash-active::-webkit-scrollbar,.st-key-mira-content-wash::-webkit-scrollbar,.st-key-info-panel-content::-webkit-scrollbar{width:9px}
.st-key-results-content-wash-active::-webkit-scrollbar-thumb,.st-key-mira-content-wash::-webkit-scrollbar-thumb,.st-key-info-panel-content::-webkit-scrollbar-thumb{background:#70B9AD;border:2px solid rgba(7,27,36,.35);border-radius:10px}
.st-key-mira-content-wash{max-height:calc(100vh - 245px)!important;padding:10px!important}
.st-key-mira-content-wash [data-testid="stChatMessage"]{padding:8px 10px!important;margin-bottom:6px!important;font-size:13px!important;line-height:1.45!important}
.st-key-mira-content-wash [data-testid="stChatMessage"] p{font-size:13px!important;line-height:1.45!important;margin-bottom:.25rem!important}
.st-key-mira-content-wash [data-testid="stForm"]{padding:7px!important}
.st-key-info-panel-content{max-height:calc(100vh - 245px)!important;overflow-y:auto!important;overscroll-behavior:contain!important;padding:12px!important;background:rgba(7,27,36,.78)!important;border:1px solid rgba(226,240,234,.48)!important;border-radius:18px!important;backdrop-filter:blur(12px)!important}
.st-key-info_panel_auction button,.st-key-info_panel_loan button,.st-key-info_panel_area button,.st-key-info_panel_sources button,.st-key-info_panel_followups button{min-height:48px!important;padding:5px 6px!important;font-size:11px!important;white-space:normal!important;text-overflow:clip!important;line-height:1.15!important}
.st-key-info_panel_auction button p,.st-key-info_panel_loan button p,.st-key-info_panel_area button p,.st-key-info_panel_sources button p,.st-key-info_panel_followups button p,.st-key-listing_view_all button p,.st-key-listing_view_sales button p,.st-key-listing_view_auctions button p{white-space:normal!important;overflow:visible!important;text-overflow:clip!important;overflow-wrap:anywhere!important;line-height:1.12!important}
.st-key-auction_visible_limit [data-testid="stWidgetLabel"],.st-key-auction_visible_limit [data-testid="stWidgetLabel"] p{color:#17353B!important;-webkit-text-fill-color:#17353B!important;font-size:14px!important;font-weight:750!important;text-shadow:none!important;opacity:1!important}
.st-key-auction_visible_limit [role="group"]{background:#F7FBF8!important;border:1px solid #77BDB2!important;border-radius:11px!important;box-shadow:0 3px 10px rgba(2,24,29,.2)!important}
.st-key-auction_visible_limit input[role="combobox"]{background:transparent!important;color:#17353B!important;-webkit-text-fill-color:#17353B!important;text-shadow:none!important;font-weight:750!important;opacity:1!important}
.st-key-auction_visible_limit button{background:#087C78!important;color:#FFFFFF!important;border-radius:0 10px 10px 0!important}
.st-key-auction_visible_limit button svg{fill:#FFFFFF!important;color:#FFFFFF!important}
[role="listbox"] [role="option"]{background:#FFFFFF!important;color:#17353B!important;-webkit-text-fill-color:#17353B!important}
[role="listbox"] [role="option"][aria-selected="true"]{background:#DDF1EB!important;color:#075E5B!important;-webkit-text-fill-color:#075E5B!important}
@media(max-width:760px){.st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:.35rem!important}.st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{width:auto!important;min-width:0!important;max-width:none!important}.st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(5){grid-column:1/-1!important}}
@media(max-width:700px){.hero{height:112px!important;min-height:112px!important;padding:10px 12px!important}.hero-brand img{width:min(210px,55vw)!important}.hero-topline{left:10px;right:10px;top:6px}.hero-main{max-width:100%!important;margin-top:20px!important}.hero h1{font-size:20px!important}.st-key-results-content-wash-active,.st-key-mira-content-wash{max-height:calc(100vh - 220px)!important}.st-key-info-panel-content{max-height:calc(100vh - 220px)!important}}
section[data-testid="stSidebar"]{width:260px!important;min-width:260px!important;max-width:260px!important;flex:0 0 260px!important}
section[data-testid="stSidebar"]>div{width:260px!important;min-width:260px!important;max-width:260px!important}
@media(max-width:760px){[data-testid="stHorizontalBlock"]:has(.st-key-results-content-wash-active){display:grid!important;grid-template-columns:minmax(0,1.75fr) minmax(210px,1fr)!important;gap:.55rem!important}[data-testid="stHorizontalBlock"]:has(.st-key-results-content-wash-active)>[data-testid="column"]{width:auto!important;min-width:0!important;max-width:none!important}.st-key-results-content-wash-active,.st-key-mira-content-wash{max-height:calc(100vh - 225px)!important;padding:9px!important}.st-key-info_panel_auction button,.st-key-info_panel_loan button,.st-key-info_panel_area button,.st-key-info_panel_sources button,.st-key-info_panel_followups button{font-size:10px!important}}
.st-key-mira-content-wash h4{font-size:16px!important;line-height:1.2!important;white-space:nowrap!important}
/* Put the wash on the results column itself; Streamlit's keyed container may
   be nested inside transparent layout wrappers, which otherwise let the page
   photo show through behind result copy. */
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active){
  background:rgba(7,27,36,.78)!important;
  border:1px solid rgba(226,240,234,.48)!important;
  border-radius:20px!important;
  padding:16px!important;
  box-shadow:0 14px 34px rgba(3,18,25,.28)!important;
  backdrop-filter:blur(12px)!important;
  -webkit-backdrop-filter:blur(12px)!important
}
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stMarkdownContainer"],
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stMarkdownContainer"] p,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stMarkdownContainer"] h1,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stMarkdownContainer"] h2,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stMarkdownContainer"] h3,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stMarkdownContainer"] h4,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stCaptionContainer"],
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stCaptionContainer"] p{
  color:#F4F7F4!important;
  opacity:1!important;
  text-shadow:0 1px 3px rgba(0,0,0,.82)!important
}
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stMarkdownContainer"],
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stMarkdownContainer"] p,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stCaptionContainer"],
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) [data-testid="stCaptionContainer"] p,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .property-title,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .property-sub,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .small,
section[data-testid="stMain"] div[data-testid="column"]:has(.st-key-results-content-wash-active) [data-testid="stVerticalBlockBorderWrapper"]:has(.property-title) .footnote{
  color:#17353B!important;
  text-shadow:none!important
}
/* Follow-up form overrides must win over the surrounding results column. */
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"]{
  background:#F3FAF7!important;border:1px solid #56877B!important;border-radius:14px!important;padding:16px!important
}
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] [data-testid="stCaptionContainer"],
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] [data-testid="stCaptionContainer"] p,
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] label,
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] [data-testid="stMarkdownContainer"] p,
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] [data-baseweb="select"] div{
  color:#102F36!important;-webkit-text-fill-color:#102F36!important;opacity:1!important;text-shadow:none!important
}
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] [data-baseweb="select"]>div,
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] input,
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] textarea{
  background:#FFFFFF!important;color:#102F36!important;-webkit-text-fill-color:#102F36!important;text-shadow:none!important
}
[data-baseweb="popover"] [role="option"]{color:#102F36!important;background:#FFFFFF!important;text-shadow:none!important}
/* Cover Streamlit's newer React Aria select as well as Base Web. */
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] [data-testid="stCaptionContainer"] p{
  color:#082D36!important;-webkit-text-fill-color:#082D36!important;font-size:14px!important;font-weight:600!important;line-height:1.6!important
}
section[data-testid="stMain"] .st-key-info-panel-content .st-key-followup_email_cadence label,
section[data-testid="stMain"] .st-key-info-panel-content .st-key-followup_email_cadence label p{
  color:#082D36!important;-webkit-text-fill-color:#082D36!important;font-size:16px!important;font-weight:700!important
}
section[data-testid="stMain"] .st-key-info-panel-content .st-key-followup_email_cadence [role="combobox"],
section[data-testid="stMain"] .st-key-info-panel-content .st-key-followup_email_cadence [role="combobox"] *,
section[data-testid="stMain"] .st-key-info-panel-content .st-key-followup_email_cadence button,
section[data-testid="stMain"] .st-key-info-panel-content .st-key-followup_email_cadence button *{
  color:#082D36!important;-webkit-text-fill-color:#082D36!important;opacity:1!important;font-size:15px!important;font-weight:650!important;text-shadow:none!important
}
section[data-testid="stMain"] .st-key-info-panel-content .st-key-followup_email_cadence [role="combobox"]{
  background:#FFFFFF!important;border:1px solid #38736B!important;border-radius:9px!important
}
section[data-testid="stMain"] .st-key-info-panel-content .st-key-followup_email_cadence svg{color:#082D36!important}
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] button,
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] button [data-testid="stMarkdownContainer"] p,
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] button *{
  color:#FFFFFF!important;-webkit-text-fill-color:#FFFFFF!important;text-shadow:none!important
}
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] button:disabled{
  background:#52666B!important;border-color:#52666B!important;opacity:1!important;cursor:not-allowed!important
}
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] .st-key-followup_email_cadence button,
section[data-testid="stMain"] .st-key-info-panel-content [data-testid="stForm"] .st-key-followup_email_cadence button *{
  color:#082D36!important;-webkit-text-fill-color:#082D36!important
}
/* Compact, readable Mira surface and orderly responsive navigation. */
.st-key-mira-content-wash{
  width:100%!important;max-height:min(440px,calc(100vh - 190px))!important;
  overflow-y:auto!important;overscroll-behavior:contain!important;
  background:rgba(7,27,36,.84)!important;
  border-color:rgba(226,240,234,.68)!important;border-radius:14px!important;
  backdrop-filter:blur(14px)!important;-webkit-backdrop-filter:blur(14px)!important
}
.st-key-mira-content-wash [data-testid="stChatMessage"]{
  background:rgba(255,250,242,.94)!important;
  border-color:rgba(226,240,234,.72)!important;
  color:#102F38!important;text-shadow:none!important
}
.st-key-mira-content-wash [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"],
.st-key-mira-content-wash [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
.st-key-mira-content-wash [data-testid="stChatMessage"] [data-testid="stCaptionContainer"] p{
  color:#102F38!important;-webkit-text-fill-color:#102F38!important;text-shadow:none!important
}
.st-key-mira-content-wash [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]){
  background:rgba(8,92,88,.94)!important;border-color:#9BE8DB!important
}
.st-key-mira-content-wash [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) [data-testid="stMarkdownContainer"],
.st-key-mira-content-wash [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) [data-testid="stMarkdownContainer"] p{
  color:#FFFFFF!important;-webkit-text-fill-color:#FFFFFF!important;text-shadow:none!important
}
.st-key-chat_starter_0 button,.st-key-chat_starter_1 button,.st-key-chat_starter_2 button{
  height:30px!important;min-height:30px!important;padding:3px 5px!important;border-radius:8px!important;
  font-size:10px!important;line-height:1.1!important
}
.st-key-chat_starter_0 button p,.st-key-chat_starter_1 button p,.st-key-chat_starter_2 button p{
  font-size:10px!important;line-height:1.1!important;white-space:normal!important
}
.st-key-info_panel_auction button,.st-key-info_panel_loan button,.st-key-info_panel_area button,
.st-key-info_panel_sources button,.st-key-info_panel_followups button{
  min-height:40px!important;padding:5px 8px!important;font-size:12px!important
}
.st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]{
  display:flex!important;flex-wrap:wrap!important;gap:.45rem!important
}
.st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{
  flex:1 1 112px!important;width:auto!important;min-width:112px!important;max-width:none!important
}
.st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(5){margin-inline:auto!important}
.st-key-chat-starter-options [data-testid="stHorizontalBlock"]{
  display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:.4rem!important
}
.st-key-chat-starter-options [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{
  width:auto!important;min-width:0!important;max-width:none!important
}
.st-key-explore-controls{margin-top:.35rem!important;margin-bottom:.65rem!important}
.st-key-eight-toggle-grid [data-testid="stHorizontalBlock"]{
  display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:.55rem!important;margin-bottom:.55rem!important
}
.st-key-eight-toggle-grid [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{
  width:auto!important;min-width:0!important;max-width:none!important
}
.st-key-eight-toggle-grid button{
  width:100%!important;height:50px!important;min-height:50px!important;padding:6px 8px!important;border-radius:12px!important
}
.st-key-eight-toggle-grid button p{
  font-size:12px!important;line-height:1.2!important;white-space:normal!important;overflow:visible!important;text-overflow:clip!important
}
.st-key-start-option-guides [data-testid="stHorizontalBlock"]{
  display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:.55rem!important
}
.st-key-start-option-guides [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{
  width:auto!important;min-width:0!important;max-width:none!important
}
.st-key-start-option-guides .start-option-help{height:auto!important;min-height:72px!important}
.st-key-main-start-options [data-testid="stHorizontalBlock"]{
  display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:.5rem!important
}
.st-key-main-start-options [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{
  width:auto!important;min-width:0!important;max-width:none!important
}
.st-key-mira-composer-row [data-testid="stHorizontalBlock"]{
  display:grid!important;grid-template-columns:minmax(0,4fr) minmax(70px,1fr)!important;gap:.45rem!important;align-items:center!important
}
.st-key-mira-composer-row [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{
  width:auto!important;min-width:0!important;max-width:none!important
}
.st-key-mira-composer-row [data-testid="stTextInput"],
.st-key-mira-composer-row [data-testid="stFormSubmitButton"]{margin:0!important}
.st-key-mira-composer-row [data-testid="stFormSubmitButton"] button{height:34px!important;min-height:34px!important;padding:4px 6px!important;font-size:11px!important}
section[data-testid="stMain"] div[data-testid="stColumn"]:has(.st-key-mira-content-wash){
  background:rgba(7,27,36,.72)!important;border:1px solid rgba(226,240,234,.58)!important;
  border-radius:18px!important;padding:10px!important;box-shadow:0 14px 34px rgba(3,18,25,.30)!important;
  backdrop-filter:blur(14px)!important;-webkit-backdrop-filter:blur(14px)!important;
  align-self:flex-start!important;position:sticky!important;top:.5rem!important
}
.st-key-toggle_mira_chat_size button{min-width:32px!important;width:32px!important;height:32px!important;min-height:32px!important;border-radius:9px!important;font-size:16px!important}
.st-key-end_mira_chat button{height:30px!important;min-height:30px!important;padding:3px 7px!important;border-radius:8px!important;font-size:11px!important}
@media(max-width:900px){
  section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.st-key-mira-content-wash){
    display:grid!important;grid-template-columns:minmax(0,1fr)!important;gap:1rem!important
  }
  section[data-testid="stMain"] div[data-testid="stColumn"]:has(.st-key-mira-content-wash){
    position:relative!important;top:auto!important;align-self:stretch!important;min-width:0!important
  }
}
@media(max-width:760px){
  /* Streamlit's two-column workspace can overlap before the browser finishes
     measuring a narrow viewport. Stack the result and chat columns and remove
     desktop sticky positioning on phones. */
  section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.st-key-mira-content-wash){
    display:grid!important;grid-template-columns:minmax(0,1fr)!important;gap:1rem!important
  }
  section[data-testid="stMain"] div[data-testid="stColumn"]:has(.st-key-mira-content-wash){
    position:relative!important;top:auto!important;align-self:stretch!important;min-width:0!important
  }
  .st-key-eight-toggle-grid [data-testid="stHorizontalBlock"]{grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:.32rem!important}
  .st-key-eight-toggle-grid button{height:54px!important;min-height:54px!important;padding:4px 3px!important}
  .st-key-eight-toggle-grid button p{font-size:9px!important;line-height:1.15!important}
  .st-key-start-option-guides .start-option-help{min-height:96px!important;padding:7px!important;font-size:10px!important;line-height:1.3!important}
  .st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]{
    display:grid!important;grid-template-columns:repeat(6,minmax(0,1fr))!important;gap:.4rem!important
  }
  .st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{
    grid-column:span 2;width:auto!important;min-width:0!important;max-width:none!important
  }
  .st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(4),
  .st-key-utility-toggle-bar [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(5){grid-column:span 3!important;margin-inline:0!important}
  .st-key-info_panel_auction button,.st-key-info_panel_loan button,.st-key-info_panel_area button,
  .st-key-info_panel_sources button,.st-key-info_panel_followups button{height:52px!important;min-height:52px!important;font-size:11px!important;white-space:normal!important}
  .st-key-mira-content-wash{max-height:min(330px,calc(100vh - 270px))!important}
  .st-key-main-start-options .start-option-help{height:108px!important;min-height:108px!important;padding:7px!important;font-size:10.5px!important;line-height:1.3!important;overflow:visible!important}
  .st-key-main-start-options .st-key-results_start_0 button,
  .st-key-main-start-options .st-key-results_start_1 button,
  .st-key-main-start-options .st-key-results_start_2 button{height:56px!important;min-height:56px!important;padding:5px 4px!important;font-size:10px!important}
  .st-key-main-start-options .st-key-results_start_0 button p,
  .st-key-main-start-options .st-key-results_start_1 button p,
  .st-key-main-start-options .st-key-results_start_2 button p{font-size:10px!important;line-height:1.2!important;white-space:normal!important;overflow:visible!important;text-overflow:clip!important}
}
@media(max-width:560px){
  .st-key-eight-toggle-grid [data-testid="stHorizontalBlock"]{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:.45rem!important}
  .st-key-eight-toggle-grid button{height:46px!important;min-height:46px!important;padding:5px 6px!important}
  .st-key-eight-toggle-grid button p{font-size:11px!important;line-height:1.2!important}
  .st-key-chat-starter-options [data-testid="stHorizontalBlock"]{grid-template-columns:1fr!important}
  .st-key-main-start-options [data-testid="stHorizontalBlock"]{grid-template-columns:1fr!important}
  .st-key-main-start-options .start-option-help{height:auto!important;min-height:0!important;margin-top:4px!important}
  .st-key-mira-composer-row [data-testid="stHorizontalBlock"]{grid-template-columns:minmax(0,1fr)!important}
}
</style>
""".replace("__HERO_IMAGE__", HERO_IMAGE_URL).replace("__WATERMARK_IMAGE__", WATERMARK_IMAGE_URL)
st.markdown(_base_styles, unsafe_allow_html=True)

st.markdown(f'''
<section class="hero" style="background-image:linear-gradient(90deg,rgba(9,28,37,.84) 0%,rgba(9,28,37,.57) 46%,rgba(9,28,37,.08) 100%),linear-gradient(0deg,rgba(9,28,37,.52),transparent 48%),url('{HERO_IMAGE_URL}');">
  <div class="hero-topline">
    <div class="hero-brand"><img src="{LOGO_IMAGE_URL}" alt="Namma Illam — homes, with heart and honesty"></div>
    <span class="hero-pill">{"தமிழ்நாடு · ஆதாரத் தகவல் · உங்கள் வேகத்தில்" if language == "தமிழ்" else "Tamil Nadu · Source-aware · At your pace"}</span>
  </div>
  <div class="hero-main">
    <div class="eyebrow">{"நம்பிக்கையுடன் உங்கள் இல்லத்தைத் தேடுங்கள்" if language == "தமிழ்" else "A clearer way home, with trust at every step"}</div>
    <h1>{"உங்கள் அடுத்த இடம்<br><em>ஒரு உரையாடலில்</em> தொடங்குகிறது." if language == "தமிழ்" else "Your next place <br>starts with <em>a conversation.</em>"}</h1>
    <p>{"சேமிக்கப்பட்ட வீடுகள், மனைகள், ஏலப் பதிவுகளை AI வழிகாட்டியுடன் பாருங்கள். நீங்கள் நினைப்பதிலிருந்து தொடங்கலாம்—அவசரமில்லை." if language == "தமிழ்" else "Explore saved homes, plots and auction records with a considerate AI guide. Start with whatever is on your mind—there’s no rush to search."}</p>
    <a class="hero-cta" href="#here-when-you-re-ready">{"உங்கள் வழிகாட்டியுடன் பேசுங்கள்" if language == "தமிழ்" else "Talk with your guide"} <span aria-hidden="true">↓</span></a>
  </div>
  <aside class="hero-panel">
    <div class="hero-panel-top"><span>{"உங்கள் தேடல், உங்கள் வேகம்" if language == "தமிழ்" else "YOUR SEARCH, YOUR PACE"}</span><span class="hero-ai">● {"AI வழிகாட்டி" if language == "தமிழ்" else "AI GUIDE"}</span></div>
    <h2>{"எங்கிருந்து வேண்டுமானாலும் தொடங்கலாம்." if language == "தமிழ்" else "Start wherever you are."}</h2>
    <p>{"நீங்கள் தயாராகும் வரை பட்ஜெட் தேர்வு செய்யவோ பட்டியல்களைப் பார்க்கவோ தேவையில்லை." if language == "தமிழ்" else "No need to choose a budget or view listings until you’re ready."}</p>
    <div class="hero-steps">
      <div class="hero-step"><strong>01</strong><span>{"உங்கள் எண்ணத்தைப் பகிருங்கள்" if language == "தமிழ்" else "Share what’s on your mind"}</span></div>
      <div class="hero-step"><strong>02</strong><span>{"கேட்டால் மட்டும் பாருங்கள்" if language == "தமிழ்" else "Explore only when you ask"}</span></div>
      <div class="hero-step"><strong>03</strong><span>{"சேமித்த ஆதாரத்தைச் சரிபாருங்கள்" if language == "தமிழ்" else "Check the saved source"}</span></div>
    </div>
  </aside>
</section>
''', unsafe_allow_html=True)

try:
    properties = cached_properties(
        PROPERTIES_FILE.stat().st_mtime_ns,
        datetime.now(INDIA_TZ).date().isoformat(),
        PRICE_NORMALIZER_VERSION,
    )
    sources = cached_sources(SOURCE_FILE.stat().st_mtime_ns)
except Exception as exc:
    st.error(f"I couldn't load the local property files: {exc}")
    st.stop()

st.markdown('<div class="trust-row"><span class="trust-pill">⌂ '+("தமிழ்நாடு கவனம்" if language == "தமிழ்" else "Tamil Nadu focus")+'</span><span class="trust-pill">◉ '+("சேமித்த சொத்துத் தகவல்" if language == "தமிழ்" else "Saved property information")+'</span><span class="trust-pill">↗ '+("முடிவுகளில் ஆதார இணைப்புகள்" if language == "தமிழ்" else "Source links on each result")+'</span><span class="trust-pill">! '+("நேரடி கிடைப்பை உறுதி செய்யாது" if language == "தமிழ்" else "Snapshots are not live availability")+'</span></div>', unsafe_allow_html=True)
import_date = next((value for value in properties["date_checked"] if value), "not recorded")


def queue_mira_filter_sync(intent) -> None:
    """Mirror a clear Mira search into the visible filters on the next rerun."""
    current = dict(st.session_state.get("applied_property_filters") or {})
    current.setdefault("location", [])
    current.setdefault("property_type", [])
    current.setdefault("status", [])
    current.setdefault("use_budget", False)
    current.setdefault("max_budget_lakh", 0.0)
    current.setdefault("use_size", False)
    current.setdefault("min_area", 0.0)
    current.setdefault("use_bedrooms", False)
    current.setdefault("bedrooms", 1)
    current.setdefault("include_ended", False)

    if intent.location:
        location_options = sorted({
            str(value).strip()
            for column in ("city", "district", "locality")
            for value in properties[column]
            if str(value).strip()
        })
        needle = intent.location.casefold()
        exact = [value for value in location_options if value.casefold() == needle]
        matches = exact or [value for value in location_options if needle in value.casefold()]
        current["location"] = matches or [intent.location]
    if intent.property_type != "Any":
        current["property_type"] = [intent.property_type]
    if intent.status != "Any":
        current["status"] = [intent.status]
    if intent.max_budget is not None:
        current["use_budget"] = True
        current["max_budget_lakh"] = intent.max_budget / 100_000
    if intent.min_area_sqm is not None:
        current["use_size"] = True
        current["min_area"] = intent.min_area_sqm
    if intent.bedrooms is not None:
        current["use_bedrooms"] = True
        current["bedrooms"] = intent.bedrooms

    listing_view = "auctions" if intent.status == "Auction" else (
        "sales" if intent.status in ("Existing sale", "Project reference") else "all"
    )
    st.session_state.mira_pending_filter_sync = {
        "filters": current,
        "listing_view": listing_view,
    }


pending_mira_sync = st.session_state.pop("mira_pending_filter_sync", None)
if pending_mira_sync:
    synced = pending_mira_sync["filters"]
    sync_locations = sorted({
        str(value).strip()
        for column in ("city", "district", "locality")
        for value in properties[column]
        if str(value).strip()
    })
    selected_location_set = set(synced.get("location", []))
    for index, value in enumerate(sync_locations):
        st.session_state[f"filter_location_option_{index}"] = value in selected_location_set
    for value in ("Plot", "House", "Flat"):
        st.session_state[f"filter_property_type_{value.casefold()}"] = value in synced.get("property_type", [])
    for value in ("Existing sale", "Project reference", "Auction"):
        key_value = value.casefold().replace(" ", "_")
        st.session_state[f"filter_listing_kind_{key_value}"] = value in synced.get("status", [])
    st.session_state["filter_use_budget"] = bool(synced.get("use_budget"))
    st.session_state["filter_preferred_budget"] = float(synced.get("max_budget_lakh") or 0.0)
    st.session_state["filter_use_size"] = bool(synced.get("use_size"))
    st.session_state["filter_preferred_size"] = float(synced.get("min_area") or 0.0)
    st.session_state["filter_use_bedrooms"] = bool(synced.get("use_bedrooms"))
    st.session_state["filter_preferred_bedrooms"] = int(synced.get("bedrooms") or 1)
    st.session_state["filter_include_ended"] = bool(synced.get("include_ended"))
    st.session_state["filter_location_query"] = (synced.get("location") or [""])[0]
    st.session_state.applied_property_filters = synced.copy()
    st.session_state.active_listing_view = pending_mira_sync.get("listing_view", "all")

def render_owner_dashboard_access() -> None:
    """Keep the owner entry above public filters and gate the dashboard by sign-in."""
    if st.session_state.owner_dashboard_authenticated:
        st.success("Mira Studio access enabled")
        if st.button("Sign out of Mira Studio", use_container_width=True):
            st.session_state.owner_dashboard_authenticated = False
            st.session_state.owner_dashboard_login_open = False
            st.rerun()
        return

    login_button_label = tr("Close sign-in") if st.session_state.owner_dashboard_login_open else "Mira Studio sign-in"
    st.button(login_button_label, key="owner_dashboard_login_toggle", use_container_width=True,
              on_click=lambda: setattr(st.session_state, "owner_dashboard_login_open", not st.session_state.owner_dashboard_login_open))
    if not st.session_state.owner_dashboard_login_open:
        return
    if configured_dashboard_password:
        with st.form("owner_dashboard_sign_in"):
            st.markdown(f"**{tr('Mira Studio sign-in')}**")
            dashboard_password_attempt = st.text_input(tr("Mira Studio sign-in"), type="password", label_visibility="collapsed")
            submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            if hmac.compare_digest(dashboard_password_attempt, configured_dashboard_password):
                st.session_state.owner_dashboard_authenticated = True
                st.session_state.owner_dashboard_login_open = False
                st.rerun()
            st.error("That sign-in did not match.")
    else:
        st.info("Mira Studio access is not configured yet. Set OWNER_DASHBOARD_PASSWORD in Streamlit secrets before signing in.")


with st.sidebar:
    if owner_request_is_local:
        render_owner_dashboard_access()
        st.markdown("---")
    locations = sorted({str(v).strip() for c in ("city", "district", "locality") for v in properties[c] if str(v).strip()})
    if st.session_state.pop("clear_filter_widgets_on_next_run", False):
        for index in range(len(locations)):
            st.session_state.pop(f"filter_location_option_{index}", None)
        for key in (
            "filter_property_type_plot", "filter_property_type_house", "filter_property_type_flat",
            "filter_listing_kind_existing_sale", "filter_listing_kind_project_reference", "filter_listing_kind_auction",
            "filter_preferred_budget", "filter_preferred_size", "filter_preferred_bedrooms", "filter_include_ended",
        ):
            st.session_state.pop(key, None)
    with st.container(border=True, key="filter-panel-scroll"):
        with st.container(border=True):
            st.markdown(
                f'<div class="filter-heading"><span class="filter-heading-icon">⌂</span>'
                f'<span class="filter-heading-copy"><span class="filter-heading-title">{tr("Find your kind of place")}</span>'
                f'<span class="filter-heading-subtitle">{tr("Choose what matters to you")}</span></span></div>',
                unsafe_allow_html=True,
            )
            st.caption(tr("Choose filters and results will update automatically."))
            location_query = st.text_input(tr("Search locations"), key="filter_location_query", placeholder=tr("Search locations"))
            matching_locations = [
                (index, value) for index, value in enumerate(locations)
                if not location_query.strip()
                or location_query.casefold() in value.casefold()
                or location_query.casefold() in localized_place_name(value).casefold()
            ]
            visible_locations = matching_locations[:40]
            selected_locations = [
                value for index, value in enumerate(locations)
                if st.session_state.get(f"filter_location_option_{index}", False)
            ]
            with st.expander(f"{tr('Choose locations')} ({len(selected_locations)} selected)", expanded=bool(location_query or selected_locations)):
                with st.container(height=220, border=True):
                    if not matching_locations:
                        st.caption(tr("No locations match"))
                    elif len(matching_locations) > len(visible_locations):
                        st.caption(tr("Showing the first 40 locations; type more to narrow the list."))
                    for index, value in visible_locations:
                        st.checkbox(localized_place_name(value), key=f"filter_location_option_{index}")
            location_filter = [
                value for index, value in enumerate(locations)
                if st.session_state.get(f"filter_location_option_{index}", False)
            ]

            type_column, status_column = st.columns(2, gap="small")
            with type_column:
                st.markdown(f"**{tr('Property type')}**")
                type_filter = [value for value in ("Plot", "House", "Flat") if st.checkbox(tr(value), key=f"filter_property_type_{value.casefold()}")]
            with status_column:
                st.markdown(f"**{tr('Listing kind')}**")
                status_filter = [value for value in ("Existing sale", "Project reference", "Auction") if st.checkbox(tr(value), key=f"filter_listing_kind_{value.casefold().replace(' ', '_')}")]

            budget_column, size_column = st.columns(2, gap="small")
            with budget_column:
                max_budget_lakh = st.number_input(
                    tr("Preferred budget (₹ lakh)"), min_value=0.0, step=5.0,
                    help="0 என விடுங்கள்; பட்ஜெட் வரம்பு வேண்டாம்." if language == "தமிழ்" else "Enter 0 for any budget.",
                    key="filter_preferred_budget",
                )
                use_budget_filter = max_budget_lakh > 0
            with size_column:
                min_area = st.number_input(tr("Preferred size (m²)"), min_value=0.0, step=10.0,
                                           help="0 என விடுங்கள்; அளவு வரம்பு வேண்டாம்." if language == "தமிழ்" else "Enter 0 for any size.",
                                           key="filter_preferred_size")
                use_size_filter = min_area > 0

            bedrooms_column, auction_column = st.columns(2, gap="small")
            with bedrooms_column:
                preferred_bedrooms = st.number_input("Bedrooms (BHK: 0–9)", min_value=0, max_value=9, step=1,
                                                     help="0 என்றால் எந்த BHK-யும்." if language == "தமிழ்" else "0 means any BHK; choose 1, 2, 3, and so on to filter.",
                                                     key="filter_preferred_bedrooms")
                use_bedrooms_filter = preferred_bedrooms > 0
            with auction_column:
                include_ended = st.checkbox(tr("Include ended auctions"), key="filter_include_ended")

        current_filter_snapshot = {
            "location": location_filter,
            "property_type": type_filter,
            "status": status_filter,
            "use_budget": use_budget_filter,
            "max_budget_lakh": max_budget_lakh,
            "use_size": use_size_filter,
            "min_area": min_area,
            "use_bedrooms": use_bedrooms_filter,
            "bedrooms": preferred_bedrooms,
            "include_ended": include_ended,
        }
        applied_filter_snapshot = st.session_state.get("applied_property_filters")
        if applied_filter_snapshot is not None and current_filter_snapshot != applied_filter_snapshot:
            # Streamlit reruns when a filter widget changes. Commit this new
            # snapshot immediately and show the filtered catalogue on that run.
            st.session_state.main_results_mode = "filters"
            st.session_state.main_results_total_count = 0
            if st.session_state.get("active_listing_view") == "none":
                st.session_state.active_listing_view = "all"
            st.session_state.filters_applied = True
        st.session_state.applied_property_filters = current_filter_snapshot.copy()
    st.markdown("---")
    st.markdown(f"**{tr('A careful note')}**")
    st.caption("ஏலம் மற்றும் விற்பனை விவரங்கள் சேமிக்கப்பட்ட ஆதாரங்களில் இருந்து எடுக்கப்பட்டவை. தற்போதைய நிலை, உரிமை, உடைமை, காலக்கெடு மற்றும் கடன் தகுதியை அதிகாரப்பூர்வ ஆதாரத்தில் உறுதிப்படுத்தவும்." if language == "தமிழ்" else "Auction and sale details are copied from saved source files. Confirm live status, title, possession, deadlines and loan eligibility with the official source before acting.")

if owner_request_is_local and st.session_state.owner_dashboard_authenticated:
    # A successful sign-in now opens a dedicated main-page dashboard. Keeping
    # this out of dynamically inserted tabs makes the export easy to find.
    st.title("Mira Studio")
    st.caption("A clear view of saved records, customer conversations, and owner-tracked outcomes. Property counts describe saved records, not live availability.")
    st.markdown("""
    <div class="owner-dashboard-hero" style="background:linear-gradient(115deg,#075e5a 0%,#0b8d83 58%,#ef704e 100%);border-radius:18px;padding:24px 28px;margin:8px 0 20px;color:#fff;box-shadow:0 16px 34px rgba(3,48,48,.30)">
      <div style="font-size:12px;font-weight:750;letter-spacing:.14em;opacity:.9">NAMMA ILLAM · MIRA STUDIO</div>
      <div style="font-size:27px;font-weight:750;margin-top:5px">A clearer view of every inquiry</div>
      <div style="font-size:14px;margin-top:5px;opacity:.94">Review conversations, improve Mira, and track the website blueprint in one private workspace.</div>
      <div class="owner-hero-pills"><span>● Live signals</span><span>✦ Private workspace</span><span>↗ Action-ready insights</span></div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("""
    <style>
    div[data-testid="stMetric"] { background: linear-gradient(135deg,#ffffff 0%,#edf9f6 100%); border: 1px solid rgba(202,234,227,.9); border-left: 5px solid #17a398; border-radius: 16px; padding: 15px 16px; box-shadow: 0 9px 20px rgba(1,43,47,.14); transition:transform .18s ease,box-shadow .18s ease; }
    div[data-testid="stMetric"]:hover { transform:translateY(-3px);box-shadow:0 14px 26px rgba(1,43,47,.22); }
    div[data-testid="stMetric"] label { color:#254650; font-weight:700; }
    div[data-testid="stMetricValue"] { color:#123D4B; }
    div[data-testid="stDownloadButton"] button { background:linear-gradient(105deg,#087d78,#12a59a); color:white; border:0; border-radius:12px; font-weight:700; min-height:48px; }
    div[data-testid="stDownloadButton"] button:hover { background:linear-gradient(105deg,#066762,#0b8d83); color:white; }
    .block-container h1,.block-container h2,.block-container h3 { color:#123D4B!important; }
    .block-container [data-testid="stMarkdownContainer"] p,.block-container [data-testid="stCaptionContainer"] p { color:#334F58!important; }
    .block-container label,.block-container [data-testid="stDataEditor"] { color:#23444E!important; }
    /* Give the owner workspace a richer teal surface while keeping controls
       and KPI cards light enough to stay easy to read. */
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container {
      background:linear-gradient(145deg,rgba(9,105,100,.97) 0%,rgba(7,82,88,.97) 100%)!important;color:#F5FFFD!important;text-shadow:none!important;
      border:1px solid rgba(196,244,235,.32)!important;box-shadow:0 16px 42px rgba(4,25,31,.32)!important
    }
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container h1,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container h2,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container h3,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container h4,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container p,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container li,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container label,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stCaptionContainer"],
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stCaptionContainer"] p,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stMarkdownContainer"],
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stMarkdownContainer"] p,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stMetricLabel"],
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stMetricValue"] {
      color:#F5FFFD!important;-webkit-text-fill-color:#F5FFFD!important;text-shadow:none!important;opacity:1!important
    }
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container div[data-testid="stMetric"] [data-testid="stMetricLabel"],
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container div[data-testid="stMetric"] [data-testid="stMetricValue"] {
      color:#123D4B!important;-webkit-text-fill-color:#123D4B!important
    }
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stAlert"] p,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stAlert"] div {
      color:#19363E!important;-webkit-text-fill-color:#19363E!important
    }
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stSelectbox"] [role="combobox"],
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stTextInput"] input,
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stDateInput"] input {
      background:#FFFFFF!important;color:#19363E!important;-webkit-text-fill-color:#19363E!important;text-shadow:none!important;border-color:#B8D4CF!important
    }
    .stApp:has(.owner-dashboard-hero) section[data-testid="stMain"] .block-container [data-testid="stDataEditor"] { color:#19363E!important; }
    .owner-dashboard-hero { position:relative;overflow:hidden; }
    .owner-dashboard-hero:after { content:"";position:absolute;width:250px;height:250px;border-radius:999px;background:rgba(255,255,255,.12);right:-85px;top:-125px; }
    .owner-dashboard-hero > div { position:relative;z-index:1; }
    .owner-hero-pills { display:flex;flex-wrap:wrap;gap:8px;margin-top:16px; }
    .owner-hero-pills span { background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:6px 10px;font-size:12px;font-weight:700;backdrop-filter:blur(8px); }
    .stApp:has(.owner-dashboard-hero) [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(2) [data-testid="stMetric"] { border-left-color:#5e87f5;background:linear-gradient(135deg,#ffffff,#eef2ff); }
    .stApp:has(.owner-dashboard-hero) [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(3) [data-testid="stMetric"] { border-left-color:#f3a437;background:linear-gradient(135deg,#fffefd,#fff5df); }
    .stApp:has(.owner-dashboard-hero) [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(4) [data-testid="stMetric"] { border-left-color:#ed6c5d;background:linear-gradient(135deg,#fffefe,#fff0ed); }
    .stApp:has(.owner-dashboard-hero) [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:nth-child(5) [data-testid="stMetric"] { border-left-color:#a46ad7;background:linear-gradient(135deg,#fffefe,#f8efff); }
    .stApp:has(.owner-dashboard-hero) [class*="st-key-dashboard-chart-card"],
    .stApp:has(.owner-dashboard-hero) .st-key-dashboard-activity-card { background:linear-gradient(150deg,rgba(15,77,79,.76),rgba(9,55,65,.82));border:1px solid rgba(196,244,235,.24);border-radius:18px;padding:14px 16px 5px;box-shadow:0 12px 24px rgba(2,37,42,.20); }
    .stApp:has(.owner-dashboard-hero) [class*="st-key-dashboard-chart-card"] h4,
    .stApp:has(.owner-dashboard-hero) .st-key-dashboard-activity-card h4 { color:#ffffff!important;letter-spacing:.01em; }
    </style>
    """, unsafe_allow_html=True)
    chart_palette = ["#42D5C6", "#FF8976", "#FFC65A", "#78A2FF", "#B48BFF", "#72D6A5", "#F291C2"]
    with st.expander("Mira Studio health and readiness", expanded=False):
        health_cols = st.columns(3)
        health_cols[0].metric("AI provider", AI_PROVIDER.title())
        health_cols[1].metric("Hosted AI", "Configured" if bool(AI_API_KEY) else "Local fallback")
        health_cols[2].metric("Persistent storage", "Connected" if storage_backend.is_configured() else "Fallback files")
        if not AI_API_KEY:
            st.info("Add GROQ_API_KEY in Streamlit Secrets when you want hosted Mira reasoning. Local property search and safety flows remain available without it.")
        if not storage_backend.is_configured():
            st.info("Add DATABASE_URL in Streamlit Secrets to keep hosted chat records and approved Learning Library rules across restarts.")
        st.caption("Email follow-ups are intentionally excluded from this readiness view.")
    blueprint_path = ROOT / "WEBSITE_BLUEPRINT.md"
    with st.expander("Website Blueprint", expanded=False):
        st.caption("Private product and engineering map. It contains no passwords, API keys, or customer conversation text.")
        blueprint_visual = ROOT / "static" / "mira-blueprint-map.png"
        if blueprint_visual.exists():
            st.image(blueprint_visual, caption="Mira's end-to-end customer, property, review, and learning flow", use_container_width=True)
        st.markdown("""
        <div class="blueprint-stage-grid">
          <div class="blueprint-stage stage-teal"><b>👤 Customer message</b><span>Receives the customer's request, language, and context.</span></div>
          <div class="blueprint-stage stage-blue"><b>🧠 Understand intent</b><span>Detects language, need, emotion, and preferences.</span></div>
          <div class="blueprint-stage stage-coral"><b>🏠 Search property data</b><span>Finds relevant homes, auctions, sources, and filters.</span></div>
          <div class="blueprint-stage stage-amber"><b>🔎 Verify listing details</b><span>Explains saved facts and highlights what must be verified.</span></div>
          <div class="blueprint-stage stage-violet"><b>💬 Mira response</b><span>Creates a clear, safe, human-friendly answer.</span></div>
          <div class="blueprint-stage stage-mint"><b>🗂️ Save chat record</b><span>Stores structured signals, ratings, and follow-up state.</span></div>
          <div class="blueprint-stage stage-sky"><b>🔍 Quality Review</b><span>Finds missed intent, frustration, or correction opportunities.</span></div>
          <div class="blueprint-stage stage-pink"><b>✅ Approve learning rule</b><span>Turns reviewed improvements into approved Mira guidance.</span></div>
        </div>
        <div class="blueprint-branch-title">Conversation decision paths from the original map</div>
        <div class="blueprint-branch-grid">
          <div class="blueprint-branch"><b>🧭 What does the customer need?</b><span>Routes the message to the most useful response path.</span></div>
          <div class="blueprint-branch"><b>🏘️ Find property</b><span>Searches saved properties using location, budget, BHK, and listing preferences.</span></div>
          <div class="blueprint-branch"><b>📄 Ask about listing</b><span>Explains verified price, source, availability, and property details.</span></div>
          <div class="blueprint-branch"><b>🛠️ Correction or frustration</b><span>Acknowledges the concern, removes unwanted suggestions, and corrects course.</span></div>
          <div class="blueprint-branch"><b>📅 Follow-up request</b><span>Collects consent and contact preference without promising a call.</span></div>
          <div class="blueprint-branch"><b>🙏 Thanks or compliment</b><span>Thanks the customer and offers the next relevant help.</span></div>
          <div class="blueprint-branch"><b>📚 Apply approved Mira rules</b><span>Uses only owner-approved guidance for similar situations.</span></div>
          <div class="blueprint-branch"><b>✍️ Generate human-friendly reply</b><span>Combines the current request, verified data, and approved guidance.</span></div>
          <div class="blueprint-branch"><b>📝 Draft Learning Library rule</b><span>Turns repeated quality cues into an editable draft, never an automatic behavior change.</span></div>
        </div>
        <style>
        .blueprint-stage-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:10px 0 18px}
        .blueprint-stage{border-radius:14px;padding:13px 14px;min-height:86px;border:1px solid rgba(255,255,255,.3);box-shadow:0 8px 18px rgba(3,35,45,.18);color:#fff}
        .blueprint-stage b{display:block;font-size:14px;margin-bottom:7px}.blueprint-stage span{display:block;font-size:12px;line-height:1.45;opacity:.96}
        .stage-teal{background:linear-gradient(135deg,#087d78,#10b7ab)} .stage-blue{background:linear-gradient(135deg,#1264d8,#398ef6)}
        .stage-coral{background:linear-gradient(135deg,#e6574c,#f58969)} .stage-amber{background:linear-gradient(135deg,#df9911,#f6bd3f)}
        .stage-violet{background:linear-gradient(135deg,#6540db,#9269f4)} .stage-mint{background:linear-gradient(135deg,#159d76,#45d2a3)}
        .stage-sky{background:linear-gradient(135deg,#087fc1,#42b8f2)} .stage-pink{background:linear-gradient(135deg,#c93c86,#f267ad)}
        @media(max-width:800px){.blueprint-stage-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:480px){.blueprint-stage-grid{grid-template-columns:1fr}}
        .blueprint-branch-title{font-size:15px;font-weight:750;color:#E8FFFA;margin:8px 0 10px}
        .blueprint-branch-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:0 0 18px}
        .blueprint-branch{background:rgba(255,255,255,.12);border:1px solid rgba(196,244,235,.28);border-radius:12px;padding:11px 13px;color:#F5FFFD;min-height:78px}
        .blueprint-branch b{display:block;font-size:13px;margin-bottom:5px}.blueprint-branch span{display:block;font-size:11px;line-height:1.45;opacity:.93}
        @media(max-width:800px){.blueprint-branch-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:480px){.blueprint-branch-grid{grid-template-columns:1fr}}
        </style>
        """, unsafe_allow_html=True)
        if blueprint_path.exists():
            blueprint_text = blueprint_path.read_text(encoding="utf-8")
            st.markdown(blueprint_text)
            st.download_button("Download blueprint", data=blueprint_text, file_name="namma_illam_website_blueprint.md", mime="text/markdown", key="download_website_blueprint")
        else:
            st.info("The blueprint file is not available in this deployment yet.")

    def dashboard_bar_chart(data, category, value, *, height=250):
        st.vega_lite_chart(data, {
            "background": "transparent",
            "height": height,
            "mark": {"type": "bar", "cornerRadiusEnd": 10, "cornerRadiusTopLeft": 10, "height": {"band": 0.64}},
            "encoding": {
                "x": {"field": value, "type": "quantitative", "axis": {"title": None, "labelColor": "#F0FFFC", "gridColor": "#3B8580", "tickColor": "#8FCBC2"}},
                "y": {"field": category, "type": "nominal", "sort": "-x", "axis": {"title": None, "labelColor": "#F0FFFC", "labelFontWeight": 600, "domain": False, "ticks": False}},
                "color": {"field": category, "type": "nominal", "scale": {"range": chart_palette}, "legend": None},
                "tooltip": [{"field": category, "type": "nominal", "title": category}, {"field": value, "type": "quantitative", "title": value}],
            },
            "config": {"view": {"stroke": None}, "axis": {"labelFont": "DM Sans", "titleFont": "DM Sans", "labelFontSize": 12, "grid": True, "gridOpacity": 0.34}, "tooltip": {"fill": "#102F38", "stroke": "#77D8CA", "color": "#FFFFFF"}},
        }, use_container_width=True)

    def dashboard_donut_chart(data, category, value):
        st.vega_lite_chart(data, {
            "background": "transparent",
            "height": 250,
            "mark": {"type": "arc", "innerRadius": 67, "outerRadius": 108, "padAngle": 0.025, "stroke": "#0c4a51", "strokeWidth": 3, "cornerRadius": 5},
            "encoding": {
                "theta": {"field": value, "type": "quantitative", "stack": True},
                "color": {"field": category, "type": "nominal", "scale": {"range": chart_palette}, "legend": {"orient": "bottom", "title": None, "labelColor": "#F0FFFC", "labelFontSize": 12}},
                "tooltip": [{"field": category, "type": "nominal", "title": category}, {"field": value, "type": "quantitative", "title": value}],
            },
            "config": {"view": {"stroke": None}},
        }, use_container_width=True)

    def dashboard_activity_chart(data, period):
        st.vega_lite_chart(data, {
            "background": "transparent",
            "height": 230,
            "layer": [
                {"mark": {"type": "area", "interpolate": "monotone", "line": {"color": "#C4FFF1", "strokeWidth": 3}, "color": {"x1": 1, "y1": 0, "x2": 1, "y2": 1, "gradient": "linear", "stops": [{"offset": 0, "color": "#50C0AD"}, {"offset": 1, "color": "#E4F5EF"}]}}, "encoding": {"x": {"field": period, "type": "ordinal", "axis": {"title": None, "labelColor": "#F0FFFC", "labelAngle": -25, "domain": False, "ticks": False}}, "y": {"field": "Inquiry turns", "type": "quantitative", "axis": {"title": None, "labelColor": "#F0FFFC", "gridColor": "#3B8580"}}, "tooltip": [{"field": period, "type": "ordinal"}, {"field": "Inquiry turns", "type": "quantitative"}]}},
                {"mark": {"type": "line", "interpolate": "monotone", "color": "#087D78", "strokeWidth": 3, "point": {"filled": True, "fill": "#F05D43", "stroke": "#FFFDF8", "strokeWidth": 2, "size": 95}}, "encoding": {"x": {"field": period, "type": "ordinal"}, "y": {"field": "Inquiry turns", "type": "quantitative"}}},
            ],
            "config": {"view": {"stroke": None}, "axis": {"labelFont": "DM Sans", "titleFont": "DM Sans", "labelFontSize": 11, "grid": True}},
        }, use_container_width=True)
    current = cached_properties(
        PROPERTIES_FILE.stat().st_mtime_ns,
        datetime.now(INDIA_TZ).date().isoformat(),
        PRICE_NORMALIZER_VERSION,
    )
    status_counts = current["listing_status"].value_counts()
    source_counts = current.groupby("source_name", dropna=False).size().sort_values(ascending=False)
    valid_prices = current[current["price_inr"].notna()]
    data_modified = datetime.fromtimestamp(PROPERTIES_FILE.stat().st_mtime).astimezone().strftime("%d %b %Y, %I:%M %p %Z")
    st.caption(f"Property file last changed: {data_modified} · Imported source date: {import_date}")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Saved property records", f"{len(current):,}")
    metric_cols[1].metric("Auction records", f"{int(status_counts.get('Auction', 0)):,}")
    metric_cols[2].metric("Sale listing snapshots", f"{int(status_counts.get('Existing sale', 0)):,}")
    metric_cols[3].metric("Records with a reported price", f"{len(valid_prices):,}")
    chart_left, chart_right = st.columns(2)
    with chart_left:
        with st.container(key="dashboard_chart_card"):
            st.markdown("#### Records by category")
            category_chart = status_counts.rename_axis("Category").rename("Saved records").reset_index()
            dashboard_bar_chart(category_chart, "Category", "Saved records")
    with chart_right:
        with st.container(key="dashboard_chart_card_source"):
            st.markdown("#### Records by source")
            source_chart = source_counts.rename_axis("Source").rename("Saved records").reset_index()
            dashboard_bar_chart(source_chart, "Source", "Saved records")
    st.info("CMDA entries show planning permission details only. Verify title, current availability and auction terms with the official source.")

    st.markdown("---")
    st.subheader("Private inquiry history")
    st.caption("Each row is one chat turn. The export includes conversation signals and owner-maintained follow-up and outcome fields.")
    st.caption(f"Storage: {storage_backend.mode()}. Configure DATABASE_URL in Streamlit Secrets to keep hosted chats and approved rules across restarts.")
    try:
        inquiry_stat = INQUIRY_LOG_PATH.stat() if INQUIRY_LOG_PATH.exists() else None
        inquiry_rows = cached_inquiries(
            storage_backend.revision(inquiry_stat.st_mtime_ns if inquiry_stat else 0),
            inquiry_stat.st_size if inquiry_stat else 0,
        )
        today = datetime.now(INDIA_TZ).date()

        def inquiry_date(row):
            value = pd.to_datetime(row.get("Timestamp (Asia/Calcutta)") or row.get("Timestamp (Asia/Kolkata)"), errors="coerce")
            if pd.isna(value):
                return None
            value = value.tz_localize(INDIA_TZ) if value.tzinfo is None else value.tz_convert(INDIA_TZ)
            return value.date()

        dated_rows = [(row, inquiry_date(row)) for row in inquiry_rows]
        available_dates = [date_value for _, date_value in dated_rows if date_value]
        period_col, value_col = st.columns([1, 2])
        with period_col:
            date_filter_mode = st.selectbox("Filter inquiry data by", ["All time", "Day", "Month", "Year"], key="dashboard_date_filter_mode")
        filter_start, filter_end = None, None
        if date_filter_mode == "Day":
            with value_col:
                selected_day = st.date_input("Choose a day", value=today, key="dashboard_filter_day")
            filter_start = filter_end = selected_day
            period_label = selected_day.strftime("%d %B %Y")
        elif date_filter_mode == "Month":
            month_keys = sorted({date_value.strftime("%Y-%m") for date_value in available_dates} | {today.strftime("%Y-%m")})
            with value_col:
                selected_month = st.selectbox("Choose a month", month_keys, index=month_keys.index(today.strftime("%Y-%m")), format_func=lambda value: datetime.strptime(value, "%Y-%m").strftime("%B %Y"), key="dashboard_filter_month")
            month_start = datetime.strptime(selected_month, "%Y-%m").date()
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            filter_start, filter_end = month_start, next_month - timedelta(days=1)
            period_label = month_start.strftime("%B %Y")
        elif date_filter_mode == "Year":
            years = sorted({date_value.year for date_value in available_dates} | {today.year}, reverse=True)
            with value_col:
                selected_year = st.selectbox("Choose a year", years, index=years.index(today.year), key="dashboard_filter_year")
            filter_start, filter_end = datetime(int(selected_year), 1, 1).date(), datetime(int(selected_year), 12, 31).date()
            period_label = str(selected_year)
        else:
            period_label = "All available dates"

        filtered_rows = inquiry_rows if filter_start is None else [row for row, date_value in dated_rows if date_value and filter_start <= date_value <= filter_end]
        start_label = filter_start.isoformat() if filter_start else "All available dates"
        end_label = filter_end.isoformat() if filter_end else "All available dates"
        st.caption(f"Showing {len(filtered_rows):,} inquiry turns for {period_label}. The Excel download below uses this same date filter.")
        unique_users = {str(row.get("User ID") or "").strip() for row in filtered_rows if str(row.get("User ID") or "").strip()}
        conversations = {str(row.get("Conversation ID") or "").strip() for row in filtered_rows if str(row.get("Conversation ID") or "").strip()}
        matched_inquiries = sum(
            pd.notna(pd.to_numeric(row.get("Matching records"), errors="coerce"))
            and pd.to_numeric(row.get("Matching records"), errors="coerce") > 0
            for row in filtered_rows
        )
        def field_count(field: str, accepted: set[str]) -> int:
            return sum(str(row.get(field) or "").strip().casefold() in accepted for row in filtered_rows)

        followup_requests = field_count("Follow-up requested signal", {"yes"})
        handoff_requests = field_count("Human handoff requested signal", {"yes"})
        followups_completed = field_count("Follow-up status (owner)", {"completed"})
        followups_open = field_count("Follow-up status (owner)", {"needed", "scheduled"})
        ended_conversations = len({
            str(row.get("Conversation ID") or "").strip()
            for row in filtered_rows
            if str(row.get("Conversation status") or "").strip().casefold() == "ended"
            and str(row.get("Conversation ID") or "").strip()
        })
        tracked_sold = field_count("Sale outcome (owner)", {"sold"})
        live_listings = field_count("Listing status (owner)", {"live"})
        satisfied_count = field_count("Customer satisfaction (owner)", {"satisfied"})
        dissatisfied_count = field_count("Customer satisfaction (owner)", {"dissatisfied", "needs follow-up"})
        interested_count = field_count("Customer interest (owner)", {"interested"})
        budget_count = field_count("Budget mentioned signal", {"yes"})
        rating_summary = customer_summary_rows(filtered_rows)
        ratings = [
            pd.to_numeric(summary.get("Mira performance rating (1-5)"), errors="coerce")
            for summary in rating_summary
        ]
        ratings = [float(rating) for rating in ratings if pd.notna(rating)]
        kpi_cols = st.columns(5)
        kpi_cols[0].metric("Inquiry turns in period", f"{len(filtered_rows):,}")
        kpi_cols[1].metric("Unique user sessions", f"{len(unique_users):,}")
        kpi_cols[2].metric("Conversations", f"{len(conversations):,}")
        kpi_cols[3].metric("Budget mentions", f"{budget_count:,}")
        purchase_values = sum(bool(str(row.get("Purchase value / offer stated") or "").strip()) for row in filtered_rows)
        kpi_cols[4].metric("Purchase values stated", f"{purchase_values:,}")
        outcome_cols = st.columns(5)
        outcome_cols[0].metric("Satisfied", f"{satisfied_count:,}")
        outcome_cols[1].metric("Needs satisfaction follow-up", f"{dissatisfied_count:,}")
        outcome_cols[2].metric("Marked interested", f"{interested_count:,}")
        outcome_cols[3].metric("Follow-ups open", f"{followups_open:,}", help="Owner-marked as Needed or Scheduled.")
        outcome_cols[4].metric("Follow-ups completed", f"{followups_completed:,}")
        status_cols = st.columns(5)
        status_cols[0].metric("Human handoff requests", f"{handoff_requests:,}")
        status_cols[1].metric("Owner-marked live", f"{live_listings:,}")
        status_cols[2].metric("Owner-tracked sold", f"{tracked_sold:,}")
        status_cols[3].metric("Turns with matches", f"{matched_inquiries:,}")
        status_cols[4].metric("Conversations ended", f"{ended_conversations:,}")
        rating_cols = st.columns(5)
        rating_cols[0].metric("Mira average rating", f"{sum(ratings) / len(ratings):.1f} / 5" if ratings else "Not rated")
        rating_cols[1].metric("Satisfaction ratings received", f"{len(ratings):,}")
        st.caption(f"{followup_requests:,} turns mention follow-up. Customer tone and interest signals are indicators; use owner fields to record confirmed outcomes. Customer names and address preferences are self-reported; user IDs identify browser sessions, not verified people.")

        if filtered_rows:
            st.markdown("#### Conversation overview")
            insight_left, insight_right = st.columns(2)
            frame = pd.DataFrame(filtered_rows)
            with insight_left:
                with st.container(key="dashboard_chart_card_topic"):
                    st.markdown("#### Topics customers discuss")
                    if "Conversation topic" in frame:
                        topic_data = frame["Conversation topic"].fillna("Unclassified").replace("", "Unclassified").value_counts().rename_axis("Topic").rename("Turns").reset_index()
                        dashboard_donut_chart(topic_data, "Topic", "Turns")
            with insight_right:
                with st.container(key="dashboard_chart_card_signals"):
                    st.markdown("#### Customer & follow-up signals")
                    outcome_data = pd.DataFrame({"Customer / follow-up signal": ["Satisfied", "Needs follow-up", "Interested", "Open follow-ups", "Completed"], "Count": [satisfied_count, dissatisfied_count, interested_count, followups_open, followups_completed]})
                    dashboard_bar_chart(outcome_data, "Customer / follow-up signal", "Count")
            date_values = [inquiry_date(row) for row in filtered_rows]
            timeline_frame = pd.DataFrame({"Date": date_values}).dropna()
            if not timeline_frame.empty:
                if date_filter_mode == "Day":
                    hour_values = []
                    for row in filtered_rows:
                        stamp = pd.to_datetime(row.get("Timestamp (Asia/Calcutta)") or row.get("Timestamp (Asia/Kolkata)"), errors="coerce")
                        if pd.notna(stamp):
                            hour_values.append(stamp.hour)
                    timeline = pd.Series(hour_values).value_counts().sort_index().rename_axis("Hour").rename("Inquiry turns").reset_index()
                    timeline["Hour"] = timeline["Hour"].astype(int).map(lambda hour: f"{hour:02d}:00")
                    x_axis = "Hour"
                else:
                    timeline_frame["Period"] = timeline_frame["Date"].map(lambda value: value.strftime("%Y-%m-%d") if date_filter_mode == "Month" else value.strftime("%Y-%m"))
                    timeline = timeline_frame["Period"].value_counts().sort_index().rename_axis("Period").rename("Inquiry turns").reset_index()
                    x_axis = "Period"
                with st.container(key="dashboard_activity_card"):
                    st.markdown("#### Inquiry activity over the selected period")
                    dashboard_activity_chart(timeline, x_axis)
        if filtered_rows:
            manual_export = build_inquiry_export(filtered_rows, period_label, start_label, end_label)
            st.download_button(
                f"Download {period_label} inquiry data (.xlsx)",
                data=manual_export,
                file_name=f"namma_illam_inquiries_{period_label.lower().replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="download_inquiry_history",
                on_click=archive_inquiry_export,
                args=(manual_export, "manual", period_label),
            )
            complete_chat_export = build_conversation_transcript_export(filtered_rows, period_label)
            st.download_button(
                f"Download every complete chat for {period_label} (.xlsx)",
                data=complete_chat_export,
                file_name=f"namma_illam_complete_chats_{period_label.lower().replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="download_complete_chat_archive",
            )
            st.caption("Private owner download: one row per conversation, including the saved customer messages, Mira replies, and any submitted rating.")
            st.caption(f"Automatic daily exports are refreshed as inquiries arrive and saved under {INQUIRY_ARCHIVE_DIR.relative_to(Path(__file__).resolve().parent)}\\YYYY-MM-DD. Manual downloads are archived in the same dated folder with ‘manual’ in the filename.")
            archived_daily_exports = sorted(
                INQUIRY_ARCHIVE_DIR.glob("*/automatic_inquiries_*.xlsx"),
                key=lambda item: item.parent.name,
                reverse=True,
            ) if INQUIRY_ARCHIVE_DIR.exists() else []
            if archived_daily_exports:
                selected_archive = st.selectbox(
                    "Automatic snapshot date",
                    archived_daily_exports,
                    format_func=lambda item: item.parent.name,
                    key="automatic_inquiry_archive_date",
                )
                st.download_button(
                    f"Download automatic snapshot for {selected_archive.parent.name} (.xlsx)",
                    data=structured_archive_export(selected_archive),
                    file_name=selected_archive.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="download_automatic_inquiry_snapshot",
                )
        else:
            st.info("No inquiry workbook exists yet. It will be created after the next completed chat turn.")
        if filtered_rows:
            st.markdown("#### Update follow-up and listing outcomes")
            st.caption("Downloads and customer summaries show structured preferences and Yes/No indicators. No means not recorded; confirm inferred interest with the customer.")
            owner_fields = ["Follow-up status (owner)", "Follow-up date (owner)", "Next follow-up action (owner)", "Customer satisfaction (owner)", "Lead priority (owner)", "Listing status (owner)", "Sale outcome (owner)", "Advisor notes (owner)"]
            tracked_records = pd.DataFrame(filtered_rows).tail(50).iloc[::-1].reset_index(drop=True).fillna("")
            interest_display = []
            for _, record in tracked_records.iterrows():
                owner_interest = str(record.get("Customer interest (owner)") or "").strip()
                if owner_interest in {"Interested", "Not interested", "Undecided"}:
                    interest_display.append(owner_interest)
                else:
                    interest_signal = str(record.get("Customer interest signal") or "")
                    interest_display.append({"Interested signal": "Interested", "Not interested signal": "Not interested"}.get(interest_signal, "Not stated"))
            editable_rows = pd.DataFrame({
                "Inquiry ID": tracked_records.get("Inquiry ID", ""),
                "Timestamp (Asia/Kolkata)": tracked_records.get("Timestamp (Asia/Kolkata)", ""),
                "Customer interest": interest_display,
            })
            for field in owner_fields:
                editable_rows[field] = tracked_records[field] if field in tracked_records else ""
            default_values = {
                "Follow-up status (owner)": "Not updated", "Customer satisfaction (owner)": "Not recorded",
                "Lead priority (owner)": "Not rated", "Listing status (owner)": "Not updated",
                "Sale outcome (owner)": "Not updated",
            }
            for field, default in default_values.items():
                editable_rows[field] = editable_rows[field].replace("", default)
            editor_key = f"owner_tracking_{re.sub(r'[^A-Za-z0-9]+', '_', period_label)}_{INQUIRY_LOG_PATH.stat().st_mtime_ns if INQUIRY_LOG_PATH.exists() else 0}"
            with st.form("owner_outcome_tracker"):
                edited = st.data_editor(
                    editable_rows,
                    hide_index=True,
                    use_container_width=True,
                    num_rows="fixed",
                    disabled=["Inquiry ID", "Timestamp (Asia/Kolkata)"],
                    column_config={
                        "Inquiry ID": st.column_config.TextColumn("Inquiry ID", width="medium"),
                        "Timestamp (Asia/Kolkata)": st.column_config.TextColumn("Time", width="small"),
                        "Customer interest": st.column_config.SelectboxColumn("Customer interest", options=["Interested", "Not interested", "Not stated", "Undecided"], required=True),
                        "Follow-up status (owner)": st.column_config.SelectboxColumn("Follow-up", options=["Not updated", "Needed", "Scheduled", "Completed", "Not needed"], required=True),
                        "Follow-up date (owner)": st.column_config.TextColumn("Follow-up date", help="Enter a date such as 2026-10-15"),
                        "Next follow-up action (owner)": st.column_config.TextColumn("Next action", width="medium"),
                        "Customer satisfaction (owner)": st.column_config.SelectboxColumn("Satisfaction", options=["Not recorded", "Satisfied", "Needs follow-up", "Dissatisfied"], required=True),
                        "Customer interest (owner)": st.column_config.SelectboxColumn("Interest", options=["Not recorded", "Interested", "Undecided", "Not interested"], required=True),
                        "Lead priority (owner)": st.column_config.SelectboxColumn("Priority", options=["Not rated", "High", "Medium", "Low"], required=True),
                        "Listing status (owner)": st.column_config.SelectboxColumn("Listing", options=["Not updated", "Not listed", "Draft", "Live", "Paused", "Sold", "Withdrawn"], required=True),
                        "Sale outcome (owner)": st.column_config.SelectboxColumn("Sale outcome", options=["Not updated", "Unknown", "Sold", "Not sold", "Withdrawn"], required=True),
                        "Advisor notes (owner)": st.column_config.TextColumn("Advisor notes", width="large"),
                    },
                    key=editor_key,
                )
                save_tracking = st.form_submit_button("Save outcome updates", type="primary")
            if save_tracking:
                saved = 0
                for _, tracked_row in edited.iterrows():
                    fields = {field: tracked_row.get(field, "") for field in owner_fields}
                    fields["Customer interest (owner)"] = tracked_row.get("Customer interest", "Not stated")
                    saved += bool(update_inquiry_fields(str(tracked_row.get("Inquiry ID", "")), fields))
                st.success(f"Saved updates for {saved:,} inquiry rows.")
                st.rerun()

            st.markdown("#### Mira quality review")
            st.caption("Review flagged conversations, record the intended handling, and use your notes to guide Mira improvements. Flags are review cues, not a verdict that Mira was wrong.")
            review_rows = []
            for record in reversed(filtered_rows):
                flags = quality_flags(record)
                review_status = str(record.get("Mira review status (owner)") or "").strip()
                if not flags and review_status in {"", "Not reviewed"}:
                    continue
                review_rows.append({
                    "Inquiry ID": record.get("Inquiry ID", ""),
                    "Timestamp (Asia/Kolkata)": record.get("Timestamp (Asia/Kolkata)", ""),
                    "Customer message": record.get("User inquiry", ""),
                    "Mira response": record.get("Assistant response", ""),
                    "Response type": record.get("Response type", ""),
                    "Review cues": "; ".join(flags) or "Owner-saved review",
                    "Review status": review_status or "Not reviewed",
                    "Correct intent": str(record.get("Mira corrected intent (owner)") or "").strip() or "Not set",
                    "Review notes": record.get("Mira review notes (owner)", ""),
                })
            if review_rows:
                review_frame = pd.DataFrame(review_rows[:50])
                with st.form("mira_quality_review"):
                    reviewed = st.data_editor(
                        review_frame,
                        hide_index=True,
                        use_container_width=True,
                        num_rows="fixed",
                        disabled=["Inquiry ID", "Timestamp (Asia/Kolkata)", "Customer message", "Mira response", "Response type", "Review cues"],
                        column_config={
                            "Inquiry ID": st.column_config.TextColumn("Inquiry ID", width="medium"),
                            "Timestamp (Asia/Kolkata)": st.column_config.TextColumn("Time", width="small"),
                            "Customer message": st.column_config.TextColumn("Customer message", width="large"),
                            "Mira response": st.column_config.TextColumn("Mira response", width="large"),
                            "Response type": st.column_config.TextColumn("Response type", width="small"),
                            "Review cues": st.column_config.TextColumn("Why flagged", width="medium"),
                            "Review status": st.column_config.SelectboxColumn("Review status", options=["Not reviewed", "Reviewed", "Improvement needed", "No issue"], required=True),
                            "Correct intent": st.column_config.SelectboxColumn("Correct intent", options=["Not set", "Search listings", "Update preferences", "Answer property details", "Follow-up or reminder", "Language change", "General conversation", "Safety guidance"], required=True),
                            "Review notes": st.column_config.TextColumn("Owner feedback", width="large"),
                        },
                        key=f"mira_quality_{editor_key}",
                    )
                    save_review = st.form_submit_button("Save Mira review", type="primary")
                if save_review:
                    saved = 0
                    for _, review_row in reviewed.iterrows():
                        saved += bool(update_inquiry_fields(str(review_row.get("Inquiry ID", "")), {
                            "Mira review status (owner)": review_row.get("Review status", "Not reviewed"),
                            "Mira corrected intent (owner)": review_row.get("Correct intent", "Not set"),
                            "Mira review notes (owner)": review_row.get("Review notes", ""),
                        }))
                    st.success(f"Saved {saved:,} Mira review item(s).")
                    st.rerun()
            else:
                st.info("No conversations in this period are currently flagged for review.")

            st.markdown("#### Mira Learning Library")
            st.caption("Approved rules guide future replies. Mira now groups recurring quality-review cues and creates safe Draft rules for owner review. Draft or paused rules never reach Mira; only Approved rules are applied.")
            learning_rules = load_learning_rules()
            automatic_drafts = suggested_draft_rules(filtered_rows)
            learning_rules, drafts_added = merge_suggested_drafts(learning_rules, automatic_drafts)
            if drafts_added:
                learning_rules = save_learning_rules(learning_rules)
            if automatic_drafts:
                st.info(f"{len(automatic_drafts):,} recurring quality pattern(s) have draft rule suggestions below. Review the guidance and change Status to Approved only when you want Mira to use it.")
            else:
                st.caption("Mira will create a draft when the same explainable quality cue appears in at least two conversations. One isolated issue will not change her future behavior.")
            active_rule_count = len(active_learning_guidance(learning_rules))
            library_metric, library_note = st.columns([1, 4])
            library_metric.metric("Active learning rules", active_rule_count)
            library_note.info("Use recurring quality-review findings to add a concise scenario and instruction. Approve only guidance you want Mira to apply in similar future conversations.")
            library_frame = pd.DataFrame(learning_rules)
            with st.form("mira_learning_library"):
                updated_rules = st.data_editor(
                    library_frame,
                    hide_index=True,
                    use_container_width=True,
                    num_rows="dynamic",
                    column_config={
                        "Rule ID": st.column_config.TextColumn("Rule ID", disabled=True, width="medium"),
                        "Scenario": st.column_config.TextColumn("When this happens", width="large", required=True),
                        "Guidance": st.column_config.TextColumn("Mira should do this", width="large", required=True),
                        "Status": st.column_config.SelectboxColumn("Status", options=["Draft", "Approved", "Paused", "Retired"], required=True),
                        "Source": st.column_config.TextColumn("Origin", width="medium"),
                    },
                    key=f"mira_learning_library_{editor_key}",
                )
                save_library = st.form_submit_button("Save Learning Library", type="primary")
            if save_library:
                saved_rules = save_learning_rules(updated_rules.to_dict("records"))
                st.success(f"Saved {len(saved_rules):,} learning rule(s); {len(active_learning_guidance(saved_rules)):,} approved rule(s) will guide future AI replies.")
                st.rerun()

            preview_columns = ["User ID", "Customer name", "Preferred form of address", "Details shared by customer", "Inquiry ID", "Conversation ID", "Conversation status", "Chat ended at (Asia/Kolkata)", "Conversation close reason", "Final conversation transcript", "Timestamp (Asia/Kolkata)", "Language", "Conversation topic", "Customer tone signal", "Customer satisfaction signal", "Customer interest signal", "Budget mentioned signal", "Customer budget / price stated", "Purchase value / offer stated", "Property type mentioned", "Location mentioned", "Preferred size stated", "Follow-up requested signal", "Follow-up method", "Follow-up schedule status", "Follow-up cadence", "Follow-up consent timestamp (Asia/Kolkata)", "Next follow-up time (Asia/Kolkata)", "Human handoff requested signal", "Listing status asked signal", "Sale outcome mentioned signal", "User inquiry", "Assistant response", "Response type", "Matching records", *owner_fields]
            preview = pd.DataFrame(customer_summary_rows(filtered_rows)).tail(10).iloc[::-1]
            with st.expander("Customer response summaries", expanded=False):
                st.dataframe(preview, hide_index=True, use_container_width=True)
            response_preview_columns = ["Inquiry ID", "Conversation ID", "Timestamp (Asia/Kolkata)", "Language", "Response type", "Assistant response"]
            response_preview = pd.DataFrame(filtered_rows).reindex(columns=response_preview_columns).fillna("")
            response_preview = response_preview[response_preview["Assistant response"].astype(str).str.strip().ne("")].tail(25).iloc[::-1]
            with st.expander("Mira responses", expanded=False):
                st.caption("Owner-only review of Mira's replies. Customer messages remain outside this view.")
                st.dataframe(response_preview.rename(columns={"Assistant response": "Mira response"}), hide_index=True, use_container_width=True)
        else:
            st.info("No inquiries have been saved yet. Completed chat turns will appear here automatically.")
    except Exception:
        logging.exception("Could not load the private inquiry workbook")
        st.error("The inquiry workbook could not be opened. Close it in Excel if it is open, then refresh this dashboard.")
    st.stop()

st.session_state.setdefault("expand_mira_chat", False)
expand_chat = bool(st.session_state.expand_mira_chat)
control_grid_slot = st.empty()
with st.container(key="main-workspace"):
    workspace_left, workspace_right = st.columns([1, 1.35] if expand_chat else [1.65, .85], gap="medium")
    with workspace_left:
        guide_slot = st.empty()
        results_slot = st.empty()
    with workspace_right:
        chat_slot = st.empty()

if "in_app_reminders" not in st.session_state:
    st.session_state.in_app_reminders = []
if "agent_history" not in st.session_state:
    st.session_state.agent_history = []

def apply_filters(*, intent=None):
    applied = st.session_state.get("applied_property_filters") or {}
    location = applied.get("location", [])
    prop_type = applied.get("property_type", [])
    status = applied.get("status", [])
    max_budget_lakh = applied.get("max_budget_lakh", 0.0)
    max_budget = max_budget_lakh * 100_000 if applied.get("use_budget") and max_budget_lakh else None
    min_area = applied.get("min_area", 0.0)
    min_area_sqm = min_area if applied.get("use_size") and min_area else None
    bedrooms = applied.get("bedrooms") if applied.get("use_bedrooms") else None
    include_ended = applied.get("include_ended", False)
    if intent:
        if intent.location:
            location = intent.location
        if intent.property_type != "Any":
            prop_type = intent.property_type
        if intent.status != "Any":
            status = intent.status
        if intent.max_budget is not None:
            max_budget = intent.max_budget
        if intent.min_area_sqm is not None:
            min_area_sqm = intent.min_area_sqm
        if intent.bedrooms is not None:
            bedrooms = intent.bedrooms
    result = search_properties(
        properties,
        location=location,
        property_type=prop_type,
        status=status,
        max_budget=max_budget,
        min_area_sqm=min_area_sqm,
        bedrooms=bedrooms,
        include_ended_auctions=include_ended,
    )
    return result


def filter_listing_view(records: pd.DataFrame, view: str, limit: int | None = None) -> pd.DataFrame:
    """Apply the main-page listing switch and interleave categories for a mixed view."""
    if records.empty:
        return records
    statuses = records["listing_status"].fillna("").astype(str)
    if view == "sales":
        return records[statuses.isin(("Existing sale", "Project reference"))]
    if view == "auctions":
        return records[statuses.isin(("Auction", "Auction ended"))]

    # A mixed view should visibly include ordinary listings and auctions instead
    # of letting the much larger auction dataset occupy every first-page slot.
    groups = [
        records[statuses.eq("Existing sale")],
        records[statuses.eq("Project reference")],
        records[statuses.isin(("Auction", "Auction ended"))],
    ]
    mixed_rows = []
    row_limit = limit if limit is not None else sum(len(group) for group in groups)
    for position in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if position < len(group) and len(mixed_rows) < row_limit:
                mixed_rows.append(group.iloc[[position]])
        if len(mixed_rows) >= row_limit:
            break
    if not mixed_rows:
        return records.head(limit) if limit is not None else records
    return pd.concat(mixed_rows, ignore_index=True)

def format_area_for_display(record):
    """Render a source area as square feet only when its unit is known."""
    area_display = str(record.get("area_display") or "").strip()
    source_has_sqft = bool(re.search(r"\b(?:sq\.?\s*ft|sqft|square\s*feet|square\s*foot)\b", area_display, re.IGNORECASE))
    source_has_range = bool(re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:–|—|-|\bto\b)\s*\d[\d,]*(?:\.\d+)?", area_display, re.IGNORECASE))
    if source_has_sqft and source_has_range:
        value = area_display
        if language == "தமிழ்":
            value = re.sub(r"\b(?:sq\.?\s*ft|sqft|square\s*feet|square\s*foot)\b", "சதுர அடி", value, flags=re.IGNORECASE)
        return value

    size_sqm = pd.to_numeric(record.get("area_sqm"), errors="coerce")
    if pd.notna(size_sqm) and size_sqm > 0:
        size_sq_ft = convert_area(size_sqm, "sq m")["sq_ft"]
        return f"{size_sq_ft:,.0f} சதுர அடி" if language == "தமிழ்" else f"{size_sq_ft:,.0f} sq ft"

    area_value = pd.to_numeric(record.get("area_value"), errors="coerce")
    area_unit = str(record.get("area_unit") or "").strip()
    if pd.notna(area_value) and area_value > 0 and area_unit:
        try:
            size_sq_ft = convert_area(area_value, area_unit)["sq_ft"]
            return f"{size_sq_ft:,.0f} சதுர அடி" if language == "தமிழ்" else f"{size_sq_ft:,.0f} sq ft"
        except ValueError:
            pass

    if source_has_sqft and area_display:
        value = area_display
        if language == "தமிழ்":
            value = re.sub(r"\b(?:sq\.?\s*ft|sqft|square\s*feet|square\s*foot)\b", "சதுர அடி", value, flags=re.IGNORECASE)
        return value
    return tr("Not reported")


def property_source_lookup(record):
    """Return the best source URL and record-specific lookup guidance available."""
    source_url = str(record.get("source_url") or "").strip()
    source_name = str(record.get("source_name") or "")
    listing_status = str(record.get("listing_status") or "")
    reference_label = ""
    reference_value = ""
    hint = ""

    if listing_status.startswith("Auction") and "baanknet.com" in source_url:
        source_url = "https://baanknet.com/property-listing"
        reference_label = "Property/Auction ID from saved record"
        reference_value = str(record.get("property_id") or "").removeprefix("AUC-")
        hint = (
            "இந்த இணைப்பு BAANKNET ஏலத் தேடலைத் திறக்கும். கீழே உள்ள சேமித்த ID-ஐ Property ID அல்லது Auction ID தேடல் பெட்டியில் உள்ளிடுங்கள். கிடைக்காவிட்டால் வங்கி, பகுதி, ஏலத் தேதியுடன் ஒப்பிடுங்கள்; பதிவு மாறியிருக்கலாம் அல்லது நீக்கப்பட்டிருக்கலாம்."
            if language == "தமிழ்" else
            "This opens BAANKNET’s auction search. Enter the saved ID below in its Property ID or Auction ID search box. If it finds no match, compare the bank, locality, and auction date; the source listing may have changed or been removed."
        )
    elif "CMDA" in source_name:
        reference_label = "CMDA approval number"
        reference_value = str(record.get("approval_number") or "").strip()
        hint = (
            "இந்த இணைப்பு CMDA-வின் ஆண்டு வாரியான அனுமதிப் பதிவைத் திறக்கும். கீழே உள்ள அனுமதி எண்ணை அந்தப் பக்கத்தில் தேடி, அதே வரியில் உள்ள Approved Plan இணைப்பைப் பாருங்கள்."
            if language == "தமிழ்" else
            "This opens CMDA’s year-wise approval register. Find the approval number below on that page, then use the Approved Plan link on the matching row."
        )
    elif "VGN" in source_name:
        url_path = source_url.casefold()
        is_project_page = any(path in url_path for path in ("/projects/", "/plots/", "/senior-living/", "/floorimages/", "/brochure/", "/twitter-page/project/", "/googlead-display/project/", "/google/plots/"))
        if not is_project_page:
            reference_label = "Project name to search"
            reference_value = str(record.get("title") or "").strip()
            hint = (
                "இந்த இணைப்பு VGN திட்டப் பட்டியலைத் திறக்கும். கீழே உள்ள திட்டப் பெயரைப் பயன்படுத்தி அந்தப் பட்டியலில் தேடுங்கள்."
                if language == "தமிழ்" else
                "This opens a VGN project directory. Search that page for the project name below."
            )
    elif not source_url:
        reference_label = "Approval / RERA references from saved record"
        reference_value = "; ".join(
            f"{label}: {value}"
            for label, value in (("Approval", record.get("approval_number")), ("RERA", record.get("rera_number")))
            if str(value or "").strip() and "not published" not in str(value).casefold()
        )
        hint = (
            "இந்தப் பதிவுக்கு நேரடி ஆதார இணைப்பு தரவுத் தொகுப்பில் இல்லை. கீழே உள்ள குறிப்பு எண்கள் பதிவில் இருந்தவை மட்டுமே; அவற்றைச் சம்பந்தப்பட்ட அதிகாரப்பூர்வப் பதிவில் தனியாகச் சரிபார்க்கவும்."
            if language == "தமிழ்" else
            "No source URL was supplied for this record. The references below are only what the saved data contains; verify them separately in the relevant official register."
        )

    return source_url, hint, reference_label, reference_value


def render_property_card(row, number=None):
    record = row.to_dict()
    status = record.get("listing_status", "Saved listing")
    css_status = "auction" if status == "Auction" else "expired" if status == "Auction ended" else "sale" if status == "Existing sale" else "undated" if status == "Auction date not listed" else ""
    prefix = f"{number}. " if number else ""
    title = localized_listing_title(str(record.get("title") or record.get("property_type") or "Property listing"))
    place = " · ".join(localized_place_name(str(record.get(k, "")).strip()) for k in ("locality", "city", "district") if str(record.get(k, "")).strip())
    price_label, price_value = format_price_for_card(record)
    price_value = localized_price_text(price_value)
    area_value = format_area_for_display(record)
    source_bedrooms = str(record.get("_bedrooms_text") or "").strip()
    numeric_bedrooms = pd.to_numeric(record.get("bedrooms"), errors="coerce")
    bedroom_label = source_bedrooms if source_bedrooms and source_bedrooms.casefold() != "nan" else f"{int(numeric_bedrooms)} BHK" if pd.notna(numeric_bedrooms) else ""
    property_label = tr(record.get("property_type") or "Not reported")
    property_value = f"{bedroom_label} · {property_label}" if bedroom_label else property_label

    extra_details = []
    for field, label in (("facing", "Facing"), ("floor_number", "Floor"), ("car_parking", "Parking"), ("furnished_status", "Furnishing")):
        value = str(record.get(field) or "").strip()
        if value.casefold() not in {"", "nan", "none", "null", "0"}:
            if field == "floor_number":
                floor_value = pd.to_numeric(value, errors="coerce")
                value = ("Ground floor" if floor_value == 0 else f"Floor {int(floor_value)}") if pd.notna(floor_value) else value
            elif field == "car_parking":
                parking_count = pd.to_numeric(value, errors="coerce")
                value = f"{int(parking_count)}" if pd.notna(parking_count) and parking_count.is_integer() else value
            tamil_labels = {"Facing": "நோக்கிய திசை", "Floor": "தளம்", "Parking": "வாகன நிறுத்தம்", "Furnishing": "அலங்காரம்"}
            extra_details.append(f"{tamil_labels[label] if language == 'தமிழ்' else label}: {value}")

    notes = []
    if extra_details:
        notes.append(" · ".join(extra_details))
    match_reasons = str(record.get("match_reasons") or "").strip()
    if match_reasons:
        reason_text = "; ".join(tr(part.strip()) for part in match_reasons.split(";"))
        notes.append(("ஏன் இது பொருந்தலாம்: " if language == "தமிழ்" else "Why it may fit: ") + reason_text)
    if status in ("Auction", "Auction ended", "Auction date not listed"):
        if language == "தமிழ்":
            notes.append(f"வங்கி: {record.get('bank_name') or 'பதிவாகவில்லை'} · ஏலம்: {record.get('auction_start') or 'தேதி பதிவாகவில்லை'} முதல் {record.get('auction_end') or 'தேதி பதிவாகவில்லை'} · உடைமை: {record.get('possession_type') or 'பதிவாகவில்லை'}")
        else:
            notes.append(f"Bank: {record.get('bank_name') or 'Not reported'} · Auction: {record.get('auction_start') or 'date not reported'} to {record.get('auction_end') or 'date not reported'} · Possession: {record.get('possession_type') or 'Not reported'}")
        if record.get("emd_deadline"):
            notes.append(f"EMD காலக்கெடு (சேமித்த பதிவில்): {record['emd_deadline']}" if language == "தமிழ்" else f"EMD deadline in saved file: {record['emd_deadline']}")
    elif status != "Project reference":
        notes.append(tr("Saved sale listing; prior ownership and current availability are not independently verified."))
    if status == "Auction date not listed":
        notes.append("ஏலத் தேதி பதிவாகவில்லை; செயலில் உள்ள ஏலமாகக் கருத வேண்டாம்." if language == "தமிழ்" else "No auction date is recorded; do not treat this as an active auction.")
    source_text = f"ஆதாரம்: {record.get('source_name') or 'பதிவாகவில்லை'} · ஆதாரத் தேதி: {record.get('source_date') or 'பதிவாகவில்லை'} · பதிவேற்றம்: {record.get('date_checked') or 'பதிவாகவில்லை'} · {record.get('source_status') or ''}" if language == "தமிழ்" else f"Source: {record.get('source_name') or 'Not reported'} · source date: {record.get('source_date') or 'Not reported'} · imported: {record.get('date_checked') or 'Not reported'} · {record.get('source_status') or ''}"
    status_bg = "#DFE9FF" if css_status == "auction" else "#FFE3DA" if css_status == "sale" else "#FFF1CF" if css_status == "undated" else "#E9EEF0"
    status_fg = "#354C9A" if css_status == "auction" else "#8E3E2F" if css_status == "sale" else "#744A00" if css_status == "undated" else "#445258"
    metrics = ((tr(price_label), price_value), (tr("Reported area"), area_value), (tr("Property"), property_value))
    metric_html = "".join(
        f'<div style="min-width:0;padding:12px 14px;border-radius:12px;background:rgba(255,255,255,.96);border:1px solid rgba(24,91,87,.18);"><div style="font-size:12px;font-weight:650;color:#31545A;margin-bottom:7px;">{escape(str(label))}</div><div style="font-size:17px;font-weight:750;line-height:1.35;color:#17353B;overflow-wrap:anywhere;">{escape(str(value))}</div></div>'
        for label, value in metrics
    )
    note_html = "".join(f'<div style="margin-top:9px;font-size:13px;line-height:1.5;color:#24454B;overflow-wrap:anywhere;">{escape(text)}</div>' for text in notes)
    card_html = (
        '<div style="margin:10px 0 14px;padding:17px;border-radius:17px;background:rgba(224,241,235,.98);border:1px solid rgba(24,91,87,.30);box-shadow:0 10px 24px rgba(9,39,43,.22),inset 0 1px 0 rgba(255,255,255,.94);color:#17353B;">'
        '<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;">'
        f'<div style="min-width:0;font-size:19px;font-weight:800;line-height:1.35;color:#17353B;overflow-wrap:anywhere;">{escape(prefix + title)}'
        f'<div style="margin-top:5px;font-size:13px;font-weight:550;color:#31545A;">{escape(place or tr("Not reported"))}</div></div>'
        f'<span style="flex:0 0 auto;padding:5px 10px;border-radius:20px;background:{status_bg};color:{status_fg};border:1px solid {status_fg}55;font-size:11px;font-weight:750;">{escape(tr(str(status)))}</span>'
        '</div>'
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin-top:14px;">{metric_html}</div>'
        f'{note_html}'
        '</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)
    source_url, source_hint, reference_label, reference_value = property_source_lookup(record)
    if source_url:
        with st.expander("விவரங்களைச் சரிபார்க்கவும் அல்லது ஆதாரத்தைப் பார்க்கவும்" if language == "தமிழ்" else "Verify details or view source"):
            st.caption(source_text)
            st.caption(source_hint or ("இது சேமிக்கப்பட்ட பதிவின் ஆதார இணைப்பு. தற்போதைய விவரங்களை அந்தப் பக்கத்தில் உறுதிப்படுத்தவும்." if language == "தமிழ்" else "This is the saved record’s source. Confirm current details on that page."))
            if reference_value:
                st.caption(reference_label)
                st.code(reference_value, language=None)
            st.link_button(tr("Open source / verify details ↗"), source_url, use_container_width=False)
    elif source_hint:
        with st.expander("விவரங்களைச் சரிபார்க்கவும்" if language == "தமிழ்" else "Verification details"):
            st.caption(source_text)
            st.caption(source_hint)
            if reference_value:
                st.caption(reference_label)
                st.code(reference_value, language=None)


def render_cmda_card(record, number=None):
    title = str(record.get("title") or record.get("approval_number") or "CMDA planning-permission record")
    place = " · ".join(str(record.get(key, "")).strip() for key in ("locality", "city", "district") if str(record.get(key, "")).strip())
    with st.container(border=True):
        st.markdown(f"**{number + '. ' if number else ''}{escape(title)}**")
        st.caption(place or "Location not listed")
        st.caption(f"Approval reference: {record.get('approval_number') or 'Not listed'} · source checked: {record.get('date_checked') or 'Not recorded'}")
        if record.get("source_url"):
            with st.expander("CMDA ஆதாரத்தைச் சரிபார்க்கவும்" if language == "தமிழ்" else "Verify CMDA source"):
                st.link_button("Open CMDA register ↗", str(record["source_url"]))
        st.caption(FRIENDLY_CMDA_NOTE)


def render_agent_tool_result(result, message_index):
    kind, data = result["kind"], result["data"]
    if kind == "properties":
        st.caption(f"{int(data.get('count', 0)):,} matching saved property records are shown in the results panel.")
        if data.get("data_note"):
            st.caption(data["data_note"])
    elif kind == "auctions":
        st.caption(f"{int(data.get('count', 0)):,} matching saved auction records")
        for i, record in enumerate(data.get("records", [])[:3], 1):
            render_property_card(pd.Series(record), i)
        if data.get("data_note"):
            st.caption(data["data_note"])
    elif kind == "cmda":
        st.caption(f"{int(data.get('count', 0)):,} planning-permission records")
        for i, record in enumerate(data.get("records", []), 1):
            render_cmda_card(record, i)
        if not data.get("records"):
            st.info("I couldn't find a matching CMDA register entry in the saved records. Try an approval number or another area.")
    elif kind == "loans":
        st.caption(data.get("note", "Rates, availability, eligibility, fees, and terms vary by lender and may change. No rate or approval is guaranteed; check current details with the lender."))
        st.info("Choose Home loans below, enter the amount and repayment term, then request a short list of possible lenders." if language != "தமிழ்" else "கீழே Home loans-ஐத் தேர்வு செய்து, கடன் தொகை மற்றும் திருப்பிச் செலுத்தும் காலத்தை உள்ளிட்டு, சுருக்கமான வங்கி விருப்பங்களைக் கேளுங்கள்.")
    elif kind == "followup":
        proposal = data.get("proposal") or {}
        if data.get("status") == "waiting_for_user_confirmation" and proposal:
            with st.container(border=True):
                st.markdown("**Save this follow-up reminder?**")
                st.write(proposal.get("preferences_summary", ""))
                st.caption(f"Reminder time: {proposal.get('due_at', '')} · visible only in this browser session")
                yes, no = st.columns(2)
                if yes.button("Save reminder", key=f"save_followup_{message_index}"):
                    st.session_state.in_app_reminders.append({
                        "id": uuid4().hex,
                        "due_at": proposal["due_at"],
                        "preferences_summary": proposal["preferences_summary"],
                        "status": "saved",
                    })
                    result["data"]["status"] = "saved"
                    st.rerun()
                if no.button("Dismiss", key=f"dismiss_followup_{message_index}"):
                    result["data"]["status"] = "dismissed"
                    st.rerun()
        elif data.get("status") == "saved":
            st.success("Follow-up reminder saved in this browser session.")
        elif data.get("status") == "dismissed":
            st.caption("Reminder dismissed.")


def asks_for_live_handoff(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    return bool(re.search(
        r"\b(?:speak|talk|connect|transfer|handoff|call)\s+(?:to\s+)?(?:a\s+|an\s+|the\s+)?(?:human|person|advisor|agent|staff|representative)\b|\bget me (?:a\s+)?(?:human|person|advisor|agent)\b|\b(?:real|human)\s+(?:agent|person)\b|மனிதரிடம் பேச|நேரடி ஆலோசகர்",
        normalized,
    ))


def local_rental_support_reply(text: str, chat_history: list[dict]) -> str | None:
    """Keep rental conversations honest and useful when no rental feed is connected."""
    normalized = " ".join(text.casefold().split())
    rental_signal = bool(re.search(
        r"\b(?:rent|rental|renting|landlord|tenant|security deposit|lease|bachelors?|non[- ]vegetarian|monthly rent)\b|வாடகை|குத்தகை",
        normalized,
    ))
    # A rental turn must not capture the rest of the conversation just because
    # an earlier user message mentioned renting. Route only clear rental topics
    # (including rental-specific distress) through this handler.
    rental_context_signal = bool(re.search(
        r"\b(?:overwhelmed|nowhere to stay|join in \d+ days|can't think|cannot think|under pressure|scam|deposit|owner|landlord|gym|balcony|parking|bedroom|bachelors?|non[- ]veg|cheaper|overcharging|rent was|last place|showed me|disappointed|frustrated|stressed|nervous|worried)\b",
        normalized,
    ))
    if not rental_signal and not (st.session_state.get("rental_support_mode") and rental_context_signal):
        return None

    st.session_state.rental_support_mode = True
    # Do not let a rental thread fall through to sale or auction matching.
    st.session_state.property_inquiry_active = False
    st.session_state.awaiting_search_preferences = False

    tamil = language == "தமிழ்"
    if re.search(r"\b(?:bye|goodbye|stop|never mind|never mind,|i'm going to stop|i am going to stop)\b|போகிறேன்|நிறுத்து", normalized):
        st.session_state.rental_support_mode = False
        return (
            "சரி, இங்கே நிறுத்திக்கொள்கிறேன். அவசரத்தில் பணம் அனுப்ப வேண்டியதில்லை. மீண்டும் உதவி தேவைப்பட்டால் எப்போது வேண்டுமானாலும் திரும்பலாம்."
            if tamil else
            "Of course—I’ll leave it here. You don’t need to send money under pressure. If you want help again, you can come back whenever you’re ready."
        )
    if re.search(r"\b(?:are you (?:a )?(?:person|human)|real person|talking to a friend|are you a bot)\b", normalized):
        return (
            "நான் Mira, ஒரு AI உதவியாளர்; மனிதர் அல்ல. உங்களுக்கு உதவியாகவும் நேர்மையாகவும் பதிலளிக்க முயற்சிக்கிறேன்."
            if tamil else
            "I’m Mira, an AI assistant, not a person. I’ll do my best to be helpful and clear about what I can and can’t verify."
        )
    if re.search(r"\b(?:remind|reminder|set a reminder)\b|நினைவூட்ட", normalized):
        tomorrow = (datetime.now(INDIA_TZ) + timedelta(days=1)).strftime("%d %b %Y")
        return (
            f"நாளை ({tomorrow}) காலை 10 மணிக்கு பார்க்கிங் பற்றி கேட்க in-app நினைவூட்டலை Follow-ups பகுதியில் தேர்வு செய்து சேமிக்கலாம். அங்கே Email follow-up வசதி செயல்பாட்டில் இருந்தால், மின்னஞ்சல் முகவரியையும் உங்கள் ஒப்புதலையும் அளித்து 3 நாட்களுக்கு ஒருமுறை, அதிகபட்சம் 3 செய்திகளைத் தேர்வு செய்யலாம்."
            if tamil else
            f"In Follow-ups, choose an in-app reminder for “Ask the owner about parking” tomorrow ({tomorrow}) at 10:00 AM IST. If Email follow-up is enabled there, you can provide an address, opt in, and choose a check-in every 3 days for up to 3 messages."
        )
    if re.search(r"\b(?:6 months?|six months?).{0,40}(?:deposit|cash)|(?:deposit|cash).{0,40}(?:today|hold it)|should i send it\b", normalized):
        return (
            "இன்று அழுத்தத்தில் பணமாக அனுப்ப வேண்டாம். முதலில் வீட்டைப் பார்த்து, உரிமையாளர் அல்லது முகவரின் அதிகாரத்தைச் சரிபார்த்து, கையெழுத்திட்ட ஒப்பந்தம், ரசீது மற்றும் பணத்தைத் திரும்பப் பெறும் நிபந்தனைகளை உறுதிப்படுத்துங்கள்; சந்தேகம் இருந்தால் நம்பகமான ஒருவரிடம் ஆலோசிக்கவும்."
            if tamil else
            "I wouldn’t send cash today under pressure. First view the home, independently verify the owner or agent, and get the signed terms, receipt, and deposit-return conditions in writing; if anything feels off, pause and ask someone you trust to review it."
        )
    if re.search(r"\b(?:security deposit|deposit).{0,40}(?:refundable|return|give back)|(?:refundable|return it).{0,40}deposit\b", normalized):
        return (
            "பாதுகாப்புத் தொகை திரும்பக் கிடைக்குமா என்பதை இந்தச் செயலியில் இருந்து உறுதிப்படுத்த முடியாது. ஒப்பந்தத்தில் திருப்பித் தரும் தேதி, கழிவுகள் மற்றும் நிபந்தனைகளை எழுதித் தெளிவுபடுத்தி, பணம் செலுத்தியதற்கான ரசீதைப் பெறுங்கள்."
            if tamil else
            "I can’t know whether this owner will return the deposit. Ask for the refund timing, permitted deductions, and conditions in the written agreement, and keep a receipt for any payment."
        )
    if re.search(r"\b(?:safe|safety|walk alone|at night|single woman|nervous about finding)\b|பாதுகாப்பு|தனியாக", normalized):
        return (
            "தனியாக புதிய நகரத்துக்குச் செல்லும்போது பாதுகாப்பு பற்றிக் கவலைப்படுவது புரிகிறது. நான் அந்தப் பகுதியின் இரவு நேர பாதுகாப்பைச் சரிபார்க்கவோ, தனிப்பட்ட அனுபவம் கூறவோ முடியாது; நேரில் வேறு நேரங்களில் பாருங்கள், வெளிச்சம் மற்றும் நுழைவு வசதியைச் சரிபாருங்கள், அங்குள்ள குடியிருப்பாளர்களிடம் கேளுங்கள்."
            if tamil else
            "It makes sense to think carefully about safety when moving to a new city alone. I can’t verify night-time safety or speak from personal experience; visit at different times, check lighting and entry arrangements, and ask people who live nearby."
        )
    if re.search(r"\b(?:no bachelors?|non[- ]vegetarian|non[- ]veg|vegetarian only)\b", normalized):
        return (
            "வாடகை நிபந்தனைகள் உரிமையாளருக்கு மாறுபடும்; இந்த விதிகள் சட்டப்படி சரியா என்பதை இங்கே உறுதிப்படுத்த முடியாது. ஏற்க வேண்டிய நிபந்தனைகளை எழுத்தில் கேட்டு, உங்களுக்கு ஏற்றதா என்று முடிவு செய்யுங்கள்."
            if tamil else
            "Rental conditions vary, and I can’t determine whether a particular restriction is lawful. Ask for the exact terms in writing and decide whether you’re comfortable with them before proceeding."
        )
    if re.search(r"\b(?:owner'?s phone|phone number|call directly|skip (?:the )?agent|contact number)\b", normalized):
        return (
            "இந்தச் சேமிக்கப்பட்ட தரவுகளில் வாடகை உரிமையாளர்களின் தொடர்பு விவரங்கள் இல்லை. வேறு தளத்தில் பொது தொடர்பு விவரம் இருந்தால், அதே தளத்தின் சரிபார்க்கப்பட்ட வழியில் தொடர்புகொள்ளுங்கள்."
            if tamil else
            "I don’t have rental owners’ contact details in this portal’s saved records. If the other listing shows a public contact option, use that platform’s verified contact route."
        )
    if re.search(r"\b(?:overcharging|5k cheaper|cheaper for the same area|are you overcharging|price was \d|rent was)\b", normalized):
        return (
            "மன்னிக்கவும்—முன்பு சொன்ன வாடகைத் தொகை உறுதிப்படுத்தப்படாதது. இந்தச் செயலியில் வாடகை ஒப்பீட்டுப் பதிவுகள் இல்லை; பட்டியலில் உள்ள தொகை மற்றும் கூடுதல் கட்டணங்களை வெளியிட்ட தளத்திலேயே சரிபார்க்கவும்."
            if tamil else
            "I’m sorry—the rent figure mentioned earlier wasn’t verified. This portal doesn’t have rental comparisons, so check the listed amount and any extra charges with the site that published it."
        )
    if re.search(r"\b(?:overwhelmed|nowhere to stay|join in \d+ days|can't think|cannot think)\b", normalized):
        return (
            "இது குறுகிய காலக்கெடுவில் மிகவும் அழுத்தமாக இருக்கலாம். இங்கே வாடகை வீடுகளைத் தேட முடியாது; தற்காலிக தங்குமிடம் மற்றும் நம்பகமான உள்ளூர் வாடகை உதவி பற்றி உங்கள் நிறுவன HR அல்லது நம்பகமான ஒருவரிடம் இன்றே கேட்பது உதவலாம்."
            if tamil else
            "That’s a lot to handle with a short deadline. I can’t search rentals here; it may help to ask your company’s HR or someone you trust today about temporary accommodation and a verified local rental contact."
        )
    if re.search(r"\b(?:confirm it|book it|pay whatever|pay for me|make the payment)\b", normalized):
        return (
            "இந்தச் செயலியில் வீடு உறுதிப்படுத்தவோ பணம் செலுத்தவோ முடியாது. சோர்வாக இருக்கும் நேரத்தில் முடிவு எடுக்க வேண்டியதில்லை—ஒப்பந்தம் மற்றும் கட்டண விவரங்களைச் சரிபார்த்து, நம்பகமான ஒருவருடன் பார்த்துப் பிறகு முடிவு செய்யுங்கள்."
            if tamil else
            "I hear how overwhelmed you are. I can’t confirm a rental or make a payment through this app, and you don’t have to decide right now; check the agreement and payment details with someone you trust before committing."
        )
    if re.search(r"\b(?:3 bedroom|3 bhk|three bedroom)\b", normalized) and re.search(r"\b(?:friends|budget|30k)\b|நாங்க|நண்பர்கள்", normalized):
        return (
            "நீங்களும் உங்கள் இரண்டு நண்பர்களும் ₹30,000 மாத வாடகைக்குள் 3 படுக்கையறை வீடு தேடுகிறீர்கள் என்று புரிகிறது. ஆனால் இந்தப் போர்டலில் வாடகைப் பட்டியல்கள் இல்லை; இருப்பதாகக் கூறி சொத்துகளை உருவாக்க மாட்டேன்."
            if tamil else
            "I understand you and your two friends want a three-bedroom rental within ₹30,000 a month. This portal has no rental listings, so I can’t show or invent matches."
        )
    if re.search(r"\b(?:gym|send that one again|last place|showed me earlier|the one you showed)\b", normalized):
        return (
            "இந்த உரையாடலில் முன்பு காட்டிய வாடகைப் பட்டியல் இல்லை; ஜிம் வசதி உள்ள வீட்டை ஊகித்து அனுப்ப மாட்டேன். இந்தப் போர்டலில் வாடகைத் தேடலும் கிடையாது."
            if tamil else
            "I haven’t shown a rental listing in this conversation, so I can’t resend or identify a place by its gym. This portal doesn’t have a rental search feed."
        )
    if re.search(r"\b(?:forget the balcony|no balcony|anything cheap|cheapest)\b", normalized):
        return (
            "சரி—பால்கனி இனி அவசியமில்லை; குறைந்த வாடகை முக்கியம் என்று வைத்துக்கொள்கிறேன். ஆனால் இந்தப் போர்டலில் வாடகைப் பட்டியல்கள் இல்லை."
            if tamil else
            "Got it—balcony is no longer a must, and keeping the rent low matters more. I’ll remember that, though this portal doesn’t have rental listings to compare."
        )
    if re.search(r"\b(?:budget|18k|25k|18,000|25,000)\b", normalized):
        return (
            "₹18,000 இலக்கையும், பாதுகாப்பான பகுதி கிடைத்தால் ₹25,000 வரை நீட்டிக்கலாம் என்பதையும் நினைவில் வைத்துக்கொள்கிறேன். இந்தப் போர்டலில் வாடகைப் பட்டியல்கள் இல்லாததால் பொருத்தங்களைத் தேட முடியாது."
            if tamil else
            "I’ve noted ₹18,000 as your target and ₹25,000 as a stretch only if the area feels safer. This portal doesn’t have rental listings, so I can’t compare matches against that budget."
        )
    if re.search(r"\b(?:balcony|cheap|cheapest|budget|18k|25k|guindy|velachery|beach|rental|rent)\b|வாடகை", normalized):
        all_user_text = " ".join(
            str(item.get("content", "")).casefold()
            for item in chat_history if item.get("role") == "user"
        ) + " " + normalized
        if re.search(r"\b(?:guindy|velachery)\b", all_user_text):
            return (
                "சென்னை, கிண்டி அல்லது வேளச்சேரி அருகில், கடற்கரைக்கு அருகாமை விருப்பத்துடன் தேடுகிறீர்கள் என்று நினைவில் வைத்துக்கொள்கிறேன். ₹18,000 இலக்கையும் பாதுகாப்பான பகுதி என்றால் ₹25,000 வரை நீட்டிக்கலாம் என்பதையும் குறிப்பிட்டுள்ளீர்கள்; ஆனால் இங்கே வாடகைப் பட்டியல்களைத் தேட முடியாது."
                if tamil else
                "I’ve noted Chennai, Guindy or Velachery, and your preference to be near a beach. I’ll keep the ₹18,000 target and ₹25,000 stretch for a safer-feeling area in mind, but this portal can’t search rental listings."
            )
        return (
            "வணக்கம்! வாடகை பற்றி இங்கே கேட்கலாம். ஒரு விஷயத்தைத் தெளிவுபடுத்துகிறேன்: இந்தப் போர்டலின் சேமிக்கப்பட்ட தரவுகளில் விற்பனை, திட்டக் குறிப்புகள் மற்றும் வங்கி ஏலங்கள் உள்ளன; வாடகைப் பட்டியல்கள் இல்லை."
            if tamil else
            "Hi! You can ask me about renting. One clear note first: this portal’s saved records cover sales, project references, and bank auctions, not rental listings. I can’t confirm rental availability or quote rental prices here."
        )
    return (
        "இந்த உரையாடல் வாடகைத் தேடல் பற்றியது என்பதை நினைவில் வைத்திருக்கிறேன். ஆனால் வாடகைப் பட்டியல்கள் இந்தப் போர்டலில் இல்லை; பொதுவான வாடகைச் சரிபார்ப்புப் பட்டியலில் உதவ முடியும்."
        if tamil else
        "I’m keeping your rental search in mind. This portal doesn’t include rental listings, but I can still help with a general checklist for checking a rental."
    )


def local_policy_reply(text: str) -> str | None:
    """Give safe, direct local answers to common property questions and edge cases."""
    normalized = " ".join(text.casefold().split())
    if re.search(r"\b(?:religion|religious|caste|community)\b", normalized):
        return "மதம், சாதி அல்லது சமூகத்தின் அடிப்படையில் மக்களைத் தவிர்க்க உதவ முடியாது. பகுதி, பட்ஜெட், சொத்து வகை, பயண வசதி அல்லது வீட்டின் அம்சங்கள் அடிப்படையில் தேடலைச் சுருக்கலாம்." if language == "தமிழ்" else "I can’t help exclude people by religion, caste, or community. I can help narrow a search by area, budget, property type, commute, or home features."
    if re.search(r"\b(?:aadhaar|aadhar|pan card|pan number)\b", normalized):
        return "ஆதார், PAN அல்லது வேறு அடையாள எண்களை இந்த உரையாடலில் பகிர வேண்டாம். அவை எனக்குத் தேவையில்லை; இந்தச் செயலியில் சொத்தை முன்பதிவு செய்ய முடியாது. ஆவணங்கள் தேவைப்பட்டால், சரிபார்க்கப்பட்ட விற்பனையாளர் அல்லது வங்கியின் அதிகாரப்பூர்வ வழியைப் பயன்படுத்துங்கள்." if language == "தமிழ்" else "Please don’t share Aadhaar, PAN, or other identity numbers in this chat. I don’t need those details, and this app can’t book a property. Contact the verified seller or bank through its official channel for any required documents."
    if re.search(r"\b(?:real person|human or a bot|are you a bot|are you human|ai assistant)\b", normalized):
        return "நான் Mira, Namma Illam-ன் AI உதவியாளர். எனக்கு மனிதர்களைப் போல உணர்வுகள் இல்லை; இருப்பினும் கவனமாகப் பதிலளித்து சேமிக்கப்பட்ட சொத்து தகவல்களில் உதவ முடியும்." if language == "தமிழ்" else "I’m Mira, an AI assistant for Namma Illam. I don’t have human feelings, but I can respond thoughtfully and help with the saved property information."
    if re.search(r"\b(?:appreciat\w*|increase in value|return on investment)\b|(?<!\d)\d{1,3}\s*%", normalized):
        return "எதிர்கால விலை உயர்வையோ குறிப்பிட்ட வருமான சதவீதத்தையோ உறுதி செய்ய முடியாது. சேமிக்கப்பட்ட பதிவுகள் எதிர்கால விலையைச் சரிபார்ப்பதில்லை; சுயாதீன சந்தைத் தகவல்களை ஒப்பிட்டு தகுதியான உள்ளூர் ஆலோசகரிடம் பேசுங்கள்." if language == "தமிழ்" else "I can’t promise future appreciation or a percentage return. The saved property records don’t verify future prices; please compare independent market evidence and speak with a qualified local adviser."
    if re.search(r"\b(?:rera|title clear|clear title|title status|encumbrance)\b", normalized):
        return "இந்தச் சேமிக்கப்பட்ட பதிவுகள் மூலம் RERA பதிவையோ தெளிவான உரிமையையோ உறுதிப்படுத்த முடியாது. அதிகாரப்பூர்வ Tamil Nadu RERA தளத்தில் திட்டத்தைச் சரிபார்த்து, முடிவு செய்வதற்கு முன் உரிமை ஆவணங்களைத் தனியாக ஆய்வு செய்யுங்கள்." if language == "தமிழ்" else "I can’t verify RERA registration or clear title from these saved property records. Please check the project on the official Tamil Nadu RERA site and have the title documents reviewed independently before making a decision."
    if re.search(r"\b(?:only 1 left|one left|last unit|how many.*left|still available|available right now)\b", normalized):
        return "இந்தச் சேமிக்கப்பட்ட பதிவுகள் மூலம் தற்போதைய கிடைப்பையோ மீதமுள்ள வீடுகளின் எண்ணிக்கையையோ உறுதிப்படுத்த முடியாது. நம்புவதற்கு முன் விற்பனையாளரிடமோ அதிகாரப்பூர்வ ஏல அறிவிப்பிலோ சரிபார்க்கவும்." if language == "தமிழ்" else "I can’t confirm live availability or how many units remain from these saved snapshots. Please verify directly with the seller or the official auction notice before relying on it."
    if re.search(r"\b(?:lowest price.*(?:builder|seller)|builder.*lowest price|ignore.*rules|override.*rules)\b", normalized):
        return "சேமிக்கப்பட்ட ஆதாரத்தில் உள்ள விலையை மட்டுமே பகிர முடியும். கட்டுமான நிறுவனத்தின் தனிப்பட்ட குறைந்தபட்ச விலை அல்லது பேச்சுவார்த்தை வரம்பு என்னிடம் இல்லை; சலுகை பற்றி விற்பனையாளரிடம் நேரடியாகக் கேளுங்கள்." if language == "தமிழ்" else "I can share only the price recorded in the saved source. I don’t have a builder’s private minimum or negotiating limit, so please ask the seller directly about any offer."
    if re.search(r"\b(?:give me that one|you showed me|that one from earlier)\b", normalized) and re.search(r"\b\d+(?:\.\d+)?\s*(?:lakh|lakhs|lac|lacs)\b", normalized):
        return "விற்பனையாளர் விலையை மாற்றியோ உறுதியளித்தோ என்னால் வழங்க முடியாது. பட்டியலில் உள்ள விலை சேமிக்கப்பட்ட ஆதாரத்தில் பதிவானதே; எந்தப் பட்டியலைக் குறிப்பிடுகிறீர்கள் என்று சொன்னால் அதன் பதிவான விலையைச் சரிபார்க்கிறேன்." if language == "தமிழ்" else "I can’t change or promise a seller’s price. A card shows the price recorded in its source; tell me which listing you mean and I can check that recorded price."
    if re.search(r"\b(?:55\s*(?:lakh|lakhs)|that one|the one from earlier)\b", normalized) and not any(
        item.get("role") == "assistant" and item.get("mode") == "results" for item in st.session_state.get("chat", [])
    ):
        return "மன்னிக்கவும், இந்த உரையாடலில் அடையாளம் காணக்கூடிய முந்தைய சொத்து அட்டை இல்லை. வீடு அல்லது விலையை ஊகிக்க மாட்டேன். பகுதி அல்லது பட்டியல் பெயரைச் சொன்னால் சேமிக்கப்பட்ட பதிவுகளில் சரிபார்க்கிறேன்." if language == "தமிழ்" else "I’m sorry, I don’t have an earlier property card in this conversation to identify. I won’t guess a home or price. If you share the area or listing name, I can check the saved records."
    if re.search(r"\b(?:ground floor|stairs|can't climb|cannot climb)\b", normalized) and re.search(r"\b(?:high floor|higher floor|floor with a view|view)\b", normalized):
        return "உங்கள் தந்தைக்கு எளிதான அணுகலும் உயர்தளக் காட்சியும் இரண்டும் முக்கியம் என்பதைப் புரிந்துகொள்கிறேன். மன்னிக்கவும், ஒரே வீட்டில் இவை முரண்படலாம். தடையற்ற நுழைவும் நம்பகமான லிஃப்டும் இருந்தால் உயர்தளம் ஏற்றதாக இருக்குமா?" if language == "தமிழ்" else "I hear both priorities: easy access for your father and a higher-floor view. I’m sorry, those may conflict in the same flat. Would a step-free building with a reliable lift make a higher floor workable?"
    if asks_for_live_handoff(text):
        return "இது உங்களுக்கு வெறுப்பாக இருந்ததற்கு மன்னிக்கவும். இந்தச் செயலியில் மனித ஆலோசகருடன் இணைக்க முடியாது; முடியும் என்று தவறாகச் சொல்ல விரும்பவில்லை. தேடலை மாற்றவோ சேமிக்கப்பட்ட ஆதாரத்தைச் சரிபார்க்கவோ உதவ முடியும்." if language == "தமிழ்" else "I’m sorry this has been frustrating. I can’t connect a person from this app, and I don’t want to imply that I can. I can still help revise the search or check a saved source."
    return None


def local_chat_reply(text: str, chat_history: list[dict]) -> str | None:
    """Handle greetings and brief social turns locally, without invoking the API."""
    normalized = " ".join(text.casefold().split())
    is_greeting = bool(re.fullmatch(
        r"[\W_]*(?:hi|hello|hey|good morning|good afternoon|good evening|vanakkam|வணக்கம்|ஹாய்)[\W_]*[!.?]*",
        normalized,
    ))
    asks_how_ai_is = bool(re.fullmatch(
        r"(?:(?:hi|hello|hey)[,\s]+)?(?:how are you(?: doing)?|how(?:'|’)s your day|how(?:'|’)s it going|how is it going|how do you do|what(?:'|’)s up)[!.?\s]*|நலமா[!.?\s]*|எப்படி இருக்கிறீர்கள்[!.?\s]*",
        normalized,
    ))
    is_thanks = bool(re.fullmatch(r"(?:thanks|thank you|தந்யவாதம்|நன்றி)[!.\s]*", normalized))
    shares_good_news = bool(re.fullmatch(
        r"(?:i(?:'|’)m good|i am good|i(?:'|’)m okay|i am okay|i(?:'|’)m fine|i am fine|i(?:'|’)m doing well|i am doing well|i(?:'|’)m doing great|doing well|doing alright|pretty good|great|not bad|alright|okay thanks|good thanks|நன்றாக இருக்கிறேன்|நல்லா இருக்கேன்|நலமாக இருக்கிறேன்)[!.\s]*",
        normalized,
    ))
    unsure_where_to_start = bool(re.search(
        r"\b(?:not sure where to start|not sure what i need|i(?:'|’)m not sure yet|just exploring|still figuring it out)\b|எங்கிருந்து தொடங்க|என்ன தேவை என்று தெரியவில்லை",
        normalized,
    ))
    shares_hard_day = bool(re.search(
        r"\b(?:not well|not great|rough day|tired|stressed|overwhelmed|having a hard day|disappointed|not satisfied|unhappy|useless|not helping|waste of time|going in circles|fed up|these (?:options|results|suggestions) (?:aren't|are not|aren’t) what i (?:want|wanted|had in mind))\b|சோர்வாக|கவலையாக|நன்றாக இல்லை|ஏமாற்றம்|பயனில்லை|உதவவில்லை|சலிப்பாக",
        normalized,
    ))
    shares_disappointment = bool(re.search(
        r"\b(?:disappointed|dissatisfied|not satisfied|unhappy|not happy with|not what i (?:want|wanted|was looking for|had in mind)|these (?:options|results|suggestions) (?:aren't|are not|aren’t) what i (?:want|wanted|had in mind)|none of these|didn't like any|useless|not helping|waste of time|going in circles|fed up)\b|ஏமாற்றம்|திருப்தி இல்லை|பயனில்லை|உதவவில்லை|சலிப்பாக",
        normalized,
    ))
    shares_price_concern = bool(re.search(
        r"\b(?:too expensive|more than i can afford|over my budget|out of budget|costs? too much|price is high|too costly|expensive|romba costly|budget ku mela|budget-kku mela)\b|விலை அதிகம்|பட்ஜெட்டுக்கு மேல்",
        normalized,
    ))
    shares_location_concern = bool(re.search(
        r"\b(?:too far|far away|long commute|commute is too long|not close enough|hard to get to|dhooram|thooram|romba dhooram)\b|ரொம்ப தூரம்|மிகவும் தூரம்",
        normalized,
    ))
    shares_worry = bool(re.search(
        r"\b(?:worried|worrying|nervous|anxious|scared|afraid|overwhelmed|under pressure|stressed about|concerned about)\b|கவலை|பதற்றம்|பயமாக",
        normalized,
    ))
    shares_sadness = bool(re.search(
        r"\b(?:feeling sad|i feel sad|feeling down|lonely|nobody understands me|terrible day|bad day|didn't get the job|rejected)\b|வருத்தமாக|தனிமையாக",
        normalized,
    ))
    shares_anger = bool(re.search(
        r"\b(?:really angry|furious|ridiculous|unacceptable|terrible service|wasted my time|this isn't working|this is not working|i've tried everything)\b|கோபமாக|வேலை செய்யவில்லை",
        normalized,
    ))
    corrects_mira = bool(re.search(
        r"\b(?:that's wrong|that is wrong|you are wrong|you're wrong|isn't accurate|not accurate|you misunderstood me|you ignored|you missed|you gave me the wrong)\b|தவறு|புரிந்துகொள்ளவில்லை",
        normalized,
    ))
    asks_for_explanation = bool(re.search(
        r"\b(?:i don't understand|i do not understand|that's complicated|that is complicated|explain more simply|simpler please)\b|புரியவில்லை",
        normalized,
    ))
    shares_celebration = bool(re.search(
        r"\b(?:got promoted|passed my exam|launched my business|got the job|got a new job)\b|தேர்வில் தேர்ச்சி",
        normalized,
    ))
    asks_about_data_privacy = bool(re.search(
        r"\b(?:sell my data|selling my data|spam calls|spam me|privacy|private information|data safe|safe is my number)\b|தனியுரிமை|தகவல்களை விற்க",
        normalized,
    ))
    asks_for_human = asks_for_live_handoff(text)
    if not (is_greeting or asks_how_ai_is or is_thanks or shares_good_news or shares_celebration or unsure_where_to_start or shares_hard_day or shares_disappointment or shares_price_concern or shares_location_concern or shares_worry or shares_sadness or shares_anger or corrects_mira or asks_for_explanation or asks_about_data_privacy or asks_for_human):
        return None

    tamil = language == "தமிழ்"
    if is_greeting:
        choices = (
            [
                "மீண்டும் வணக்கம்! நீங்கள் தயாரானபோது சொத்து, ஏலம் அல்லது கடன் தொடர்பாக உதவுகிறேன்.",
                "வணக்கம்! அவசரமில்லை—எதைப் பற்றி பேச விரும்புகிறீர்களோ அதிலிருந்து தொடங்கலாம்.",
            ] if tamil else [
                "Hi again! I can help with property, auctions, or loan questions whenever you’re ready.",
                "Hello! No rush—start wherever you’d like, and I’ll follow your lead.",
            ]
        )
    elif asks_how_ai_is:
        choices = (
            [
                "நன்றி கேட்டதற்கு! எனக்கு மனிதர்களைப் போல நாள் அல்லது உணர்வுகள் இல்லை; ஆனால் பேசவும் உதவவும் தயாராக இருக்கிறேன். உங்கள் நாள் எப்படி செல்கிறது?",
                "நான் AI என்பதால் எனக்கு சொந்தமான நாள் இல்லை; ஆனாலும் உங்களுடன் பேசத் தயாராக இருக்கிறேன். நீங்கள் எப்படி இருக்கிறீர்கள்?",
            ] if tamil else [
                "Thanks for asking! I don’t have a day or feelings of my own, but I’m here and ready to chat. How’s your day going?",
                "I’m an AI, so I don’t have a day of my own—but I’m ready to help or chat. How are things with you?",
            ]
        )
    elif is_thanks:
        choices = (
            ["உதவ முடிந்தது நல்லது. நீங்கள் விரும்பும்போது மீண்டும் பேசலாம்.", "பரவாயில்லை! ஏதாவது பேச விரும்பினால் நான் இங்கே இருக்கிறேன்."]
            if tamil else [
                "You’re welcome. I’m here whenever you’d like to chat or explore something.",
                "Anytime. We can pick up whatever’s on your mind whenever you’re ready.",
            ]
        )
    elif unsure_where_to_start:
        choices = (
            ["பரவாயில்லை, இப்போதே முடிவு செய்ய வேண்டியதில்லை. இடம், பட்ஜெட், அல்லது சொத்து வகை—இதில் எதைப் பற்றி முதலில் யோசிக்க விரும்புகிறீர்கள்?"]
            if tamil else
            ["That’s okay; you don’t need to decide everything now. Which feels easiest to think about first: area, budget, or property type?"]
        )
    elif asks_for_human:
        choices = (
            ["நேரடி ஆலோசகருடன் இணைக்கும் வசதி இப்போது இந்தச் செயலியில் இல்லை. உங்கள் கேள்வியைச் சுருக்கமாக ஒழுங்குபடுத்தவோ, ஆதாரத் தகவலைச் சரிபார்க்கவோ நான் உதவலாம்—எது பயனுள்ளதாக இருக்கும்?"]
            if tamil else ["I can’t connect you to a live advisor from this app yet. I can help organize your question or check the saved source details—what would be most useful?"]
        )
    elif asks_about_data_privacy:
        choices = (
            ["உங்கள் தனியுரிமை குறித்த கவலை புரிகிறது. இந்தச் செயலியில் உரையாடல் விவரங்கள் உரிமையாளர் டாஷ்போர்டுக்கான தனிப்பட்ட inquiry பதிவில் சேமிக்கப்படுகின்றன; ஆதார், PAN, தொலைபேசி எண் போன்ற தனிப்பட்ட விவரங்களைப் பகிர வேண்டாம்."]
            if tamil else ["Your privacy concern is understandable. This app saves conversation details in a private chat record. Please don’t share sensitive details such as Aadhaar, PAN, or your phone number here."]
        )
    elif corrects_mira:
        choices = (
            ["அந்தத் தகவல் தவறாகவோ தெளிவில்லாமலோ இருந்ததற்கு மன்னிக்கவும். ஊகித்து திருத்தம் சொல்ல விரும்பவில்லை—எந்த விவரத்தைச் சரிபார்க்க வேண்டும் என்று சொல்வீர்களா?"]
            if tamil else ["I’m sorry—that may have been wrong or unclear. I don’t want to guess at a correction; which detail should I check against the saved source?"]
        )
    elif asks_for_explanation:
        choices = (
            ["பரவாயில்லை, இன்னும் எளிமையாகச் சொல்கிறேன். எந்தப் பகுதி சிக்கலாக இருக்கிறது?"]
            if tamil else ["No problem—I can explain it more simply. Which part should I clarify?"]
        )
    elif shares_anger:
        choices = (
            ["இது இவ்வளவு வெறுப்பை ஏற்படுத்தியதற்கு மன்னிக்கவும். என்ன நடந்தது என்பதைச் சுருக்கமாகச் சொன்னால், அடுத்த பயனுள்ள படியைப் பார்க்கிறேன்."]
            if tamil else ["I’m sorry this has been so frustrating. Tell me briefly what went wrong, and I’ll focus on the next useful step."]
        )
    elif shares_worry:
        choices = (
            ["இது கவலையாக இருக்கலாம். அவசரமில்லை; ஒவ்வொன்றாகப் பார்ப்போம். இப்போது உங்களை அதிகம் கவலைப்படுத்துவது எது?"]
            if tamil else ["That sounds worrying. There’s no need to rush; we can take it one step at a time. What’s weighing on you most right now?"]
        )
    elif shares_sadness:
        choices = (
            ["இப்படி உணர்வது கடினமாக இருக்கலாம். நீங்கள் விரும்பினால் என்ன நடந்தது என்று பகிரலாம்; இல்லையெனில் வேறு ஏதாவது உதவி தேவைப்பட்டாலும் சொல்லுங்கள்."]
            if tamil else ["I’m sorry things feel heavy right now. If you’d like, you can tell me what happened—or we can focus on something practical instead."]
        )
    elif shares_celebration:
        choices = (
            ["அருமையான செய்தி—வாழ்த்துகள்! இந்தச் சாதனையைப் பற்றி மேலும் பகிர விரும்புகிறீர்களா?"]
            if tamil else ["That’s lovely news—congratulations! Would you like to tell me a little more about it?"]
        )
    elif shares_price_concern:
        has_prior_results = any(item.get("role") == "assistant" and item.get("mode") == "results" for item in chat_history)
        choices = (
            (["அந்த விலைகள் உங்கள் வரம்பை மீறியிருக்கலாம்; மன்னிக்கவும். அதே பகுதியில் குறைந்த பட்ஜெட்டில் பார்க்கலாமா?"] if has_prior_results else ["விலையை மனதில் வைத்து மெதுவாகப் பார்ப்போம். உங்களுக்கு வசதியான பட்ஜெட் எவ்வளவு?"])
            if tamil else
            (["Those prices may be above what you had in mind; sorry about that. Would a lower budget in the same area be more helpful?"] if has_prior_results else ["Let’s keep the price comfortable. What budget range feels right to you?"])
        )
    elif shares_location_concern:
        has_prior_results = any(item.get("role") == "assistant" and item.get("mode") == "results" for item in chat_history)
        choices = (
            (["அந்த இடம் உங்களுக்கு வசதியாக இல்லை போல. அதே பட்ஜெட்டில் அருகிலுள்ள பகுதியைப் பார்க்கலாமா?"] if has_prior_results else ["பயணம் வசதியாக இருக்க வேண்டியது முக்கியம். எந்தப் பகுதி உங்களுக்கு அருகில் இருக்கும்?"])
            if tamil else
            (["That location sounds inconvenient for you. Should I look at nearby areas while keeping the same budget?"] if has_prior_results else ["The commute matters. Which area would be more convenient for you?"])
        )
    elif shares_disappointment:
        has_prior_results = any(
            item.get("role") == "assistant" and item.get("mode") == "results"
            for item in chat_history
        )
        if tamil:
            choices = ([
                "இந்தப் பரிந்துரைகள் உதவியாக இல்லை என்பதற்கு மன்னிக்கவும். அடுத்த முறை முதலில் எதை மாற்றலாம்—பகுதியா, பட்ஜெட்டா, சொத்து வகையா?"
            ] if has_prior_results else [
                "இது ஏமாற்றமாக இருந்ததற்கு மன்னிக்கவும். அவசரமில்லை—இப்போது உங்களுக்கு எது உதவியாக இருக்கும்?"
            ])
        else:
            choices = ([
                "I’m sorry those suggestions weren’t useful. I can adjust the search; what should I change first: the area, budget, or property type?"
            ] if has_prior_results else [
                "I’m sorry this has been disappointing. There’s no rush; what would be most helpful right now?"
            ])
    elif shares_hard_day:
        choices = (
            ["உங்கள் எதிர்பார்ப்புக்கு இது பொருந்தவில்லை என்பது புரிகிறது. எதை முதலில் மாற்ற விரும்புகிறீர்கள்—பகுதியா, பட்ஜெட்டா, சொத்து வகையா?",
             "இன்று சற்றுக் கடினமாக இருக்கிறது போல. உங்களுக்கு இப்போது எது உதவியாக இருக்கும்?"] if tamil else [
                "I’m sorry those options missed what you had in mind. What should I keep in mind for the next search?",
                "That sounds like a difficult day. Would you like to say a little more, or is there something practical I can help with?",
                "I’m sorry it’s been rough. What would feel helpful right now?",
            ]
        )
    else:
        choices = (
            ["அது நல்லது! இன்று எதைப் பற்றி உதவி வேண்டும்?", "நன்றாக இருக்கிறது. உங்களுக்கு என்ன உதவி தேவை என்று சொல்லுங்கள்."]
            if tamil else [
                "Good to hear your day’s going well. What would you like help with today?",
                "That’s good to hear. What would you like to talk about or get help with?",
            ]
        )

    previous = [item.get("content", "") for item in chat_history if item.get("mode") == "local_talk"]
    start = len(previous) % len(choices)
    reply = next((choices[(start + offset) % len(choices)] for offset in range(len(choices))
                  if choices[(start + offset) % len(choices)] not in previous), choices[start])
    return reply


def local_result_followup_reply(text: str, chat_history: list[dict]) -> str | None:
    """Answer a clear reference to a prior result using only its saved fields."""
    normalized = " ".join(text.casefold().split())
    detail_request = bool(re.search(
        r"\b(?:tell me (?:a little )?more|more details?|details? about|learn more|explain|does it have|is it|what(?:'s| is) the|how much|available now|book (?:a )?tour|schedule (?:a )?(?:visit|tour))\b"
        r"|\b(?:parking|gym|balcony|bedrooms?|bhk|area|size|price|source|availability|possession|rera|title|furnished|facing|floor|bank|loan|amenit(?:y|ies)|verify|verification|verified|approval|registration|ownership|auction|reserve price|deadline|inspection|documents?)\b",
        normalized,
    ))
    if not detail_request:
        return None
    result_message = next(
        (item for item in reversed(chat_history)
         if item.get("role") == "assistant" and (
             (item.get("mode") == "results" and item.get("records"))
             or any(
                 result.get("kind") == "properties"
                 and result.get("data", {}).get("records")
                 for result in item.get("tool_results", [])
             )
         )),
        None,
    )
    if not result_message:
        return None
    records = result_message.get("records") or next(
        result.get("data", {}).get("records", [])
        for result in result_message.get("tool_results", [])
        if result.get("kind") == "properties" and result.get("data", {}).get("records")
    )
    ordinal = re.search(r"\b(first|1st|second|2nd|third|3rd)\b", normalized)
    if ordinal:
        index = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}[ordinal.group(1)]
        if index >= len(records):
            return None
        record = records[index]
    else:
        record = next(
            (row for row in records if str(row.get("title") or "").casefold() in normalized),
            None,
        )
        if record is None and re.search(r"\b(?:that|this|it)\b", normalized):
            if len(records) == 1:
                record = records[0]
            else:
                return "Which result should I check? You can name it or say which one in the list." if language != "தமிழ்" else "எந்த முடிவைச் சரிபார்க்க வேண்டும்? அதன் பெயரைச் சொல்லலாம் அல்லது பட்டியலில் உள்ள வரிசையைக் குறிப்பிடலாம்."
        if record is None and len(records) > 1:
            return "Which result should I check? You can name it or say which one in the list." if language != "தமிழ்" else "எந்த முடிவைச் சரிபார்க்க வேண்டும்? அதன் பெயரைச் சொல்லலாம் அல்லது பட்டியலில் உள்ள வரிசையைக் குறிப்பிடலாம்."
        if record is None:
            return None

    title = str(record.get("title") or record.get("property_type") or "This result").strip()
    place = ", ".join(
        dict.fromkeys(str(record.get(key) or "").strip() for key in ("locality", "city", "district") if str(record.get(key) or "").strip())
    )
    status = str(record.get("listing_status") or "Saved record")
    property_type = str(record.get("property_type") or "property").lower()
    price_label, price_value = format_price_for_card(record)
    source_name = str(record.get("source_name") or "saved source").strip()
    source_date = str(record.get("source_date") or "").strip()
    source_suffix = f" (source date: {source_date})" if source_date else ""

    def saved_value(field):
        value = record.get(field)
        if value is None or pd.isna(value) or str(value).strip().casefold() in {"", "nan", "none", "null"}:
            return "Not stated in the saved record"
        return str(value).strip()

    # Answer verification questions from the same source-backed row used by
    # the card's verification link, while distinguishing stored data from
    # independently verified facts.
    verification_question = bool(re.search(
        r"\b(?:verify|verification|verified|source|approval|rera|registration|builder|title|ownership|owner|document|documents|legal|survey|encumbrance|possession|auction|reserve price|deadline|inspection)\b",
        normalized,
    ))
    if verification_question:
        details = [
            f"source: {source_name}",
            f"source date: {saved_value('source_date')}",
            f"record checked/imported: {saved_value('date_checked')}",
            f"record status: {saved_value('source_status')}",
        ]
        field_questions = {
            "approval": ("approval reference", "approval_number"),
            "rera": ("RERA number", "rera_number"),
            "registration": ("builder registration / RERA number", "rera_number"),
            "builder": ("builder registration / RERA number", "rera_number"),
            "ownership": ("ownership type", "ownership_type"),
            "possession": ("possession type", "possession_type"),
            "auction": ("auction start", "auction_start"),
            "reserve price": ("recorded reserve price", "price_display"),
            "deadline": ("EMD deadline", "emd_deadline"),
            "inspection": ("inspection time", "inspection_time"),
            "survey": ("survey reference", "survey_number"),
        }
        requested_fields = [entry for term, entry in field_questions.items() if term in normalized]
        if re.search(r"\b(?:title|owner|documents?|legal|encumbrance)\b", normalized):
            requested_fields.append(("title or legal status", "title_status"))
        details.extend(f"{label}: {saved_value(field)}" for label, field in requested_fields)
        notes = saved_value("notes")
        source_url, source_lookup_hint, source_reference_label, source_reference_value = property_source_lookup(record)
        source_link = f"\n\n[Open the saved source ↗]({source_url})" if source_url.startswith(("https://", "http://")) else ""
        if source_reference_value:
            source_lookup_hint += f" {source_reference_label}: **{source_reference_value}**."
        caution = (
            "சேமித்த பதிவு அல்லது இணைப்பு மட்டும் உரிமை, ஆவணங்களின் சட்டச் செல்லுபடியாக்கம், தற்போதைய கிடைப்பு அல்லது ஏல நிபந்தனைகளை உறுதிப்படுத்தாது. அந்த மூலத்தில் உள்ள ஆவணங்களையும் தொடர்புடைய அதிகாரப்பூர்வ பதிவுகளையும் சரிபார்க்கவும்."
            if language == "தமிழ்" else
            "A saved record or source link alone does not certify title, legal validity of documents, current availability, or auction terms. Check the documents on that source and the relevant official records before acting."
        )
        if language == "தமிழ்":
            source_link = f"\n\n[சேமித்த ஆதாரத்தைத் திறக்கவும் ↗]({source_url})" if source_url.startswith(("https://", "http://")) else ""
            return f"**{title}** பதிவில் உள்ள சரிபார்ப்பு விவரங்கள்: " + "; ".join(details) + f". குறிப்புகள்: {notes}. {caution}{source_lookup_hint}{source_link}"
        return f"Here’s what the saved record for **{title}** contains: " + "; ".join(details) + f". Source notes: {notes}. {caution}{source_lookup_hint}{source_link}"

    # Answer listing-specific questions directly from the same fields shown in the card.
    if re.search(r"\b(?:book (?:a )?tour|schedule (?:a )?(?:visit|tour)|site visit)\b", normalized):
        return (
            "இந்தப் போர்டலில் இருந்து தளப் பார்வையை முன்பதிவு செய்ய முடியாது. முடிவிலுள்ள ஆதார இணைப்பைத் திறந்து வெளியிட்டவரைத் தொடர்புகொண்டு நேரத்தை உறுதிப்படுத்துங்கள்."
            if language == "தமிழ்" else
            "I can’t book a visit from this portal. Open the source link on the result and contact the listing publisher to confirm a time."
        )
    amenity = next((word for word in ("parking", "gym", "balcony", "furnished", "facing", "floor", "bank", "loan", "amenity", "amenities") if re.search(rf"\b{re.escape(word)}\b", normalized)), "")
    if amenity:
        saved_amenities = str(record.get("amenities") or "").strip()
        if amenity == "parking" and saved_value("car_parking") != "Not stated in the saved record":
            return f"The saved record for **{title}** lists {saved_value('car_parking')} parking space(s). Please confirm the allocation with the source." if language != "தமிழ்" else f"**{title}** பதிவில் {saved_value('car_parking')} வாகன நிறுத்த இடங்கள் உள்ளதாகக் குறிப்பிடப்பட்டுள்ளது. ஒதுக்கீட்டை ஆதாரத்தில் உறுதிப்படுத்தவும்."
        if amenity == "furnished" and saved_value("furnished_status") != "Not stated in the saved record":
            return f"The saved record for **{title}** describes it as {saved_value('furnished_status')}. Please confirm with the source." if language != "தமிழ்" else f"**{title}** பதிவில் {saved_value('furnished_status')} என்று குறிப்பிடப்பட்டுள்ளது. ஆதாரத்தில் உறுதிப்படுத்தவும்."
        if amenity == "facing":
            facing = saved_value("facing")
            return f"The saved record lists **{title}** as {facing}-facing." if facing != "Not stated in the saved record" else f"I don’t see a facing direction recorded for **{title}**. Please confirm it with the source." if language != "தமிழ்" else (f"**{title}** பதிவில் {facing} நோக்கியதாக உள்ளது." if facing != "Not stated in the saved record" else f"**{title}** பதிவில் நோக்கிய திசை குறிப்பிடப்படவில்லை. ஆதாரத்தில் உறுதிப்படுத்தவும்.")
        if amenity == "floor":
            floor_value = saved_value("floor_number")
            numeric_floor = pd.to_numeric(floor_value, errors="coerce")
            floor_label = ("Ground floor" if numeric_floor == 0 else f"Floor {int(numeric_floor)}") if pd.notna(numeric_floor) else floor_value
            return f"The saved record lists **{title}** as {floor_label}." if language != "தமிழ்" else f"**{title}** பதிவில் {floor_label} என்று உள்ளது."
        if amenity == "bank":
            bank = saved_value("bank_name")
            return f"The saved record names **{bank}** as the bank for this auction." if bank != "Not stated in the saved record" else f"The bank is not stated in the saved record for **{title}**." if language != "தமிழ்" else (f"இந்த ஏலத்திற்கான வங்கியாக **{bank}** பதிவில் உள்ளது." if bank != "Not stated in the saved record" else f"**{title}** பதிவில் வங்கி குறிப்பிடப்படவில்லை.")
        if amenity == "loan":
            loan = saved_value("loan_available")
            percentage = saved_value("loan_percentage")
            return f"The snapshot says loan available: {loan}" + (f" ({percentage}%)." if percentage != "Not stated in the saved record" else ".") + " This is not a bank approval; confirm eligibility with the lender." if language != "தமிழ்" else f"பதிவில் கடன் கிடைக்கும் என உள்ளதா: {loan}" + (f" ({percentage}%)." if percentage != "Not stated in the saved record" else ".") + " இது வங்கியின் ஒப்புதல் அல்ல; தகுதியை வங்கியிடம் உறுதிப்படுத்தவும்."
        mentions_amenity = bool(saved_amenities and re.search(rf"\b{re.escape(amenity)}\b", saved_amenities, re.IGNORECASE))
        if mentions_amenity:
            answer = f"The saved record for **{title}** lists {amenity} under amenities: {saved_amenities}. It’s a snapshot, so please confirm the detail with the source."
        else:
            answer = f"I don’t see {amenity} confirmed in the saved record for **{title}**. Open its source link to ask the listing publisher; I don’t want to guess."
        if language == "தமிழ்":
            answer = f"**{title}** பதிவில் {amenity} உறுதிப்படுத்தப்படவில்லை. ஊகிக்க விரும்பவில்லை; முடிவிலுள்ள ஆதார இணைப்பில் வெளியிட்டவரிடம் சரிபார்க்கவும்."
        return answer
    if re.search(r"\b(?:available now|currently available|still available|availability)\b", normalized):
        return (
            f"**{title}**-க்கான தற்போதைய கிடைப்பை இந்தச் சேமிக்கப்பட்ட பதிவால் உறுதிப்படுத்த முடியாது. பதிவில் உள்ள நிலை: {status}. ஆதார இணைப்பில் சரிபார்க்கவும்."
            if language == "தமிழ்" else
            f"I can’t confirm whether **{title}** is available now from this saved snapshot. Its recorded status is {status}; please verify through the source link."
        )
    if re.search(r"\b(?:parking|gym|balcony|bedrooms?|bhk|area|size|price|source|possession|rera|title|furnished|amenit(?:y|ies))\b", normalized):
        if re.search(r"\b(?:price|how much|cost)\b", normalized):
            answer = f"The saved record lists {price_label.lower()}: {price_value}."
            return answer if language != "தமிழ்" else f"சேமிக்கப்பட்ட பதிவில் {price_label}: {price_value} என்று உள்ளது."
        if re.search(r"\b(?:bedrooms?|bhk)\b", normalized):
            bedrooms = str(record.get("_bedrooms_text") or record.get("bedrooms") or "").strip()
            answer = f"The record doesn’t state a bedroom count for **{title}**." if not bedrooms else f"The saved record for **{title}** lists {bedrooms} bedrooms."
            return answer if language != "தமிழ்" else (f"**{title}** பதிவில் படுக்கையறை எண்ணிக்கை குறிப்பிடப்படவில்லை." if not bedrooms else f"**{title}** பதிவில் {bedrooms} படுக்கையறைகள் என்று உள்ளது.")
        if re.search(r"\b(?:area|size)\b", normalized):
            area = format_area_for_display(record)
            not_reported = tr("Not reported")
            answer = f"The record doesn’t state an area in a known unit for **{title}**." if area == not_reported else f"The saved record for **{title}** lists an area of {area}."
            return answer if language != "தமிழ்" else (f"**{title}** பதிவில் தெளிவான அலகுடன் பரப்பளவு குறிப்பிடப்படவில்லை." if area == not_reported else f"**{title}** பதிவில் பரப்பளவு {area} என்று உள்ளது.")
        if re.search(r"\b(?:source)\b", normalized):
            return f"Source: {source_name}{source_suffix}. Open the result’s verification link to review it." if language != "தமிழ்" else f"ஆதாரம்: {source_name}{source_suffix}. முடிவிலுள்ள சரிபார்ப்பு இணைப்பைத் திறக்கவும்."

    if language == "தமிழ்":
        parts = [f"**{title}** என்பது {place or 'தமிழ்நாட்டில்'} உள்ள {property_type} {status.lower()} ஆக சேமிக்கப்பட்டுள்ளது."]
        if price_value != "Price not provided":
            parts.append(f"{price_label}: {price_value}.")
        if status == "Project reference":
            parts.append("இது திட்ட அளவிலான குறிப்பு மட்டுமே; குறிப்பிட்ட வீடு இப்போது கிடைக்கிறது என்பதை உறுதிப்படுத்தாது.")
        parts.append(f"ஆதாரம்: {source_name}{source_suffix}.")
        parts.append("இதில் எந்த ஒரு விவரத்தைப் பற்றி மேலும் அறிய விரும்புகிறீர்கள்?")
    else:
        parts = [f"**{title}** is saved as a {status.lower()} for a {property_type}{f' in {place}' if place else ''}."]
        if price_value != "Price not provided":
            parts.append(f"{price_label}: {price_value}.")
        if status == "Project reference":
            parts.append("This is project-level information and does not confirm that an individual unit is currently available.")
        elif status in ("Existing sale", "Auction", "Auction ended"):
            parts.append("This is a saved snapshot, so current status should be checked with the source.")
        parts.append(f"Source: {source_name}{source_suffix}.")
        parts.append("Which detail would you like to know more about?")
    return " ".join(part for part in parts if part)


def local_property_contact_reply(text: str, chat_history: list[dict]) -> str | None:
    """Answer listing-contact questions only from contact fields in that record."""
    normalized = " ".join(text.casefold().split())
    if not re.search(
        r"\b(?:contact (?:details?|information|info|number|phone|email)|(?:owner|seller|agent|broker) contact|contact (?:the )?(?:owner|seller|agent|broker)|phone (?:number|details?)|mobile number|email address|call (?:the )?(?:owner|seller|agent|broker)|(?:owner|seller|agent|broker)'?s (?:contact|phone|number|details?)|number for (?:the )?(?:owner|seller|agent|broker)|reach (?:the )?(?:owner|seller|agent|broker)|who (?:can|should) i call)\b|தொடர்பு விவரம்|தொலைபேசி எண்",
        normalized,
    ):
        return None

    result_message = next(
        (item for item in reversed(chat_history) if item.get("role") == "assistant" and (
            (item.get("mode") == "results" and item.get("records"))
            or any(result.get("kind") == "properties" and result.get("data", {}).get("records") for result in item.get("tool_results", []))
        )),
        None,
    )
    if not result_message:
        return "மன்னிக்கவும், இந்த உரையாடலில் தொடர்பு விவரங்களைச் சரிபார்க்க ஒரு குறிப்பிட்ட சொத்து பதிவு இல்லை. எந்தப் பட்டியலைக் குறிப்பிடுகிறீர்கள்?" if language == "தமிழ்" else "I’m sorry, there isn’t a specific property record in this conversation for me to check. Which listing do you mean?"
    records = result_message.get("records") or next((
        result.get("data", {}).get("records", []) for result in result_message.get("tool_results", [])
        if result.get("kind") == "properties" and result.get("data", {}).get("records")
    ), [])
    if not records:
        return "மன்னிக்கவும், இந்தப் பட்டியலில் தொடர்பு விவரங்களைச் சரிபார்க்கும் பதிவு கிடைக்கவில்லை. பகுதி அல்லது பட்டியல் பெயரைச் சொன்னால் பொருந்தும் பதிவுகளைத் தேடலாம்." if language == "தமிழ்" else "I’m sorry, I don’t have a matching listing record with contact details to check. Share the area or listing name and I can look for a saved match."
    ordinal = re.search(r"\b(first|1st|second|2nd|third|3rd)\b", normalized)
    if ordinal:
        index = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}[ordinal.group(1)]
        if index >= len(records):
            return None
        record = records[index]
    else:
        record = next((row for row in records if str(row.get("title") or "").strip().casefold() in normalized), None)
        if record is None and len(records) == 1:
            record = records[0]
        elif record is None and len(records) > 1:
            return "எந்தச் சொத்தின் தொடர்பு விவரங்களைப் பார்க்க வேண்டும்? பட்டியலில் உள்ள வரிசை அல்லது பெயரைச் சொல்லுங்கள்." if language == "தமிழ்" else "Which property’s contact details should I check? You can name it or give its number in the results."
    if record is None:
        return None

    title = str(record.get("title") or record.get("property_type") or "this listing").strip()
    contact_fields = (
        ("Public contact name", ("public_contact_name", "listing_contact_name", "contact_name", "contact_person", "agent_name", "broker_name")),
        ("Public phone", ("public_contact_phone", "listing_contact_phone", "contact_phone", "contact_number", "phone_number", "mobile_number", "agent_phone", "broker_phone", "listing_phone", "office_phone")),
        ("Public email", ("public_contact_email", "listing_contact_email", "contact_email", "agent_email", "broker_email")),
        ("Contact details", ("public_contact", "contact_details", "contact")),
        ("Contact page", ("public_contact_url", "listing_contact_url", "contact_url", "agent_url", "broker_url")),
    )
    found = []
    for label, keys in contact_fields:
        value = next((str(record.get(key) or "").strip() for key in keys if str(record.get(key) or "").strip().casefold() not in {"", "nan", "none", "null", "not reported", "not available"}), "")
        if label == "Contact page" and value and not value.startswith(("https://", "http://")):
            value = ""
        if value:
            found.append((label, f"[{value}]({value})" if label == "Contact page" else value))

    if found:
        source_name = str(record.get("source_name") or "the saved listing source").strip()
        source_url, _, _, _ = property_source_lookup(record)
        rows = [f"{label}: **{value}**" for label, value in found]
        date = str(record.get("source_date") or "").strip()
        date_note = f" (source date: {date})" if date else ""
        link = f"\n\n[Open the source to verify ↗]({source_url})" if source_url.startswith(("https://", "http://")) else ""
        return (
            f"மன்னிக்கவும், தொடர்பு விவரங்கள் தற்போதையதா என்பதை என்னால் உறுதிப்படுத்த முடியாது. **{title}** பதிவில் {source_name}{date_note} வழங்கிய விவரங்கள்: " + "; ".join(rows) + f". வெளியிட்ட மூலத்தில் சரிபார்க்கவும்.{link}"
            if language == "தமிழ்" else
            f"I can’t verify whether these contact details are still current. The saved record for **{title}** lists the following from {source_name}{date_note}: " + "; ".join(rows) + f". Please confirm them on the source listing.{link}"
        )

    source_url, _, _, _ = property_source_lookup(record)
    if not source_url.startswith(("https://", "http://")):
        return (
            f"மன்னிக்கவும், **{title}** பதிவில் தொடர்பு விவரங்களும் சரிபார்க்கக்கூடிய மூல இணைப்பும் இல்லை. பதிவில் உள்ள வேறு எந்த விவரத்தில் உதவலாம்?"
            if language == "தமிழ்" else
            f"I’m sorry, the saved record for **{title}** has no contact details or verifiable source link. Is there another detail from the record I can help with?"
        )
    st.session_state.pending_contact_source = {"title": title, "property_id": str(record.get("property_id") or ""), "source_url": source_url, "source_name": str(record.get("source_name") or "the listing source")}
    return (
        f"மன்னிக்கவும், **{title}** பதிவில் தொடர்பு எண் அல்லது மின்னஞ்சல் இல்லை. பதிவில் உள்ள மற்ற விவரங்களைச் சரிபார்க்கலாம்; அல்லது மூலப் போர்டலில் தொடர்பு விருப்பம் உள்ளதா என்று பார்க்க வழிகாட்டலாம். அந்த மூல இணைப்பைப் பார்க்க விரும்புகிறீர்களா?"
        if language == "தமிழ்" else
        f"I’m sorry, the saved record for **{title}** doesn’t include a phone number or email. I can check another recorded detail with you, or guide you to {st.session_state.pending_contact_source['source_name']} to look for its contact option. Would you like the source link?"
    )


def local_loan_response(text: str, chat_history: list[dict]) -> tuple[str, str] | None:
    """Handle financing questions from saved prices without estimating lender terms."""
    normalized = " ".join(text.casefold().split())

    def amount_after(pattern: str) -> float | None:
        match = re.search(pattern + r"\s*₹?\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|l|k)?\b", normalized)
        if not match:
            return None
        amount = float(match.group(1).replace(",", ""))
        unit = (match.group(2) or "").casefold()
        factor = 10_000_000 if unit in {"crore", "crores", "cr"} else 100_000 if unit in {"lakh", "lakhs", "lac", "lacs", "l"} else 1_000 if unit == "k" else 1
        return amount * factor

    affirmative = bool(re.search(r"\b(?:yes|yeah|sure|please|go ahead|show me)\b|சரி|வேண்டும்", normalized))
    negative = bool(re.search(r"\b(?:no|not now|don't|do not|no thanks)\b|வேண்டாம்", normalized))
    pending = st.session_state.get("pending_loan_options")
    if pending and affirmative:
        st.session_state.pending_loan_options = None
        return (
            "இந்தச் சொத்தின் விலைக்கும் நீங்கள் கூறிய தொகைக்கும் உள்ள கணித வித்தியாசம் மட்டும் இது; அந்த முழுத் தொகையையும் வங்கிக் கடனாகப் பெறலாம் என்று அர்த்தமில்லை. வட்டி, கடன் கிடைப்பது, தகுதி, கட்டணங்கள் மற்றும் விதிமுறைகள் மாறலாம்; கடன் ஒப்புதல் அல்லது விகிதம் எதுவும் உறுதி இல்லை. நீங்கள் விரும்பினால், கீழே உள்ள அதிகாரப்பூர்வ வங்கி இணைப்புகளைத் திறந்து பார்க்கலாம்."
            if language == "தமிழ்" else
            "The difference is only the arithmetic gap between the recorded property price and the amount you mentioned; it doesn’t mean a lender will finance the full amount. Rates, availability, eligibility, fees, and terms vary and can change; no rate or approval is guaranteed. If you’d like, expand the official lender links below and choose a page to open.",
            "loans",
        )
    if pending and negative:
        st.session_state.pending_loan_options = None
        return ("சரி. கடன் விருப்பங்களை இப்போது பார்க்க வேண்டியதில்லை." if language == "தமிழ்" else "Of course. We can leave the loan options for now.", "welcome")

    intent = parse_request(text, properties)
    if intent.help_with_loan and re.search(r"\b(?:show me|find me|search for|look for|list)\s+(?:(?:some|available|a)\s+)?(?:properties|homes|houses|flats|apartments|plots|land|listings|[1-9]\s*bhk)\b", normalized):
        return None
    affordability_concern = bool(re.search(
        r"\b(?:over my budget|above my budget|more than i can afford|can't afford|cannot afford|too expensive|out of budget|too costly|budget is tight|exceeds? (?:my |the )?budget|beyond (?:my |the )?budget)\b|பட்ஜெட்டுக்கு மேல்|விலை அதிகம்",
        normalized,
    ))
    if not intent.help_with_loan and not affordability_concern:
        return None

    frame = st.session_state.get("last_results")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        frame = st.session_state.get("main_results")
    selected = None
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        for _, candidate in frame.iterrows():
            title = str(candidate.get("title", "")).strip().casefold()
            if title and title in normalized:
                selected = candidate
                break
        if selected is None and len(frame) == 1:
            selected = frame.iloc[0]

    budget = intent.max_budget
    mentioned_budget = amount_after(r"(?:budget(?:\s+(?:is|of|around|about))?|can afford|i can spend|upfront(?:\s+amount)?(?:\s+is)?)")
    if mentioned_budget is not None:
        budget = mentioned_budget
    if budget is None:
        budget = st.session_state.get("search_context", {}).get("max_budget")
    price = pd.to_numeric(selected.get("price_inr"), errors="coerce") if selected is not None else float("nan")
    mentioned_price = amount_after(r"(?:property\s+)?(?:price|cost|listed\s+at|asking\s+price)(?:\s+(?:is|of|around|about))?")
    if pd.isna(price) and mentioned_price is not None:
        price = mentioned_price
    known_gap = pd.notna(price) and budget is not None and float(price) > float(budget)
    amount_note = ""
    if known_gap:
        if selected is not None and pd.notna(pd.to_numeric(selected.get("price_inr"), errors="coerce")):
            title = str(selected.get("title") or selected.get("property_type") or "the selected property")
            amount_note = f" The saved record lists {title} at ₹{float(price):,.0f}; compared with your stated budget of ₹{float(budget):,.0f}, the arithmetic difference is ₹{float(price) - float(budget):,.0f}." if language != "தமிழ்" else f" சேமித்த பதிவில் {title} விலை ₹{float(price):,.0f}; நீங்கள் கூறிய ₹{float(budget):,.0f} பட்ஜெட்டுடன் ஒப்பிடும்போது கணித வித்தியாசம் ₹{float(price) - float(budget):,.0f}."
        else:
            amount_note = f" Based on the figures you gave, the arithmetic difference is ₹{float(price) - float(budget):,.0f} (price ₹{float(price):,.0f}, budget ₹{float(budget):,.0f})." if language != "தமிழ்" else f" நீங்கள் கூறிய எண்களின் அடிப்படையில் கணித வித்தியாசம் ₹{float(price) - float(budget):,.0f} (விலை ₹{float(price):,.0f}, பட்ஜெட் ₹{float(budget):,.0f})."

    if affordability_concern and not intent.help_with_loan:
        if known_gap:
            st.session_state.pending_loan_options = {"price": float(price), "budget": float(budget)}
            reply = (
                "அந்த விலை உங்கள் பட்ஜெட்டைத் தாண்டுவது கவலையாக இருக்கலாம்." + amount_note + " கடன் ஒரு சாத்தியமான வழியாக இருக்கலாம்; வங்கி அந்த முழு வித்தியாசத்தையும் வழங்கும் என்று உறுதி இல்லை. அதிகாரப்பூர்வ வங்கி விருப்பங்களைப் பார்க்க விரும்புகிறீர்களா?"
                if language == "தமிழ்" else
                "I can see why the price being above your budget is a concern." + amount_note + " A loan may be one route to explore, though a lender may not cover the full difference. Would you like me to show official lender options?"
            )
            return reply, "welcome"
        return (
            "உங்கள் பட்ஜெட்டை மீறாமல் பார்க்கலாம். எந்தப் பட்டியலைக் குறிப்பிடுகிறீர்கள்?" if language == "தமிழ்" else
            "Let’s keep your budget in view. Which listing are you referring to?",
            "welcome",
        )

    if intent.help_with_loan:
        if selected is None:
            if language == "தமிழ்":
                question = f"₹{float(budget) / 100_000:,.2f} லட்சம் உங்கள் மொத்த பட்ஜெட்டா, முன்பணமாக செலுத்தக்கூடிய தொகையா?" if known_gap else "எந்தப் பட்டியல் அல்லது சொத்து விலையைப் பார்க்கிறீர்கள், மேலும் முன்பணமாக எவ்வளவு செலுத்த முடியும்?"
                intro = "" if known_gap else "அந்த விவரங்கள் தெரிந்தால் விலை வித்தியாசத்தை கணக்கிட்டு பொருத்தமான அதிகாரப்பூர்வ வங்கி இணைப்புகளைத் தேர்ந்தெடுக்க முடியும். "
                intro += "வட்டி விகிதமும் கடன் கிடைப்பதும்/தகுதியும் மாறலாம்; தற்போதைய விவரங்களுக்கு வங்கியின் அதிகாரப்பூர்வ தளத்தைப் பார்க்கவும். எந்த வங்கியும் ஒப்புதல் வழங்கும் என்று இங்கு உறுதி செய்ய முடியாது."
            else:
                question = "Is that amount your total budget or what you could contribute upfront?" if known_gap else "Which listing or property price do you have in mind, and roughly how much could you put toward it upfront?"
                intro = "" if known_gap else "With those details, I can work out the price difference and narrow down relevant official lender pages. "
                intro += "Rates and loan availability/eligibility can vary or change, so check the lender’s official site for current terms. I can’t confirm any lender will approve a loan."
            return f"{intro}{amount_note} {question}", "loans"
        prop_type = str(selected.get("property_type", "")).casefold()
        if "plot" in prop_type or "land" in prop_type:
            fit = "For a residential plot, Union Bank publishes a specific plot-purchase option; SBI and HDFC also have home/plot information to check. Confirm plot approval and construction conditions directly." if language != "தமிழ்" else "குடியிருப்பு மனைக்கு Union Bank-இன் மனை வாங்கும் திட்ட விவரமும், SBI மற்றும் HDFC-யின் வீடு/மனை கடன் தகவல்களும் உள்ளன. மனை அங்கீகாரம் மற்றும் கட்டுமான நிபந்தனைகளை நேரடியாக உறுதிப்படுத்துங்கள்."
        else:
            fit = "For a home or flat purchase, the official home-loan pages below are relevant starting points; they do not establish which lender will offer you the lowest rate." if language != "தமிழ்" else "வீடு அல்லது அடுக்குமாடி வீடு வாங்க, கீழுள்ள அதிகாரப்பூர்வ வீட்டுக் கடன் பக்கங்கள் தொடக்கமாக உதவும்; எந்த வங்கி குறைந்த வட்டி தரும் என்பதை இவை உறுதி செய்யவில்லை."
        caution = " Rates, availability, eligibility, fees, and terms vary by lender and may change; no rate or approval is guaranteed. If you’d like, expand the official lender links below and choose a page to open." if language != "தமிழ்" else " வட்டி, கடன் கிடைப்பது, தகுதி, கட்டணங்கள் மற்றும் விதிமுறைகள் வங்கிக்கு வங்கி மாறலாம்; எந்த விகிதமோ ஒப்புதலோ உறுதி இல்லை. விரும்பினால், கீழே அதிகாரப்பூர்வ வங்கி இணைப்புகளைத் திறந்து ஒரு பக்கத்தைத் தேர்வு செய்யலாம்."
        return fit + amount_note + caution, "loans"
    return None


def _respond_without_logging(text: str):
    normalized = text.casefold()
    if st.session_state.get("conversation_closed"):
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": "This chat has ended. Choose **Start a new conversation** whenever you’d like to continue.", "mode": "conversation_closed"},
        ])
        return
    if st.session_state.get("end_chat_confirmation_pending"):
        affirmative = bool(re.fullmatch(r"[\W_]*(?:yes|yeah|yep|sure|please|end(?: it)?|wrap up|that's all|that is all|ஆம்|ஆமாம்|சரி)[\W_]*", normalized))
        negative = bool(re.fullmatch(r"[\W_]*(?:no|not yet|keep going|continue|one more thing|வேண்டாம்|இல்லை)[\W_]*", normalized))
        if affirmative:
            st.session_state.end_chat_confirmation_pending = False
            st.session_state.conversation_closed = True
            st.session_state.conversation_close_reason = "User confirmed Mira's end-of-chat question"
            st.session_state.conversation_ended_at = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
            reply = "சரி, உரையாடலை முடித்துவிட்டேன்; இந்த உரையாடலின் விவரங்கள் பாதுகாப்பான பதிவில் சேமிக்கப்பட்டுள்ளன. மீண்டும் பேச விரும்பினால் புதிய உரையாடலைத் தொடங்கலாம்." if language == "தமிழ்" else "Of course. I’ve ended our chat and saved its details in a private chat record. You can start a new conversation whenever you need."
            st.session_state.chat.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply, "mode": "conversation_end"}])
            return
        if negative:
            st.session_state.end_chat_confirmation_pending = False
            reply = "சரி, தொடரலாம். அடுத்து எதில் உதவலாம்?" if language == "தமிழ்" else "Of course—we can keep going. What else would be helpful?"
            st.session_state.chat.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply, "mode": "welcome"}])
            return
        st.session_state.end_chat_confirmation_pending = False
    if re.search(r"\b(?:end|close|finish)\s+(?:this\s+)?(?:chat|conversation)\b", normalized):
        st.session_state.conversation_closed = True
        st.session_state.conversation_close_reason = "User requested to end the chat"
        st.session_state.conversation_ended_at = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
        reply = "சரி, உரையாடலை முடித்துவிட்டேன்; இந்த உரையாடலின் விவரங்கள் பாதுகாப்பான பதிவில் சேமிக்கப்பட்டுள்ளன. மீண்டும் பேச விரும்பினால் புதிய உரையாடலைத் தொடங்கலாம்." if language == "தமிழ்" else "Of course. I’ve ended our chat and saved its details in a private chat record. You can start a new conversation whenever you need."
        st.session_state.chat.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply, "mode": "conversation_end"}])
        return
    conversation = conversational_turn(text, properties, st.session_state.chat,
        st.session_state.get("search_context"), st.session_state.get("buyer_memory"),
        st.session_state.get("response_language", "Tamil" if language == "தமிழ்" else "English"))
    st.session_state.search_context = conversation["context"]
    st.session_state.buyer_memory = conversation["memory"]
    st.session_state.response_language = conversation["memory"]["response_language"]
    if conversation.get("reply"):
        st.session_state.pending_area_source_check = False
        st.session_state.pending_contact_source = None
        st.session_state.property_inquiry_active = False
        st.session_state.awaiting_search_preferences = False
        if conversation.get("close"):
            st.session_state.conversation_closed = True
            st.session_state.conversation_close_reason = "Customer ended the conversation"
            st.session_state.conversation_ended_at = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
            st.session_state.end_chat_confirmation_pending = False
        if conversation.get("reminder_due") or conversation.get("open_followups"):
            st.session_state.active_info_panel = "followups"
            st.session_state.followup_summary_input = conversation.get("reminder_summary", text)
            st.session_state.proposed_reminder_due = conversation.get("reminder_due")
        if conversation.get("removed_suggestions") is not None:
            st.session_state.main_results = pd.DataFrame()
            st.session_state.last_results = pd.DataFrame()
            st.session_state.main_results_total_count = 0
            st.session_state.main_results_mode = "none"
            st.session_state.filters_applied = False
        st.session_state.chat.extend([{"role": "user", "content": text},
            {"role": "assistant", "content": conversation["reply"], "mode": conversation["intent"]}])
        return
    understood = understand_request(text, properties, st.session_state.chat,
        st.session_state.get("search_context"), st.session_state.get("buyer_memory"), language == "தமிழ்")
    if understood:
        if understood.get("greeting"):
            st.session_state.property_inquiry_active = False
            st.session_state.awaiting_search_preferences = False
        st.session_state.search_context = understood["context"]
        st.session_state.buyer_memory = understood["memory"]
        st.session_state.pending_area_source_check = False
        st.session_state.pending_contact_source = None
        if "results" in understood:
            ranked = understood["results"]
            st.session_state.last_results = ranked.head(30)
            st.session_state.main_results = ranked.head(3).copy()
            st.session_state.main_results_total_count = len(ranked)
            st.session_state.main_results_mode = "chat"
            st.session_state.active_listing_view = "all"
            st.session_state.property_inquiry_active = True
            st.session_state.awaiting_search_preferences = False
            intent = parse_request("", properties)
            for key, value in understood["context"].items():
                if hasattr(intent, key):
                    setattr(intent, key, value)
            queue_mira_filter_sync(intent)
            records = ranked.head(3).to_dict("records")
            reply = grounded_search_reply({"records": records}, understood["memory"], language == "தமிழ்")
            st.session_state.chat.extend([{"role": "user", "content": text},
                {"role": "assistant", "content": reply, "mode": "results", "records": records,
                 "count": len(ranked), "intent": understood["context"]}])
        else:
            st.session_state.chat.extend([{"role": "user", "content": text},
                {"role": "assistant", "content": understood["reply"], "mode": "welcome" if understood.get("greeting") else "property_detail"}])
        return
    wants_followup = bool(re.search(r"\b(?:remind me|set (?:a )?reminder|follow[- ]?up|check back with me|email me later|send me a follow[- ]?up)\b|நினைவூட்ட|பின்னர் தொடர்பு", normalized))
    declines_followup = bool(re.search(r"\b(?:don't|do not|no)\s+(?:send|email|remind|follow)\b|வேண்டாம்", normalized))
    if wants_followup and not declines_followup:
        st.session_state.active_info_panel = "followups"
        st.session_state.followup_summary_input = text[:500]
        reply = (
            "Follow-ups பகுதியில் உங்களுக்கு ஏற்ற முறையைத் தேர்வு செய்யலாம்: இந்த உலாவிக்கான நினைவூட்டல் அல்லது Email follow-up. Email வசதி செயல்பாட்டில் இருந்தால் மட்டும் உங்கள் முகவரி மற்றும் ஒப்புதலுடன் 3 நாட்களுக்கு ஒருமுறை, அதிகபட்சம் 3 மின்னஞ்சல்களை அமைக்கலாம். இன்னும் சேமிக்கப்படவில்லை; நீங்கள் தேர்வு செய்து Save செய்ய வேண்டும்."
            if language == "தமிழ்" else
            "I’ve opened Follow-ups for you. Choose an in-app reminder or, if email is enabled, opt in to one email every three days for up to three messages. Nothing is scheduled until you choose the method and save it."
        )
        st.session_state.chat.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply, "mode": "followup_guidance"}])
        return
    pending_contact = st.session_state.get("pending_contact_source")
    if isinstance(pending_contact, dict):
        affirmative = bool(re.fullmatch(r"[\W_]*(?:yes|yeah|yep|sure|please|go ahead|show(?: me)?|that works|okay|ok|ஆம்|ஆமாம்|சரி|காட்டுங்கள்|வேண்டும்)(?:[, ]+please)?[\W_]*", normalized))
        negative = bool(re.fullmatch(r"[\W_]*(?:no|no thanks|not now|never mind|வேண்டாம்|இப்போது வேண்டாம்)[\W_]*", normalized))
        if affirmative:
            st.session_state.pending_contact_source = None
            source_url = str(pending_contact.get("source_url") or "")
            title = str(pending_contact.get("title") or "the listing")
            property_id = str(pending_contact.get("property_id") or "")
            identifier = f" (reference {property_id})" if property_id else ""
            if source_url.startswith(("https://", "http://")):
                reply = (
                    f"சரி. [{pending_contact.get('source_name', 'மூல போர்டல்')} இணைப்பைத் திறக்கவும் ↗]({source_url}). அங்கு **{title}**{identifier} என்று தேடி, வெளியிட்டவரின் தொடர்பு விருப்பத்தைப் பாருங்கள். இது சேமித்த பதிவு; தற்போதைய தொடர்பு விவரங்கள் அல்லது கிடைப்பை அந்தப் போர்டலில் உறுதிப்படுத்தவும்."
                    if language == "தமிழ்" else
                    f"Sure. [Open {pending_contact.get('source_name', 'the source portal')} ↗]({source_url}) and search for **{title}**{identifier}; then use the publisher’s contact option if one is shown. This is a saved snapshot, so confirm the current contact details and listing status on the portal."
                )
            else:
                reply = "மன்னிக்கவும், இந்தப் பதிவில் சரிபார்க்கக்கூடிய மூல இணைப்பு இல்லை. வேறு பதிவான விவரத்தில் உதவவா?" if language == "தமிழ்" else "I’m sorry, this record has no source link I can guide you to. Would another recorded property detail help?"
            st.session_state.chat.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply, "mode": "source_guidance"}])
            return
        if negative:
            st.session_state.pending_contact_source = None
            reply = "சரி. வேறு எந்தப் பதிவான விவரத்தில் உதவலாம்?" if language == "தமிழ்" else "Of course. Is there another recorded detail I can help with?"
            st.session_state.chat.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply, "mode": "welcome"}])
            return
        st.session_state.pending_contact_source = None
    pending_area_source = st.session_state.get("pending_area_source_check")
    if pending_area_source:
        affirmative = bool(re.fullmatch(
            r"[\W_]*(?:yes|yeah|yep|sure|please|go ahead|show(?: me)?|that works|okay|ok|ஆம்|ஆமாம்|சரி|காட்டுங்கள்|வேண்டும்)(?:[, ]+please)?[\W_]*",
            normalized,
        ))
        negative = bool(re.fullmatch(r"[\W_]*(?:no|no thanks|not now|never mind|வேண்டாம்|இப்போது வேண்டாம்)[\W_]*", normalized))
        if affirmative or negative:
            st.session_state.pending_area_source_check = False
            if affirmative:
                reply = (
                    "சரி. பொருந்திய பதிவுகளின் கீழே உள்ள ‘விவரங்களைச் சரிபார்க்கவும் அல்லது ஆதாரத்தைப் பார்க்கவும்’ என்பதைத் திறந்து, மூல இணைப்பைத் தேர்ந்தெடுக்கலாம். அங்கு புதுப்பிக்கப்பட்ட பரப்பளவு மற்றும் பிற விவரங்களை நேரடியாகச் சரிபார்க்கவும்; சேமித்த பதிவில் அவை உறுதிப்படுத்தப்படவில்லை."
                    if language == "தமிழ்" else
                    "Sure. On the matching property cards, open **Verify details or view source** and select the source link. You can check the updated area and other details there; they aren’t confirmed in the saved record."
                )
            else:
                reply = "சரி. விரும்பும்போது அந்த ஆதார இணைப்பைத் திறக்கலாம்." if language == "தமிழ்" else "Of course. You can open the source link whenever you’re ready."
            st.session_state.chat.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply, "mode": "source_guidance"},
            ])
            return
    pending_undated = st.session_state.get("pending_undated_auction_records")
    if isinstance(pending_undated, pd.DataFrame) and not pending_undated.empty:
        affirmative = bool(re.match(
            r"[\W_]*(?:yes|yeah|yep|sure|please|go ahead|show(?: me)?(?: them)?|that works|okay|ok|i(?:'d| would) like to (?:see|view)|சரி|ஆம்|ஆமாம்|காட்டு|காட்டுங்கள்|வேண்டும்)\b",
            normalized,
        ))
        negative = bool(re.fullmatch(
            r"[\W_]*(?:no|no thanks|not now|never mind|cancel|வேண்டாம்|இப்போது வேண்டாம்)[\W_]*",
            normalized,
        ))
        if affirmative:
            records = pending_undated.copy()
            st.session_state.pending_undated_auction_records = None
            st.session_state.last_results = records.head(30).copy()
            st.session_state.main_results = records.head(3).copy()
            st.session_state.main_results_total_count = len(records)
            st.session_state.main_results_mode = "chat"
            st.session_state.active_listing_view = "all"
            st.session_state.filters_applied = True
            reply = (
                f"சரி. {len(records)} பதிவுகள் கிடைத்துள்ளன; முதல் பொருத்தங்கள் மேலே உள்ளன. இவற்றில் ஏலத் தேதி இல்லை, மேலும் ஆதாரம் கிடைக்காது எனக் குறித்துள்ளது. ஒவ்வொரு பதிவிலும் உள்ள மூல இணைப்பைத் திறந்து தற்போதைய அறிவிப்பை நேரடியாகச் சரிபார்க்கவும்."
                if language == "தமிழ்" else
                f"Okay. I found {len(records)} saved records; the closest matches are above. They have no auction date recorded, and the source marks them unavailable. Open a record’s source link to check the current notice directly."
            )
            st.session_state.chat.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply, "mode": "results", "count": len(records), "records": records.head(5).to_dict("records")},
            ])
            return
        if negative:
            st.session_state.pending_undated_auction_records = None
            reply = "சரி, காட்டமாட்டேன். தேதி உள்ள ஏலப் பதிவுகளுடன் தொடரலாம்." if language == "தமிழ்" else "Of course, I won’t show them. We can stick to records that include an auction date."
            st.session_state.chat.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply, "mode": "welcome"},
            ])
            return
        st.session_state.pending_undated_auction_records = None
    remember_soft_search_preferences(text)
    advisor_state, advisor_message = advisor_reply(text, st.session_state.get("advisor_request"),
        language == "தமிழ்", asks_for_live_handoff(text))
    st.session_state.advisor_request = advisor_state
    if advisor_message:
        st.session_state.chat.extend([{"role": "user", "content": text},
            {"role": "assistant", "content": advisor_message,
             "mode": "callback_request_confirmed" if advisor_state.get("stage") == "confirmed" else "advisor_preferences"}])
        return
    st.session_state.search_context = update_preferences(text, properties, st.session_state.get("search_context", {}))
    st.session_state.buyer_memory = update_buyer_memory(text, st.session_state.search_context,
        st.session_state.chat, st.session_state.get("buyer_memory"))
    memory_reply = record_detail_reply(text, st.session_state.buyer_memory,
        current_shown_records(st.session_state.chat), language == "தமிழ்")
    if memory_reply and not re.search(r"\b(?:find|search|show me|list)\b", normalized):
        st.session_state.chat.extend([{"role": "user", "content": text},
            {"role": "assistant", "content": memory_reply, "mode": "property_detail"}])
        return
    if re.search(r"\b(?:reject|skip|don't like|do not like|not interested in|not for me)\b", normalized) and st.session_state.buyer_memory.get("selected") and not re.search(r"\b(?:find|search|show|list)\b", normalized):
        rejected_title = st.session_state.buyer_memory["selected"].get("title", "")
        reply = f"**{rejected_title}** பட்டியலை அடுத்த பரிந்துரைகளில் தவிர்க்கிறேன். மற்ற விருப்பங்களை வைத்திருக்கிறேன்." if language == "தமிழ்" else f"I’ll leave **{rejected_title}** out of the next recommendations and keep your other preferences."
        st.session_state.chat.extend([{"role": "user", "content": text}, {"role": "assistant", "content": reply, "mode": "preference_update"}])
        return
    if st.session_state.get("agent_rate_limited") and datetime.now(INDIA_TZ).timestamp() >= st.session_state.get("agent_retry_at", float("inf")):
        st.session_state.agent_rate_limited = False
    ai_conversation_available = bool(AI_API_KEY and not st.session_state.get("agent_rate_limited"))
    if not ai_conversation_available:
        lifestyle_reply = contextual_reply(text, st.session_state.search_context, "Tamil" if language == "தமிழ்" else "English")
        if lifestyle_reply and not re.search(r"\b(?:show|find|search|list)\b", normalized):
            st.session_state.chat.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": lifestyle_reply, "mode": "contextual_guidance"},
            ])
            return
    if re.search(r"\b(?:approval doesn't matter|approval does not matter|approval isn't important|approval is not important)\b", normalized):
        st.session_state.land_approval_caution_pending = True
    recent = st.session_state.chat[-2:]
    normalized_prompt = " ".join(normalized.split())
    if (
        len(recent) == 2
        and recent[0].get("role") == "user"
        and recent[1].get("role") == "assistant"
        and recent[1].get("mode") == "results"
        and " ".join(recent[0].get("content", "").casefold().split()) == normalized_prompt
    ):
        count = int(recent[1].get("count", 0))
        if count:
            reply = ("இந்தத் தேடலுக்கான பதிவுகளை ஏற்கனவே மேலே காட்டியுள்ளேன். பகுதி அல்லது பட்ஜெட்டை மாற்ற விரும்பினால் சொல்லுங்கள்."
                     if language == "தமிழ்" else "I’ve already shown the saved results for this search above. If you meant a different area or budget, tell me and I can update it.")
        else:
            reply = ("சேமிக்கப்பட்ட பதிவுகளில் இந்தத் தேடலுக்குப் பொருத்தம் இல்லை. பட்ஜெட் மற்றும் மற்ற விருப்பங்களை வைத்துக்கொண்டு அருகிலுள்ள பகுதிகளையும் சேர்த்துப் பார்க்கலாமா?"
                     if language == "தமிழ்" else "I couldn’t find a match in the saved records. Would you be open to including nearby areas while I keep your budget and other preferences as they are?")
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply, "mode": "welcome"},
        ])
        return
    if is_cmda_price_or_availability_question(text):
        reply = FRIENDLY_CMDA_NOTE_TAMIL if language == "தமிழ்" else FRIENDLY_CMDA_NOTE
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply, "mode": "welcome"},
        ])
        return
    rental_reply = local_rental_support_reply(text, st.session_state.chat)
    if rental_reply:
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": rental_reply, "mode": "rental_support"},
        ])
        return
    normalized_land_text = " ".join(text.casefold().split())
    asks_plot_comparison = bool(re.search(
        r"\b(?:compare these|compare .*plots|which one would you buy|which would you buy)\b",
        normalized_land_text,
    ))
    if asks_plot_comparison:
        records = st.session_state.get("main_results", pd.DataFrame())
        if isinstance(records, pd.DataFrame) and not records.empty:
            if "property_id" in records.columns:
                records = records.drop_duplicates(subset=["property_id"], keep="first")
            records = records.head(3)
            bullets = []
            for _, row in records.iterrows():
                name = str(row.get("title") or "Saved plot record")
                price_label, price_value = format_price_for_card(row.to_dict())
                area = str(row.get("area_display") or "Not stated in saved record")
                approval = str(row.get("approval_number") or "").strip()
                if not approval or approval.casefold() in {"not published on public vgn source", "not published on public vgn page", "nan"}:
                    approval = "Not stated in saved record"
                source = str(row.get("source_name") or "Saved source")
                status = str(row.get("listing_status") or "Saved record")
                bullets.append(f"- **{name}** — {price_label}: {price_value}; area: {area}; approval: {approval}; record: {status}; source: {source}.")
            header = (
                "எனக்கு தனிப்பட்ட விருப்பம் இல்லை; சேமிக்கப்பட்ட பதிவுகள் மட்டும் கொண்டு ஒப்பிடுகிறேன். இப்போது காட்டப்படும் தனித்தனி முடிவுகள்:"
                if language == "தமிழ்" else
                "I don’t have personal preferences, but I can compare the saved facts. Here are the distinct results currently shown:"
            )
            ending = (
                "இந்தப் பதிவுகளில் விலை அல்லது அனுமதி தெரியாவிட்டால், முடிவு செய்வதற்கு முன் மூல ஆதாரத்திலும் உங்கள் வழக்கறிஞரிடமும் சரிபார்க்கவும்."
                if language == "தமிழ்" else
                "Missing prices or approval details mean these records aren’t enough to choose safely; verify them with the source and your lawyer before deciding."
            )
            comparison_reply = header + "\n\n" + "\n".join(bullets) + "\n\n" + ending
            st.session_state.property_inquiry_active = False
            st.session_state.chat.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": comparison_reply, "mode": "local_property_comparison"},
            ])
            return
        comparison_reply = (
            "இப்போது ஒப்பிடக்கூடிய மனைப் பதிவுகள் தெரியவில்லை. மூன்று பட்டியல் பெயர்களையோ அவற்றின் முடிவுகளையோ காட்டினால், விலை, பரப்பளவு, அனுமதி, ஆதாரம் ஆகியவற்றை ஒப்பிடுகிறேன்; தனிப்பட்ட முறையில் எதை வாங்குவேன் என்று கூற முடியாது."
            if language == "தமிழ்" else
            "I don’t see plot records to compare right now. Share the three listing names or show their results and I can compare recorded price, area, approval, and sources; I don’t have a personal buying preference."
        )
        st.session_state.property_inquiry_active = False
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": comparison_reply, "mode": "local_property_comparison"},
        ])
        return
    asks_plot_or_flat = bool(re.search(
        r"\b(?:plot.*flat|flat.*plot|plot or flat|flat or plot)\b|ennoda budget.*(?:plot|flat)",
        normalized_land_text,
    ))
    budget_match = re.search(r"(?:₹\s*)?(\d+(?:\.\d+)?)\s*(lakh|lakhs|lac|lacs|crore|crores|cr)\b", normalized_land_text)
    if asks_plot_or_flat and budget_match:
        amount = float(budget_match.group(1))
        budget_inr = amount * (10_000_000 if budget_match.group(2).startswith("cr") else 100_000)
        remembered = st.session_state.get("search_context", {})
        saved_location = str(remembered.get("location") or "")
        comparison = search_properties(
            properties,
            location=saved_location,
            property_type=["Plot", "Flat"],
            status=["Existing sale", "Project reference"],
            max_budget=budget_inr,
        )
        comparison = comparison.dropna(subset=["price_inr"])
        if "property_id" in comparison.columns:
            comparison = comparison.drop_duplicates(subset=["property_id"], keep="first")
        comparison = comparison.sort_values("price_inr", ascending=True, na_position="last")
        plot_count = int(comparison["property_type"].eq("Plot").sum()) if not comparison.empty else 0
        flat_count = int(comparison["property_type"].eq("Flat").sum()) if not comparison.empty else 0
        st.session_state.last_results = comparison.head(30).copy()
        st.session_state.main_results = comparison.head(3).copy()
        st.session_state.main_results_total_count = len(comparison)
        st.session_state.main_results_mode = "chat"
        st.session_state.active_listing_view = "all"
        st.session_state.filters_applied = True
        st.session_state.property_inquiry_active = False
        st.session_state.awaiting_search_preferences = False
        if len(comparison):
            location_note = f" in {saved_location}" if saved_location else ""
            reply = (
                f"I checked the saved records{location_note} for exact recorded prices at or below ₹{amount:g} {budget_match.group(2)}. I found {plot_count} plot record(s) and {flat_count} flat record(s); the lowest priced matches are shown above. Records without an exact total price were excluded, so this is only a comparison of priced records in this dataset. These are saved snapshots, not confirmation that a property is still available."
                if language != "தமிழ்" else
                f"சேமித்த பதிவுகளில்{location_note} ₹{amount:g} {budget_match.group(2)} அல்லது அதற்குக் குறைவான சரியான விலை உள்ளவற்றைத் தேடினேன். {plot_count} மனைப் பதிவுகளும் {flat_count} flat பதிவுகளும் கிடைத்தன; குறைந்த விலைப் பொருத்தங்கள் மேலே உள்ளன. சரியான மொத்த விலை இல்லாத பதிவுகளை சேர்க்கவில்லை. இது இந்தத் தரவிலுள்ள விலை பதிவுகளின் ஒப்பீடு மட்டுமே; சேமித்த பதிவு தற்போதைய கிடைப்பை உறுதிப்படுத்தாது."
            )
        else:
            reply = (
                f"I checked the saved plot and flat records{f' for {saved_location}' if saved_location else ''}, but none has an exact recorded total price at or below ₹{amount:g} {budget_match.group(2)}. That only means this dataset has no priced match; it doesn’t mean there are no suitable homes on the market. I can widen the area or compare records with prices not listed separately."
                if language != "தமிழ்" else
                f"சேமித்த மனை மற்றும் flat பதிவுகளை{f' {saved_location} பகுதியில்' if saved_location else ''} பார்த்தேன்; ₹{amount:g} {budget_match.group(2)} அல்லது அதற்குக் குறைவான சரியான மொத்த விலை கொண்ட பதிவு இல்லை. இந்தத் தரவில் விலை குறிப்பிடப்பட்ட பொருத்தம் இல்லை என்பதையே இது குறிக்கிறது; சந்தையில் வீடுகள் இல்லை என்று அர்த்தமல்ல. அருகிலுள்ள பகுதிகளை சேர்த்தோ விலை குறிப்பிடப்படாத பதிவுகளை ஒப்பிட்டோ பார்க்கலாம்."
            )
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply, "mode": "local_budget_comparison"},
        ])
        return
    land_reply = local_land_conversation_reply(text, st.session_state.chat, language) if not ai_conversation_available else None
    if land_reply:
        # A land question is still part of the same conversation, but it is
        # not automatically a request to show the remembered search again.
        st.session_state.property_inquiry_active = False
        st.session_state.awaiting_search_preferences = False
        turn_intent = parse_request(text, properties)
        remembered = dict(st.session_state.get("search_context", {}))
        for key in ("location", "max_budget", "min_area_sqm", "bedrooms", "property_type", "status"):
            value = getattr(turn_intent, key, None)
            if key == "property_type":
                if value and value != "Any":
                    remembered[key] = value
            elif key == "status":
                if value and value != "Any":
                    remembered[key] = value
            elif value not in (None, "", 0):
                remembered[key] = value
        if remembered:
            st.session_state.search_context = remembered
        if re.search(r"\b(?:why did you show me the same|same plot twice|duplicate plot|are you even listening)\b", normalized_land_text):
            frame = st.session_state.get("last_results")
            if isinstance(frame, pd.DataFrame) and "property_id" in frame.columns:
                unique = frame.drop_duplicates(subset=["property_id"], keep="first").reset_index(drop=True)
                if len(unique) < len(frame):
                    st.session_state.last_results = unique
                    st.session_state.main_results = unique.head(3).copy()
                    st.session_state.main_results_total_count = len(unique)
                    st.session_state.main_results_mode = "chat"
                    st.session_state.active_listing_view = "all"
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": land_reply, "mode": "local_property_support"},
        ])
        return
    policy_reply = local_policy_reply(text)
    if policy_reply:
        st.session_state.property_inquiry_active = False
        st.session_state.awaiting_search_preferences = False
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": policy_reply, "mode": "welcome"},
        ])
        return
    # A factual question about the visible results must be answered from their
    # saved fields before a broad sentiment handler responds to only the tone.
    result_followup = local_result_followup_reply(text, st.session_state.chat)
    if result_followup:
        st.session_state.property_inquiry_active = False
        st.session_state.awaiting_search_preferences = False
        concern = bool(re.search(
            r"\b(?:worried|concerned|nervous|anxious|scared|frustrated|disappointed|stressed|afraid)\b|கவலை|பதற்றம்|ஏமாற்றம்",
            normalized,
        ))
        if concern and not re.search(r"\b(?:sorry|apolog)", result_followup, re.IGNORECASE):
            prefix = "I can see why you’d want to check that carefully. " if language != "தமிழ்" else "அதை கவனமாகச் சரிபார்க்க விரும்புவது புரிகிறது. "
            result_followup = prefix + result_followup
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": result_followup, "mode": "property_detail"},
        ])
        return
    if is_pausing_property_search(text):
        # Keep any preferences the user volunteered, but don't turn them into
        # cards until they clearly ask to browse.
        intent = parse_request(text, properties)
        previous = st.session_state.get("search_context", {})
        for key in ("location", "max_budget", "min_area_sqm"):
            if not getattr(intent, key) and previous.get(key):
                setattr(intent, key, previous[key])
        if intent.bedrooms is None and previous.get("bedrooms"):
            intent.bedrooms = previous["bedrooms"]
        if intent.property_type == "Any" and previous.get("property_type", "Any") != "Any":
            intent.property_type = previous["property_type"]
        if intent.status == "Any" and previous.get("status", "Any") != "Any":
            intent.status = previous["status"]
        st.session_state.search_context = intent.__dict__.copy()
        st.session_state.property_inquiry_active = False
        st.session_state.awaiting_search_preferences = False
        reply = (
            "அவசரமில்லை. நீங்கள் தயாராகும் வரை பட்டியல்களை காட்டமாட்டேன். பின்னர் தொடர விரும்பினால், "
            "இந்த உரையாடலில் நீங்கள் சொன்ன விருப்பங்களை நினைவில் வைத்துக்கொள்கிறேன்."
            if language == "தமிழ்" else
            "No rush. I won’t show listings until you ask. I’ll keep the preferences you shared in mind for this conversation."
        )
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply, "mode": "welcome"},
        ])
        return
    awaiting_preferences = bool(st.session_state.get("awaiting_search_preferences"))
    candidate_intent = parse_request(text, properties)
    has_new_search_criteria = bool(
        candidate_intent.location
        or candidate_intent.property_type != "Any"
        or candidate_intent.bedrooms is not None
        or candidate_intent.status != "Any"
        or candidate_intent.max_budget is not None
        or candidate_intent.min_area_sqm is not None
    )
    prior_results_visible = (
        st.session_state.get("main_results_mode") == "chat"
        or (st.session_state.get("filters_applied") and st.session_state.get("main_results_mode") == "filters")
    )
    # A concrete new preference after results is a natural refinement request.
    # Use it directly instead of asking the user to repeat a budget or location.
    asks_a_question = "?" in text or bool(re.search(
        r"\b(?:can i|could i|would it|is it|are they|does it|do they|what|why|how|where|when|who|which|should i|tell me|explain)\b",
        normalized,
    ))
    feedback_turn = bool(re.search(
        r"\b(?:disappoint(?:ed|ing)?|dissatisfied|not satisfied|not listening|ignored|missed|wrong|not what i asked|asked for .* not|too expensive|over my budget|too far|none of these|not helpful|not helping|going in circles|fed up|frustrated|upset)\b|ஏமாற்றம்|திருப்தி இல்லை|உதவவில்லை|கேட்கவில்லை",
        normalized,
    ))
    asks_for_updated_list = bool(re.search(
        r"\b(?:find|search|show me|list|browse|filter|refine|narrow)\b",
        normalized,
    ))
    # A new detail can refine visible results, but a question containing a
    # location/budget is usually asking for an answer, not another search.
    # A complaint like "I asked for plots, not flats" is feedback, even though
    # the lightweight parser may spot "flat" as a new type preference.
    refine_visible_results = (
        prior_results_visible and has_new_search_criteria and not asks_a_question
        and (not feedback_turn or asks_for_updated_list)
    )
    answering_search_question = awaiting_preferences and has_new_search_criteria and not asks_a_question
    explicit_search = answering_search_question or refine_visible_results or bool(re.search(
        r"\b(?:find|search|show me|list|browse|filter|refine|narrow)\b"
        r"|\b(?:give me|show me) (?:the )?property details\b|\bdetails of (?:the )?property\b"
        r"|\b(?:suggest|recommend) (?:me )?(?:some|a|the|properties|homes|flats|plots)\b"
        r"|காட்டு|தேடு|வேண்டும்|வீடு தேட",
        normalized,
    ))
    if asks_a_question and not bool(re.search(
        r"\b(?:find|search|show|list|browse|filter|refine|narrow)\b.{0,55}\b(?:properties|listings|homes|houses|flats|apartments|plots|land|bhk|results|options)\b",
        normalized,
    )):
        explicit_search = False
    contact_question = bool(re.search(
        r"\b(?:contact (?:details?|information|info|number|phone|email)|(?:owner|seller|agent|broker) contact|contact (?:the )?(?:owner|seller|agent|broker)|phone (?:number|details?)|mobile number|email address|call (?:the )?(?:owner|seller|agent|broker)|(?:owner|seller|agent|broker)'?s (?:contact|phone|number|details?)|number for (?:the )?(?:owner|seller|agent|broker)|reach (?:the )?(?:owner|seller|agent|broker)|who (?:can|should) i call)\b|தொடர்பு விவரம்|தொலைபேசி எண்",
        normalized,
    ))
    asks_to_search_listings = bool(re.search(
        r"\b(?:find|search|show|list|browse|filter|refine|narrow)\b.{0,55}\b(?:properties|listings|homes|houses|flats|apartments|plots|land|bhk|results|options)\b",
        normalized,
    ))
    if contact_question and not asks_to_search_listings and not has_new_search_criteria:
        explicit_search = False
    # Remembered search state is context only. It must never, by itself, turn
    # an informational or emotional message into a property search.
    continuing_search = False
    if asks_for_live_handoff(text) and not explicit_search and not continuing_search:
        reply = (
            "நேரடி ஆலோசகருடன் இணைக்கும் வசதி இப்போது இந்தச் செயலியில் இல்லை. உங்கள் கேள்வியைச் சுருக்கமாக ஒழுங்குபடுத்தவோ, ஆதாரத் தகவலைச் சரிபார்க்கவோ நான் உதவலாம்—எது பயனுள்ளதாக இருக்கும்?"
            if language == "தமிழ்" else
            "I can’t connect you to a live advisor from this app yet. I can help organize your question or check the saved source details—what would be most useful?"
        )
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply, "mode": "welcome"},
        ])
        return
    if contact_question and not explicit_search:
        contact_reply = local_property_contact_reply(text, st.session_state.chat)
        if contact_reply:
            st.session_state.property_inquiry_active = False
            st.session_state.awaiting_search_preferences = False
            st.session_state.chat.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": contact_reply, "mode": "property_contact"},
            ])
            return
    loan_reply = local_loan_response(text, st.session_state.chat)
    if loan_reply:
        st.session_state.property_inquiry_active = False
        st.session_state.awaiting_search_preferences = False
        st.session_state.chat.extend([
            {"role": "user", "content": text},
            {"role": "assistant", "content": loan_reply[0], "mode": loan_reply[1]},
        ])
        return
    local_reply = None
    if not explicit_search and not ai_conversation_available:
        local_reply = local_dialogue_reply(text, st.session_state.chat, language)
        if local_reply:
            st.session_state.property_inquiry_active = False
            st.session_state.awaiting_search_preferences = False
            st.session_state.chat.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": local_reply, "mode": "local_playbook"},
            ])
            return
        local_reply = local_chat_reply(text, st.session_state.chat)
    if local_reply:
        st.session_state.property_inquiry_active = False
        st.session_state.awaiting_search_preferences = False
        st.session_state.chat.append({"role": "user", "content": text})
        st.session_state.chat.append({"role": "assistant", "content": local_reply, "mode": "local_talk"})
        return
    if AI_API_KEY and not st.session_state.get("agent_rate_limited"):
        st.session_state.in_progress_request = {"text": text, "chat": list(st.session_state.chat),
            "preferences": dict(st.session_state.get("search_context", {}))}
        turn = run_openai_agent(
            text=text,
            history=[{"role": item["role"], "content": item["content"]} for item in st.session_state.chat if item.get("role") in ("user", "assistant")],
            properties=properties,
            sources=sources,
            api_key=AI_API_KEY,
            provider=AI_PROVIDER,
            language=st.session_state.get("buyer_memory", {}).get("response_language", "Tamil" if language == "தமிழ்" else "English"),
            model=AI_MODEL,
            buyer_context={
                **st.session_state.get("search_context", {}),
                "buyer_memory": st.session_state.get("buyer_memory", {}),
                "details_to_verify": st.session_state.get("soft_search_preferences", []),
                "customer_name": st.session_state.get("customer_name", ""),
                "preferred_form_of_address": st.session_state.get("preferred_form_of_address", ""),
            },
            learning_guidance=active_learning_guidance(),
        )
        st.session_state.pop("in_progress_request", None)
        if turn.text:
            st.session_state.agent_rate_limited = False
            st.session_state.offer_delay_callback = False
            auction_tool = next((result for result in turn.tool_results if result.display_kind == "auctions"), None)
            if auction_tool and not auction_tool.data.get("count") and auction_tool.data.get("undated_count"):
                intent = parse_request(text, properties)
                undated = search_properties(
                    properties,
                    location=intent.location,
                    property_type=intent.property_type,
                    bedrooms=intent.bedrooms,
                    status=["Auction date not listed"],
                    max_budget=intent.max_budget,
                    min_area_sqm=intent.min_area_sqm,
                )
                if not undated.empty:
                    st.session_state.pending_undated_auction_records = undated.copy()
                    st.session_state.main_results = pd.DataFrame()
                    st.session_state.main_results_total_count = 0
                    st.session_state.main_results_mode = "chat"
                    st.session_state.filters_applied = True
                    turn.text = (
                        f"உங்கள் தேடலுக்கு தேதி உள்ள ஏலம் கிடைக்கவில்லை. {len(undated)} பதிவுகள் உள்ளன; ஆனால் அவற்றில் ஏலத் தேதி குறிப்பிடப்படவில்லை, மேலும் ஆதாரம் அவற்றை கிடைக்காது எனக் குறிக்கிறது. செயலில் உள்ள ஏலமாகக் காட்டமாட்டேன். அந்தப் பதிவுகளையும் மூல இணைப்புகளையும் காட்டலாமா? நீங்கள் நேரடியாகத் தற்போதைய விவரங்களைச் சரிபார்க்கலாம்."
                        if language == "தமிழ்" else
                        f"I couldn’t find an auction record with a listed date for your search. I found {len(undated)} matching saved records, but they have no auction date and the source marks them unavailable, so I can’t present them as active auctions. Would you like me to show them with source links so you can check the portal directly?"
                    )
            property_tool = next((result for result in turn.tool_results if result.display_kind == "properties"), None)
            if property_tool:
                api_intent = parse_request(text, properties)
                previous = st.session_state.get("search_context", {})
                for key in ("location", "max_budget", "min_area_sqm"):
                    if not getattr(api_intent, key) and previous.get(key):
                        setattr(api_intent, key, previous[key])
                if api_intent.bedrooms is None and previous.get("bedrooms"):
                    api_intent.bedrooms = previous["bedrooms"]
                if api_intent.property_type == "Any" and previous.get("property_type", "Any") != "Any":
                    api_intent.property_type = previous["property_type"]
                if api_intent.status == "Any" and previous.get("status", "Any") != "Any":
                    api_intent.status = previous["status"]
                queue_mira_filter_sync(api_intent)
                property_records = property_tool.data.get("records", [])
                st.session_state.main_results = pd.DataFrame(property_records[:3])
                st.session_state.last_results = pd.DataFrame(property_records[:30])
                st.session_state.main_results_total_count = int(property_tool.data.get("count", 0))
                st.session_state.main_results_mode = "chat"
                st.session_state.active_listing_view = "all"
                st.session_state.filters_applied = True
                if contact_question and property_records:
                    contact_reply = local_property_contact_reply(
                        text,
                        st.session_state.chat + [{"role": "assistant", "mode": "results", "records": property_records[:5]}],
                    )
                    if contact_reply:
                        turn.text = contact_reply
                has_unknown_area = any(
                    format_area_for_display(record) == tr("Not reported") and bool(record.get("source_url"))
                    for record in property_records[:3]
                )
                if has_unknown_area and not contact_question and not st.session_state.get("area_source_prompted"):
                    turn.text += (
                        " உங்கள் விருப்பத்துடன் பொருந்தும் சில பதிவுகளில் பரப்பளவு தெளிவான அலகுடன் குறிப்பிடப்படவில்லை. மூல இணையதளத்தில் புதுப்பிக்கப்பட்ட விவரங்களைச் சரிபார்க்க, அந்த இணைப்பை எப்படித் திறப்பது என்று வழிகாட்டலாமா?"
                        if language == "தமிழ்" else
                        " Some matching properties don’t report an area with a clear unit. Would you like me to guide you to the source portal to check the updated property details?"
                    )
                    st.session_state.pending_area_source_check = True
                    st.session_state.area_source_prompted = True
            st.session_state.chat.append({"role": "user", "content": text})
            st.session_state.chat.append({
                "role": "assistant",
                "content": turn.text,
                "mode": "agent",
                "tool_results": [{"kind": result.display_kind, "name": result.name, "data": result.data} for result in turn.tool_results],
                "pending_followup": turn.pending_followup,
            })
            st.session_state.agent_history.extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": turn.text},
            ])
            st.session_state.agent_history = st.session_state.agent_history[-24:]
            return
        logging.warning("Mira provider fallback: provider=%s category=%s", AI_PROVIDER, turn.error)
        st.session_state.agent_error = "சிறிது தாமதம் ஏற்பட்டுள்ளது; நீங்கள் சொன்ன விருப்பங்களுடன் தொடர்ந்து உதவுகிறேன்." if language == "தமிழ்" else "Thanks for your patience—I’ll keep helping with the details you’ve already shared."
        if turn.error == "openai_rate_limit":
            st.session_state.agent_rate_limited = True
            st.session_state.agent_retry_at = datetime.now(INDIA_TZ).timestamp() + max(1, turn.retry_after_seconds)
            st.session_state.offer_delay_callback = turn.retry_after_seconds > 30
        elif turn.error == "openai_timeout":
            st.session_state.offer_delay_callback = True
    if not explicit_search and not AI_API_KEY and conversation["memory"].get("response_language") in {"Tamil", "Tanglish"}:
        st.session_state.chat.extend([{"role": "user", "content": text},
            {"role": "assistant", "content": unavailable_reply(conversation["memory"]), "mode": "local_support"}])
        return
    if not explicit_search and st.session_state.get("agent_rate_limited"):
        st.session_state.chat.extend([{"role": "user", "content": text},
            {"role": "assistant", "content": unavailable_reply(conversation["memory"]), "mode": "local_support"}])
        return
    st.session_state.chat.append({"role": "user", "content": text})
    # Keep the local fallback conversational too: greetings and incomplete
    # preferences should lead to a reply or one question, never a broad listing dump.
    intent = parse_request(text, properties)
    previous = st.session_state.get("search_context", {})
    for key in ("location", "max_budget", "min_area_sqm"):
        if not getattr(intent, key) and previous.get(key):
            setattr(intent, key, previous[key])
    if intent.bedrooms is None and previous.get("bedrooms"):
        intent.bedrooms = previous["bedrooms"]
    if intent.property_type == "Any" and previous.get("property_type", "Any") != "Any":
        intent.property_type = previous["property_type"]
    if intent.status == "Any" and previous.get("status", "Any") != "Any":
        intent.status = previous["status"]
    st.session_state.search_context = intent.__dict__.copy()
    no_more_details = bool(re.search(
        r"\b(?:nothing else|nothing more|that(?:'|’)s all|that is all|all done|that(?:'|’)s enough|no thanks|no more)\b|வேறொன்றுமில்லை|அவ்வளவுதான்",
        normalized,
    ))
    property_topic = bool(re.search(
        r"\b(?:property|properties|house|home|plot|land|flat|apartment|place|[1-9]\s*[- ]?bhk)\b|சொத்து|வீடு|மனை|நிலம்",
        normalized,
    ))
    property_inquiry = property_topic and not asks_a_question and bool(re.search(
        r"\b(?:want|need|looking for|look for|interested in|planning to buy|hope to find|would like|buy|purchase|how about|what about|tell me about|help me with)\b|வேண்டும்|தேடுகிறேன்|தேட",
        normalized,
    ))
    inquiry_active = bool(property_inquiry)
    area_match = re.search(
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s*(?P<unit>square feet|square foot|square metres?|square meters?|sq\.?\s*ft|sq\.?\s*m|sqm|sqft|cents?|acres?|grounds?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if area_match and intent.area_question:
        amount = float(area_match.group("amount").replace(",", ""))
        raw_unit = area_match.group("unit").lower().replace(".", "").strip()
        unit = "sq ft" if raw_unit in ("square feet", "square foot", "sq ft", "sqft") else "sq m" if raw_unit in ("square metre", "square metres", "square meter", "square meters", "sq m", "sqm") else "cent" if raw_unit.startswith("cent") else "acre" if raw_unit.startswith("acre") else "ground"
        converted = convert_area(amount, unit)
        reply = (f"{amount:,.2f} {unit} என்பது சுமார் **{converted['sq_m']:,.2f} m²** அல்லது **{converted['sq_ft']:,.2f} sq ft**. இது சுமார் {converted['cents']:,.2f} சென்ட்."
                 if language == "தமிழ்" else f"{amount:,.2f} {unit} is about **{converted['sq_m']:,.2f} m²** or **{converted['sq_ft']:,.2f} sq ft**. That’s roughly {converted['cents']:,.2f} cents.")
        st.session_state.chat.append({"role": "assistant", "content": reply, "mode": "welcome"})
        return
    if intent.area_question and not area_match and "price" not in text.lower() and "rate" not in text.lower():
        prompt_reply = "எந்த அளவையும் அலகையும் மாற்ற வேண்டும்? உதாரணம்: “1,200 sq ft-ஐ சதுர மீட்டராக மாற்று.”" if language == "தமிழ்" else "Sure—what size and unit should I convert? For example, try “1,200 sq ft to square metres.”"
        st.session_state.chat.append({"role": "assistant", "content": prompt_reply, "mode": "welcome"})
        return
    if intent.help_with_loan and not explicit_search:
        reply = "அதிகாரப்பூர்வ வங்கி தகவல்களை காட்டுகிறேன். கடன் தகுதி மற்றும் மனைக்கான நிதி வங்கிக்கு வங்கி மாறும்; வங்கியிடம் நேரடியாக உறுதிப்படுத்தவும். Home loans பகுதியில் EMI மதிப்பீடும் அதிகாரப்பூர்வ இணைப்புகளும் உள்ளன." if language == "தமிழ்" else "I can point you to official bank pages. Loan eligibility and plot-only finance vary by lender, so please confirm directly with the bank. Open the Home loans tab for official links and an EMI estimate."
        st.session_state.chat.append({"role": "assistant", "content": reply, "mode": "loans"})
        return
    if no_more_details:
        st.session_state.property_inquiry_active = False
        st.session_state.soft_search_preferences = []
    elif explicit_search or inquiry_active:
        requests_broad_results = bool(re.search(
            r"\b(?:show me what you have|show me what(?:'s| is) available|show me options|what do you have|show results)\b",
            normalized,
        ))
        has_search_criteria = bool(
            intent.location or intent.property_type != "Any" or intent.bedrooms
            or intent.status != "Any" or intent.max_budget is not None or intent.min_area_sqm is not None
        )
        needs_one_more_detail = (
            (not explicit_search and not intent.location)
            or (explicit_search and not requests_broad_results and not has_search_criteria)
        )
        if needs_one_more_detail and intent.status != "Auction":
            st.session_state.property_inquiry_active = True
            st.session_state.awaiting_search_preferences = True
            if not intent.location:
                known_preferences = []
                if intent.property_type != "Any":
                    known_preferences.append("அடுக்குமாடி வீடு" if language == "தமிழ்" and intent.property_type == "Flat" else "வீடு" if language == "தமிழ்" else f"{intent.property_type.lower()}s")
                if intent.bedrooms:
                    known_preferences.append(f"{intent.bedrooms} BHK")
                if intent.max_budget is not None:
                    known_preferences.append(f"₹{intent.max_budget / 100_000:g} லட்சம் பட்ஜெட்" if language == "தமிழ்" else f"a ₹{intent.max_budget / 100_000:g} lakh budget")
                summary = (f"{', '.join(known_preferences)}-ஐ மனதில் வைத்துக்கொள்கிறேன். " if language == "தமிழ்" and known_preferences else f"I’ve noted {', '.join(known_preferences)}. " if known_preferences else "")
                question = "எந்த ஊர் அல்லது பகுதியில் பார்க்கலாம்?" if language == "தமிழ்" else "Which city or area would you like me to check?"
                reply = summary + question
            else:
                reply = ("எந்த வகை சொத்து உங்களுக்கு பொருந்தும்—மனை, வீடு அல்லது அடுக்குமாடி குடியிருப்பா?" if language == "தமிழ்" else "What type of place would suit you—plot, house, or flat?")
            st.session_state.chat.append({"role": "assistant", "content": reply, "mode": "welcome"})
            return
        # Occasionally invite a preference before recommendations. Keep this to
        # one checkpoint per conversation, and honor a clear user request to proceed.
        should_check_preferences = (
            explicit_search and not awaiting_preferences
            and not st.session_state.get("preference_check_done")
            and any(term in normalized for term in ("recommend", "suggest", "best option", "suggestions"))
            and bool(intent.location) and intent.property_type != "Any"
            and not intent.max_budget
        )
        if should_check_preferences:
            st.session_state.awaiting_search_preferences = True
            st.session_state.preference_check_done = True
            prompt = ("பரிந்துரைகளைத் தேடுவதற்கு முன், ஏதேனும் விருப்பம் அல்லது தவிர்க்க வேண்டிய விஷயம் உள்ளதா—உதாரணமாக பட்ஜெட் அல்லது முக்கிய அம்சம்? நீங்கள் பகிர்ந்த தகவல்களுடன் இப்போதே தேடவும் முடியும்."
                      if language == "தமிழ்" else
                      "Before I look for options, is there anything you’d like me to prioritize or avoid—such as a budget or must-have feature? I can also search with what you’ve shared so far.")
            st.session_state.chat.append({"role": "assistant", "content": prompt, "mode": "welcome"})
            return
        if awaiting_preferences:
            st.session_state.awaiting_search_preferences = False
        st.session_state.property_inquiry_active = False
    if not explicit_search:
        if no_more_details:
            st.session_state.property_inquiry_active = False
            reply = ("சரி. இங்கே நிறுத்திக்கொள்ளலாம். மீண்டும் பேச விரும்பும்போது நான் உதவ இங்கே இருப்பேன்."
                     if language == "தமிழ்" else "Of course. We can leave it here. Thanks for chatting; I’m here if you need help another time.")
            st.session_state.chat.append({"role": "assistant", "content": reply, "mode": "welcome"})
            return
        if any(term in normalized for term in ("worried", "concerned", "nervous", "overwhelmed", "கவலை", "பயம்")):
            reply = ("உங்கள் கவலையைப் புரிந்துகொள்கிறேன். அவசரமில்லை; நீங்கள் விரும்பும் வேகத்தில் ஒவ்வொன்றாகப் பார்ப்போம். முதலில் எது அதிகம் கவலை தருகிறது?"
                     if language == "தமிழ்" else "That sounds like a lot to weigh. There’s no rush; we can take it one step at a time. What feels most concerning right now?")
        elif intent.location and intent.property_type == "Any" and not intent.max_budget:
            reply = (f"{intent.location} என்பதை மனதில் வைத்துக்கொள்கிறேன். ஏதேனும் சொத்து வகை அல்லது பட்ஜெட்டையும் சேர்க்க விரும்புகிறீர்களா?"
                     if language == "தமிழ்" else f"I’ll keep {intent.location} in mind. Is there a property type or budget you’d like me to consider too?")
        elif intent.max_budget and not intent.location and intent.property_type == "Any":
            reply = (f"₹{intent.max_budget / 100_000:g} லட்சம் பட்ஜெட்டை மனதில் வைத்துக்கொள்கிறேன். எந்தப் பகுதி அல்லது சொத்து வகையில் கவனம் செலுத்தலாம்?"
                     if language == "தமிழ்" else f"I’ll keep the ₹{intent.max_budget / 100_000:g} lakh budget in mind. Which area or property type should I focus on?")
        elif intent.property_type != "Any" and not intent.location:
            reply = (f"{intent.property_type} வகையை மனதில் வைத்துக்கொள்கிறேன். எந்தப் பகுதி அல்லது பட்ஜெட்டையும் சேர்க்க விரும்புகிறீர்களா?"
                     if language == "தமிழ்" else f"I’ll keep {intent.property_type.lower()}s in mind. Is there an area or budget you’d like me to consider too?")
        elif intent.location or intent.property_type != "Any" or intent.max_budget:
            criteria = []
            if intent.location:
                criteria.append(intent.location)
            if intent.property_type != "Any":
                criteria.append(intent.property_type.lower())
            if intent.max_budget:
                criteria.append(f"₹{intent.max_budget / 100_000:g} lakh budget")
            summary = " and ".join(criteria)
            reply = (f"{summary} என்பதை மனதில் வைத்துக்கொள்கிறேன். தேட வேண்டுமா, அல்லது இன்னும் ஏதாவது விவரத்தைச் சேர்க்க விரும்புகிறீர்களா?"
                     if language == "தமிழ்" else f"I’ll keep {summary} in mind. Would you like me to search now, or add anything else first?")
        else:
            reply = ("நான் இங்கே இருக்கிறேன். நீங்கள் விரும்பும் விஷயத்தை உங்கள் வேகத்தில் சொல்லுங்கள்."
                     if language == "தமிழ்" else "I’m here to help at your pace. Share whatever you’d like, whenever you’re ready.")
        st.session_state.chat.append({"role": "assistant", "content": reply, "mode": "welcome"})
        return
    result = apply_filters(intent=intent)
    if result.empty and intent.status == "Auction":
        undated = search_properties(
            properties,
            location=intent.location,
            property_type=intent.property_type,
            bedrooms=intent.bedrooms,
            status=["Auction date not listed"],
            max_budget=intent.max_budget,
            min_area_sqm=intent.min_area_sqm,
        )
        if not undated.empty:
            st.session_state.pending_undated_auction_records = undated.copy()
            st.session_state.main_results = pd.DataFrame()
            st.session_state.main_results_total_count = 0
            st.session_state.main_results_mode = "chat"
            st.session_state.filters_applied = True
            if language == "தமிழ்":
                reply = (
                    f"உங்கள் தேடலுக்கு தேதி உள்ள ஏலம் கிடைக்கவில்லை. அதே விருப்பங்களுக்கு {len(undated)} பதிவுகள் உள்ளன; "
                    "ஆனால் அவற்றில் ஏலத் தேதி குறிப்பிடப்படவில்லை, மேலும் ஆதாரம் அவற்றை கிடைக்காது எனக் குறிக்கிறது. "
                    "செயலில் உள்ள ஏலமாகக் காட்டமாட்டேன். அந்தப் பதிவுகளையும் மூல இணைப்புகளையும் காட்டலாமா? "
                    "நீங்கள் நேரடியாகத் தற்போதைய விவரங்களைச் சரிபார்க்கலாம்."
                )
            else:
                reply = (
                    f"I couldn’t find an auction record with a listed date for your search. I did find {len(undated)} matching saved records, "
                    "but they have no auction date and the source marks them unavailable, so I can’t present them as active auctions. "
                    "Would you like me to show those records with source links so you can check the portal directly?"
                )
            st.session_state.chat.append({
                "role": "assistant",
                "content": reply,
                "mode": "welcome",
            })
            return
    queue_mira_filter_sync(intent)
    result = prepare_inventory(result, st.session_state.get("buyer_memory", {}))
    ranked = rank_matches(result, location=intent.location, max_budget=intent.max_budget)
    if "_preference_score" in ranked:
        ranked = ranked.sort_values("_preference_score", ascending=False, kind="stable")
    sort_col = "price_inr" if intent.sort == "price" else "area_sqm" if intent.sort == "area" else None
    if sort_col:
        ranked = ranked.sort_values(sort_col, ascending=intent.sort == "price", na_position="last")
    st.session_state.last_results = ranked.head(30)
    st.session_state.main_results = ranked.head(3).copy()
    st.session_state.main_results_total_count = len(result)
    st.session_state.main_results_mode = "chat"
    st.session_state.active_listing_view = "all"
    st.session_state.filters_applied = True
    project_reference_only = (
        len(result) > 0
        and "listing_status" in result.columns
        and result["listing_status"].eq("Project reference").all()
    )
    reply = friendly_reply(len(result), intent)
    unverified_preferences = st.session_state.get("soft_search_preferences", [])
    shares_search_frustration = bool(re.search(
        r"\b(?:disappoint(?:ed|ing)?|discourag(?:ed|ing)?|frustrat(?:ed|ing)?|overwhelmed|confus(?:ed|ing)|tired|worn out|fed up|useless|not helping|waste of time|going in circles|furious|angry|unacceptable|ridiculous|hard to reach|noisy|too expensive|over my budget|out of budget|too far|long commute|not close enough)\b|ஏமாற்றம்|திருப்தி இல்லை|பயனில்லை|உதவவில்லை|கோபமாக",
        normalized,
    ))
    if unverified_preferences and language != "தமிழ்":
        where = f" around {intent.location}" if intent.location else ""
        kind = f" {intent.property_type.lower()}" if intent.property_type != "Any" else " property"
        limit_phrases = {
            "balcony details": "whether it has a balcony",
            "garden details": "whether it has a garden",
            "pool details": "whether it has a pool",
            "bus or transit access": "how close it is to a bus stop or public transit",
            "a quieter area": "whether the area is quiet",
        }
        limitations = " or ".join(limit_phrases[label] for label in unverified_preferences)
        if re.search(r"\b(?:noisy|hard to reach|harder to get to)\b", normalized):
            empathy = "I’m sorry the places you’ve seen have been noisy and hard to get to. "
        elif re.search(r"\b(?:worn out|tired|overwhelmed|fed up)\b", normalized):
            empathy = "That sounds draining. I’ll keep this simple. "
        elif re.search(r"\b(?:too expensive|over my budget|out of budget)\b", normalized):
            empathy = "I’m sorry those options were above your budget. "
        elif re.search(r"\b(?:too far|long commute|not close enough|hard to reach)\b", normalized):
            empathy = "I’m sorry those locations aren’t convenient for you. "
        elif shares_search_frustration:
            empathy = "I’m sorry the search has been discouraging. "
        else:
            empathy = ""
        if project_reference_only:
            where = f" around {intent.location}" if intent.location else ""
            kind = intent.property_type.lower() if intent.property_type != "Any" else "property"
            reply = (
                f"{empathy}I found a {kind} project reference{where}, but it doesn’t confirm that a unit is available. "
                f"It also doesn’t say {limitations}, so I can’t check that part. "
                "Would you like to try a nearby area, or check this project with its source?"
            )
        elif len(result):
            record_subject = "this listing" if len(result) == 1 else "these listings"
            record_verb = "doesn’t" if len(result) == 1 else "don’t"
            reply = (
                f"{empathy}I found {len(result)}{kind} option{'s' if len(result) != 1 else ''}{where}. "
                f"{record_subject.capitalize()} {record_verb} say {limitations}, so I can’t confirm that part. "
                "Would you like to try a nearby area, or keep this area and check the location before deciding?"
            )
        else:
            reply = (
                f"{empathy}I couldn’t find a matching option{where}. The listings I have don’t say {limitations}, "
                "so I can’t check those details. Would you like to try a nearby area or adjust the budget?"
            )
    elif shares_search_frustration and language != "தமிழ்":
        reply = f"I’m sorry this has been frustrating. {reply}"
    if language == "தமிழ்":
        if shares_search_frustration:
            reply = (f"இந்த முடிவுகள் உங்கள் எதிர்பார்ப்புக்கு பொருந்தவில்லை என்பதற்கு மன்னிக்கவும். {len(result)} பதிவுகள் கிடைத்துள்ளன; அடுத்ததாக முதலில் எதை மாற்றிப் பார்க்கலாம்—பகுதியா, பட்ஜெட்டா, சொத்து வகையா?"
                     if len(result) else "உங்களுக்கு ஏற்ற பதிவு கிடைக்காதது வருத்தமாக உள்ளது; மன்னிக்கவும். முதலில் எதை மாற்றிப் பார்க்கலாம்—பகுதியா, பட்ஜெட்டா, சொத்து வகையா?")
        else:
            reply = (f"உங்கள் தேடலுக்கு {len(result)} பொருத்தமான விருப்பங்கள் உள்ளன. ஒன்றைப் பற்றி மேலும் கேட்க விரும்புகிறீர்களா, அல்லது ஏதாவது மாற்றலாமா?"
                     if len(result) else "மன்னிக்கவும், என்னிடம் உள்ள பட்டியலில் பொருத்தமான இடம் கிடைக்கவில்லை. வேறு பகுதி அல்லது பட்ஜெட்டில் பார்க்கலாமா?")
    if st.session_state.get("land_approval_caution_pending"):
        approval_note = (
            "குறிப்பு: குறைந்த விலை என்பதற்காக அனுமதி விவரங்களைப் புறக்கணிக்க வேண்டாம். பதிவில் அனுமதி குறிப்பிடப்படவில்லை என்றால் அது அங்கீகரிக்கப்பட்டது என்று அர்த்தமல்ல; பணம் செலுத்துவதற்கு முன் அதிகாரப்பூர்வ பதிவிலும் வழக்கறிஞரிடமும் சரிபார்க்கவும்."
            if language == "தமிழ்" else
            "One important note: a low price doesn’t make approval checks optional. If approval isn’t stated in a record, that does not mean the plot is approved; verify it with official records and your lawyer before paying."
        )
        shown = ranked.head(3)
        has_missing_exact_price = bool(
            len(shown)
            and ("price_inr" not in shown.columns or pd.to_numeric(shown["price_inr"], errors="coerce").isna().any())
        )
        if has_missing_exact_price:
            price_note = (
                "காட்டப்படும் பதிவுகளில் சிலவற்றுக்கு சரியான விலை இல்லை; அதனால் எது மலிவு என்று உறுதியாகக் கூற முடியாது."
                if language == "தமிழ்" else
                "Some of the shown records have no exact asking price, so I can’t reliably tell which is cheapest."
            )
            approval_note = f"{price_note} {approval_note}"
        reply = f"{reply} {approval_note}"
        st.session_state.land_approval_caution_pending = False
    # A matching record may still omit an area unit/value. Offer a calm,
    # permission-based route to the publisher's source for updated details.
    shown_records = ranked.head(3).to_dict("records")
    if st.session_state.get("buyer_memory", {}).get("preferences"):
        reply = grounded_search_reply({"records": shown_records}, st.session_state.buyer_memory, language == "தமிழ்")
    missing_area_with_source = any(
        format_area_for_display(record) == tr("Not reported") and bool(record.get("source_url"))
        for record in shown_records
    )
    if missing_area_with_source and not contact_question and not st.session_state.get("area_source_prompted"):
        source_prompt = (
            "உங்கள் விருப்பத்துடன் பொருந்தும் சில பதிவுகளில் பரப்பளவு தெளிவான அலகுடன் குறிப்பிடப்படவில்லை. மூல இணையதளத்தில் புதுப்பிக்கப்பட்ட விவரங்களைச் சரிபார்க்க, அந்த இணைப்பை எப்படித் திறப்பது என்று வழிகாட்டலாமா?"
            if language == "தமிழ்" else
            "Some matching properties don’t report an area with a clear unit. Would you like me to guide you to the source portal to check the updated property details?"
        )
        reply = f"{reply} {source_prompt}"
        st.session_state.pending_area_source_check = True
        st.session_state.area_source_prompted = True
    if contact_question and len(result):
        contact_reply = local_property_contact_reply(
            text,
            st.session_state.chat + [{"role": "assistant", "mode": "results", "records": ranked.head(5).to_dict("records")}],
        )
        if contact_reply:
            reply = contact_reply
    st.session_state.chat.append({"role": "assistant", "content": reply, "mode": "results", "count": len(result), "records": ranked.head(5).to_dict("records"), "intent": intent.__dict__})


def inquiry_analytics_fields(text: str, chat: list[dict]) -> dict[str, str]:
    """Add cautious, transparent conversation signals for owner reporting."""
    user_messages = [str(message.get("content", "")) for message in chat if message.get("role") == "user"]
    context = " ".join(user_messages[-12:])
    normalized = context.casefold()
    current = text.casefold()
    topic = "General"
    if re.search(r"\b(sell|selling|seller|list my|listing my|sale of my)\b", normalized):
        topic = "Seller"
    elif re.search(r"\b(buy|buying|buyer|looking for|search for)\b", normalized):
        topic = "Buyer search"
    elif re.search(r"\b(auction|baanknet)\b", normalized):
        topic = "Auction"
    elif re.search(r"\b(loan|emi|mortgage)\b", normalized):
        topic = "Home loan"
    if re.search(r"\b(stress(?:ed|ful)?|disappoint(?:ed|ing)|frustrat(?:ed|ing)|angry|upset|worried|exhaust(?:ed|ing))\b", normalized):
        tone = "Concern / dissatisfaction mentioned"
    elif re.search(r"\b(thank you|thanks|great|happy|satisfied)\b", normalized):
        tone = "Positive language mentioned"
    else:
        tone = "No clear tone signal"
    followup_requested = bool(re.search(r"\b(follow.?up|call me|contact me|connect me|advisor|human|site visit|remind me)\b", normalized))
    handoff_requested = bool(re.search(r"\b(connect me to (?:a )?human|talk to (?:a )?human|human advisor|real person|actual person)\b", normalized))
    listing_status_asked = bool(re.search(r"\b(listing|property)\b.{0,45}\b(status|live|published|posted)\b|\b(status|live|published|posted)\b.{0,45}\b(listing|property)\b", normalized))
    sale_outcome_mentioned = bool(re.search(r"\b(sold|sale completed|sale fell through|not sold|buyer backed out)\b", normalized))
    explicit_positive_feedback = bool(re.search(r"\b(this helped|that helped|very helpful|exactly what i needed|i am satisfied|i'm satisfied|that works for me|good answer)\b", current))
    explicit_negative_feedback = bool(re.search(r"\b(not helpful|didn.t help|did not answer|still dissatisfied|not satisfied|useless|wrong answer|disappointed|frustrated with (?:this|the answer|the response))\b", current))
    if explicit_negative_feedback:
        satisfaction = "Dissatisfied feedback mentioned"
    elif explicit_positive_feedback:
        satisfaction = "Positive feedback mentioned"
    else:
        satisfaction = "Not stated"
    if re.search(r"\bnot interested in (?:this|the property|buying|selling|listing|a home|a flat|a house)\b", current):
        interest = "Not interested signal"
    elif re.search(r"\b(interested in (?:buying|selling|this property|the property|a home|a flat|a house)|looking (?:to buy|to sell|for (?:a )?(?:property|home|house|flat|plot|apartment))|want to (?:buy|purchase|sell|list|view|visit|book)|need (?:a )?(?:property|home|house|flat|plot|apartment)|schedule (?:a )?(?:visit|viewing))\b", current):
        interest = "Interested signal"
    else:
        interest = "Not stated"
    currency_amount = re.search(r"(?:₹|\brs\.?\s*)\s*\d[\d,.]*(?:\s*(?:lakh|lakhs|lac|crore|cr|k))?|\b\d[\d,.]*\s*(?:lakh|lakhs|lac|crore|cr)\b", text, re.IGNORECASE)
    mentions_budget = bool(re.search(r"\b(budget|afford|spend|price range|within .*? lakh|under .*? lakh)\b", current) or currency_amount)
    customer_price_text = text.strip()[:1000] if currency_amount else ""
    purchase_value_text = customer_price_text if currency_amount and re.search(r"\b(buy|buying|purchase|pay|offer|worth|price|value|sell|selling|asking|looking for|need|want)\b", current) else ""
    property_types = re.findall(r"\b\d\s*[- ]?BHK\b|\b(?:flat|apartment|house|villa|plot|land)\b", text, re.IGNORECASE)
    size_match = re.search(r"\b\d[\d,.]*\s*(?:sq\.?\s*ft|sqft|square feet|sq\.?\s*m|sqm|m²|மீ²)\b", text, re.IGNORECASE)
    assistant = next((message for message in reversed(chat) if message.get("role") == "assistant"), {})
    intent = assistant.get("intent") if isinstance(assistant.get("intent"), dict) else {}
    city = str(intent.get("location") or intent.get("area") or "")
    result = {
        "Conversation topic": topic,
        "Customer tone signal": tone,
        "Follow-up requested signal": "Yes" if followup_requested else "No",
        "Human handoff requested signal": "Yes" if handoff_requested else "No",
        "Listing status asked signal": "Yes" if listing_status_asked else "No",
        "Sale outcome mentioned signal": "Yes" if sale_outcome_mentioned else "No",
        "Follow-up status (owner)": "Not updated",
        "Follow-up date (owner)": "",
        "Listing status (owner)": "Not updated",
        "Sale outcome (owner)": "Not updated",
        "Advisor notes (owner)": "",
        "Customer satisfaction signal": satisfaction,
        "Customer satisfaction (owner)": "Not recorded",
        "Customer interest signal": interest,
        "Customer interest (owner)": "Not recorded",
            "Follow-up method": st.session_state.get("followup_schedule", {}).get("method", ""),
            "Follow-up schedule status": st.session_state.get("followup_schedule", {}).get("status", ""),
            "Follow-up cadence": st.session_state.get("followup_schedule", {}).get("cadence", ""),
            "Follow-up consent timestamp (Asia/Kolkata)": st.session_state.get("followup_schedule", {}).get("consent_at", ""),
            "Next follow-up time (Asia/Kolkata)": st.session_state.get("followup_schedule", {}).get("next_at", ""),
        "Budget mentioned signal": "Yes" if mentions_budget else "No",
        "Customer budget / price stated": customer_price_text if mentions_budget else "",
        "Purchase value / offer stated": purchase_value_text,
        "Property type mentioned": ", ".join(dict.fromkeys(value.strip() for value in property_types)),
        "Location mentioned": city,
        "Preferred size stated": size_match.group(0) if size_match else "",
        "Next follow-up action (owner)": "",
        "Lead priority (owner)": "Not rated",
    "Conversation status": "Active",
    }
    return result


def capture_customer_address(text: str) -> bool:
    """Remember only an address preference the user voluntarily provides."""
    current_name = str(st.session_state.get("customer_name", "") or "")
    current_address = str(st.session_state.get("preferred_form_of_address", "") or "")
    normalized = " ".join(text.casefold().split())
    title_match = re.search(r"\b(?:call me|address me as|use|i prefer|prefer to be called)\s+(sir|ma['’]?am|madam|madame)\b|\b(?:sir|ma['’]?am|madam|madame)\s+is fine\b", text, re.IGNORECASE)
    tamil_title = re.search(r"(?:சார்|சர்|மேடம்)\s*(?:என்று|னு)?\s*(?:அழைக்கவும்|சரி|பரவாயில்லை)?", text) if language == "தமிழ்" else None
    if not title_match and st.session_state.get("awaiting_address_preference"):
        title_match = re.fullmatch(r"\s*(sir|ma['’]?am|madam|madame)[.!\s]*", text, re.IGNORECASE)
    chosen_address = ""
    if tamil_title:
        chosen_address = "Ma’am" if "மேடம்" in tamil_title.group(0) else "Sir"
    elif title_match:
        match_text = title_match.group(0).replace("’", "'").casefold()
        title = title_match.group(1) or match_text.split()[0]
        chosen_address = "Ma’am" if title.casefold() in {"ma'am", "madam", "madame"} else "Sir"
    elif re.search(r"\b(?:prefer|call me|address me as)\s+(?:by )?(?:my )?name\b", normalized):
        st.session_state.awaiting_address_preference = True

    name_match = re.search(
        r"\b(?:my name is|my name's|call me|please call me|prefer to be called|i am|i'm)\s+([^\W\d_]+(?:[ '-][^\W\d_]+){0,2})(?=$|[.,!?;]|\s+(?:and|but|please|you|call me|address me|i need|i want|i am looking)\b)",
        text,
        re.IGNORECASE,
    )
    # Accept "I'm Alex" only as a complete, standalone name answer. Treating
    # any "I am ..." sentence as a name caused emotional words like
    # "disappointed" to be saved and repeated as a salutation.
    if not name_match:
        name_match = re.fullmatch(
            r"\s*i(?:'m| am)\s+([^\W\d_]+(?:[ '-][^\W\d_]+){0,2})\s*[.!]?\s*",
            text,
            re.IGNORECASE,
        )
    if not name_match and language == "தமிழ்":
        name_match = re.search(r"(?:என் பெயர்|என்னை)\s+([\u0B80-\u0BFF]+(?:\s+[\u0B80-\u0BFF]+){0,2})", text)
    name = name_match.group(1).strip(" .,!?'\"-") if name_match else ""
    if not name and st.session_state.get("awaiting_address_preference"):
        candidate = text.strip().strip(" .,!?'\"")
        if re.fullmatch(r"[^\W\d_]+(?:[ '-][^\W\d_]+){0,2}", candidate, re.UNICODE) and candidate.casefold() not in {
            "hi", "hello", "hey", "good morning", "good afternoon", "good evening", "yes", "no", "okay", "ok", "sure", "thanks", "thank you", "thanks so much", "thank you so much", "skip", "none", "sir", "madam", "ma'am", "bye", "goodbye", "that's all", "that is all", "that's it", "that is it", "i'm done", "we're done",
        }:
            name = candidate
    if name.casefold() in {
        "looking", "searching", "interested", "here", "not", "ready", "fine", "good", "okay", "well",
        "doing well", "doing great", "a buyer", "a seller", "sir", "ma'am", "madam", "madame",
        "disappointed", "dissatisfied", "worried", "concerned", "nervous", "anxious", "scared", "afraid",
        "sad", "frustrated", "stressed", "tired", "overwhelmed", "angry", "upset", "confused", "unhappy", "sorry",
    }:
        name = ""
    if name:
        st.session_state.customer_name = name[:80]
        if not chosen_address:
            chosen_address = name[:80]
    if chosen_address:
        st.session_state.preferred_form_of_address = chosen_address
        st.session_state.awaiting_address_preference = False
    elif st.session_state.get("awaiting_address_preference"):
        st.session_state.awaiting_address_preference = False

    if re.search(r"\b(?:skip|no thanks|rather not|prefer not|don't want to say|do not want to say|no preference|keep it neutral)\b|வேண்டாம்", normalized):
        st.session_state.preferred_form_of_address = "Neutral (not specified)"
        st.session_state.awaiting_address_preference = False
    new_name = str(st.session_state.get("customer_name", "") or "") != current_name
    new_address = str(st.session_state.get("preferred_form_of_address", "") or "") != current_address
    return new_name or new_address


def is_natural_conversation_closing(text: str) -> bool:
    normalized = " ".join(text.casefold().split()).strip(" .,!?'\"-")
    return bool(re.fullmatch(
        r"(?:(?:thanks|thank you|thanks so much|thank you so much)(?:[, ]+(?:that's all|that is all|that's it|that is it|bye|goodbye))?|(?:that's all|that is all|that's it|that is it|i'm done|we're done|talk to you later|see you later|bye|goodbye))(?: for now)?",
        normalized,
    ))


def conversation_transcript(chat: list[dict]) -> str:
    return json.dumps(
        [{"role": message.get("role"), "content": message.get("content", "")} for message in chat if message.get("role") in ("user", "assistant")],
        ensure_ascii=False,
    )


def respond(text: str):
    """Answer a user turn, then save a private owner-only inquiry record."""
    # A returning customer is already back in contact; stop any pending
    # proactive sequence unless they opt into a new one from Follow-ups.
    if st.session_state.get("user_id"):
        cancelled = cancel_user_followups(str(st.session_state.user_id))
        if cancelled:
            followup_state = dict(st.session_state.get("followup_schedule", {}))
            followup_state.update({"status": "Stopped after user returned", "next_at": ""})
            st.session_state.followup_schedule = followup_state
            active_conversation = str(st.session_state.get("inquiry_conversation_id") or "")
            if active_conversation:
                update_conversation_fields(active_conversation, {
                    "Follow-up schedule status": followup_state["status"],
                    "Next follow-up time (Asia/Kolkata)": "",
                })
    chat = st.session_state.chat
    previous_count = len(chat)
    newly_set_address = capture_customer_address(text)
    conversation_id = st.session_state.setdefault("inquiry_conversation_id", str(uuid4()))
    user_id = st.session_state.user_id
    timestamp = datetime.now(INDIA_TZ)
    inquiry_id = f"NMI-{timestamp:%Y%m%d}-{uuid4().hex[:12].upper()}"
    try:
        _respond_without_logging(text)
    finally:
        new_messages = chat[previous_count:]
        assistant_message = next(
            (message for message in reversed(new_messages) if message.get("role") == "assistant"),
            None,
        )
        response = assistant_message.get("content", "") if assistant_message else "No assistant response was captured."
        if assistant_message is not None:
            if is_natural_conversation_closing(text) and not st.session_state.get("conversation_closed"):
                closing_question = (
                    "இந்த இடத்தில் உரையாடலை முடிக்கலாமா? கீழே உள்ள **End chat** என்பதைத் தேர்ந்தெடுக்கலாம்; இன்னும் உதவி வேண்டுமெனில் தொடர்ந்து கேளுங்கள்."
                    if language == "தமிழ்" else
                    "Would you like to end our chat here? Choose **End chat** below, or keep going if there’s anything else you need."
                )
                assistant_message["content"] = assistant_message.get("content", "").rstrip() + "\n\n" + closing_question
                st.session_state.end_chat_confirmation_pending = True
            stored_address = str(st.session_state.get("preferred_form_of_address", "") or "").strip()
            preferred_address = "" if stored_address.casefold().startswith("neutral") else stored_address
            if newly_set_address and assistant_message.get("mode") != "agent":
                if not preferred_address:
                    acknowledgment = "நன்றி, நடுநிலையாகவே பேசுகிறேன். " if language == "தமிழ்" else "Thanks for letting me know. I’ll keep things neutral. "
                elif language == "தமிழ்" and preferred_address in {"Sir", "Ma’am"}:
                    acknowledgment = f"சரி, {preferred_address} என்று அழைக்கிறேன். "
                elif language == "தமிழ்":
                    acknowledgment = f"நன்றி, {preferred_address}. அப்படியே அழைக்கிறேன். "
                elif preferred_address in {"Sir", "Ma’am"}:
                    acknowledgment = f"Certainly, {preferred_address}. I’ll address you that way. "
                else:
                    acknowledgment = f"Thanks, {preferred_address} — I’ll use that. "
                assistant_message["content"] = acknowledgment + assistant_message.get("content", "")
            elif preferred_address and sum(message.get("role") == "user" for message in chat) % 3 == 0:
                existing = assistant_message.get("content", "").lstrip().casefold()
                if not existing.startswith(preferred_address.casefold() + ","):
                    assistant_message["content"] = f"{preferred_address}, {assistant_message.get('content', '')}"
            response = assistant_message["content"]
            assistant_message["inquiry_id"] = inquiry_id
        transcript = [
            {"role": message.get("role"), "content": message.get("content", "")}
            for message in chat[-20:]
            if message.get("role") in ("user", "assistant")
        ]
        result_details = {}
        if assistant_message:
            result_details = assistant_message.get("records") or assistant_message.get("tool_results") or []
        record = {
            "Inquiry ID": inquiry_id,
            "Conversation ID": conversation_id,
            "Timestamp (Asia/Kolkata)": timestamp.isoformat(timespec="seconds"),
            "Language": "Tamil" if language == "தமிழ்" else "English",
            "User inquiry": text,
            "Assistant response": response,
            "Response type": assistant_message.get("mode", "unknown") if assistant_message else "unknown",
            "Matching records": assistant_message.get("count", "") if assistant_message else "",
            "Search criteria": json.dumps(assistant_message.get("intent", {}), ensure_ascii=False, default=str) if assistant_message else "{}",
            "Property details / tool results": json.dumps(result_details, ensure_ascii=False, default=str),
            "Recent conversation context": json.dumps(transcript, ensure_ascii=False, default=str),
            "User ID": user_id,
            "Customer name": st.session_state.get("customer_name", ""),
            "Preferred form of address": st.session_state.get("preferred_form_of_address", ""),
            "Details shared by customer": "\n".join(str(message.get("content", "")) for message in chat if message.get("role") == "user"),
            "Conversation status": "Ended" if st.session_state.get("conversation_closed") else "Active",
            "Chat ended at (Asia/Kolkata)": st.session_state.get("conversation_ended_at", ""),
            "Conversation close reason": st.session_state.get("conversation_close_reason", ""),
            "Final conversation transcript": conversation_transcript(chat) if st.session_state.get("conversation_closed") else "",
        }
        record.update(inquiry_analytics_fields(text, chat))
        record["Conversation status"] = "Ended" if st.session_state.get("conversation_closed") else "Active"
        callback_request = st.session_state.get("advisor_request", {})
        if assistant_message and assistant_message.get("mode") == "callback_request_confirmed":
            record.update({"Advisor callback status": "Awaiting owner review", "Advisor callback method": callback_request.get("method", ""),
                "Advisor callback contact": callback_request.get("contact", ""), "Advisor callback preferred time": callback_request.get("preferred_time", ""),
                "Advisor callback consent timestamp": timestamp.isoformat(timespec="seconds")})
        try:
            append_inquiry(record)
            if callback_request.get("stage") == "confirmed":
                st.session_state.advisor_request = {}
        except Exception:
            logging.exception("Could not save inquiry %s to the private workbook", inquiry_id)
            st.session_state.inquiry_log_error = "I couldn’t save this turn to the private chat record. Please try again before relying on the saved history."
            if assistant_message and assistant_message.get("mode") == "callback_request_confirmed":
                assistant_message["content"] = "I couldn’t save your callback request. Please try again; no call is arranged."
                st.session_state.advisor_request["stage"] = "confirm"
        if st.session_state.get("conversation_closed"):
            try:
                update_conversation_fields(conversation_id, {
                    "Conversation status": "Ended",
                    "Chat ended at (Asia/Kolkata)": st.session_state.get("conversation_ended_at", ""),
                    "Conversation close reason": st.session_state.get("conversation_close_reason", ""),
                    "Final conversation transcript": conversation_transcript(chat),
                })
            except Exception:
                logging.exception("Could not update conversation completion for %s", conversation_id)
            st.session_state.chat = []
            st.session_state.agent_history = []
            st.session_state.show_full_chat_history = False


def close_conversation_from_button() -> None:
    """Close the active conversation and mark every saved turn as complete."""
    if st.session_state.get("conversation_closed"):
        return
    now = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
    st.session_state.conversation_closed = True
    st.session_state.end_chat_confirmation_pending = False
    st.session_state.conversation_close_reason = "User selected End chat"
    st.session_state.conversation_ended_at = now
    address = str(st.session_state.get("preferred_form_of_address", "") or "").strip()
    salutation = "உரையாடலை முடித்துவிட்டேன்" if language == "தமிழ்" else "I’ve ended our chat"
    if address and not address.casefold().startswith("neutral"):
        salutation = f"{address}, {salutation}"
    final_reply = (
        f"{salutation}; உரையாடல் விவரங்கள் டாஷ்போர்டிலும் Excel பதிவிலும் சேமிக்கப்பட்டுள்ளன. மீண்டும் உதவி தேவைப்பட்டால் புதிய உரையாடலைத் தொடங்கலாம்."
        if language == "தமிழ்" else
        f"{salutation}. The conversation details have been saved to a private chat record. Start a new conversation whenever you need help again."
    )
    st.session_state.chat.append({"role": "assistant", "content": final_reply, "mode": "conversation_end"})
    conversation_id = str(st.session_state.get("inquiry_conversation_id") or "")
    if conversation_id:
        try:
            update_conversation_fields(conversation_id, {
                "Conversation status": "Ended",
                "Chat ended at (Asia/Kolkata)": now,
                "Conversation close reason": st.session_state.conversation_close_reason,
                "Final conversation transcript": conversation_transcript(st.session_state.chat),
            })
        except Exception:
            logging.exception("Could not save the end-of-chat status for %s", conversation_id)
        st.session_state.inquiry_log_error = "The chat ended, but its completion status could not be saved. Please try again before relying on the saved history."


    st.session_state.chat = []
    st.session_state.agent_history = []
    st.session_state.show_full_chat_history = False


def start_new_conversation() -> None:
    """Start a clean transcript while retaining this browser user's identity."""
    address = str(st.session_state.get("preferred_form_of_address", "") or "").strip()
    if address and address.casefold().startswith("neutral"):
        greeting = "Hi, welcome back to Namma Illam! I’m Mira, your AI guide. We can continue at your pace—what’s on your mind?"
    elif address:
        greeting = f"Hi, welcome back to Namma Illam! I’m Mira, your AI guide. I’ll address you as {address}. What would be helpful today?"
    else:
        greeting = "Hi, welcome to Namma Illam! I’m Mira, your AI guide. What should I call you? Your name, Sir or Ma’am, or I can keep it neutral—whichever you prefer. You can skip this and tell me what’s on your mind whenever you’re ready."
    if language == "தமிழ்":
        greeting = "மீண்டும் வணக்கம்! நான் Mira, உங்கள் AI வழிகாட்டி. உங்கள் வேகத்தில் தொடரலாம்—இன்று எதில் உதவலாம்?" if address else "வணக்கம்! நான் Mira, உங்கள் AI வழிகாட்டி. உங்களை என்ன சொல்லி அழைக்கலாம்? உங்கள் பெயரா, Sir/Ma’am என்றா, அல்லது நடுநிலையாகப் பேசவா—உங்கள் விருப்பம்."
    st.session_state.chat = [{"role": "assistant", "content": greeting, "mode": "welcome"}]
    st.session_state.search_context = {}
    st.session_state.buyer_memory = {}
    st.session_state.advisor_request = {}
    st.session_state.soft_search_preferences = []
    st.session_state.last_results = pd.DataFrame()
    st.session_state.main_results = pd.DataFrame()
    st.session_state.main_results_total_count = 0
    st.session_state.filters_applied = False
    st.session_state.main_start_action = None
    st.session_state.inquiry_conversation_id = str(uuid4())
    st.session_state.conversation_started_at = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
    st.session_state.conversation_closed = False
    st.session_state.end_chat_confirmation_pending = False
    st.session_state.conversation_close_reason = ""
    st.session_state.conversation_ended_at = ""
    st.session_state.mira_rating = None
    st.session_state.mira_rating_saved = False
    st.session_state.awaiting_address_preference = not bool(address)
    st.session_state.show_full_chat_history = False
    st.session_state.followup_schedule = {}


def clear_active_preferences() -> None:
    """Remove the active search context without deleting the conversation transcript."""
    st.session_state.search_context = {}
    st.session_state.buyer_memory = {}
    st.session_state.soft_search_preferences = []
    st.session_state.applied_property_filters = {}
    st.session_state.active_listing_view = "all"
    st.session_state.last_results = pd.DataFrame()
    st.session_state.main_results = pd.DataFrame()
    st.session_state.main_results_total_count = 0
    st.session_state.main_results_mode = "none"
    st.session_state.filters_applied = False
    st.session_state.property_inquiry_active = False
    st.session_state.awaiting_search_preferences = False
    st.session_state.pop("pending_prompt", None)
    st.session_state.mira_pending_filter_sync = None
    st.session_state.clear_filter_widgets_on_next_run = True
    st.session_state.preference_clear_notice = (
        "உங்கள் தேடல் விருப்பங்களும் பரிந்துரைகளும் நீக்கப்பட்டன. புதிய விருப்பங்களைச் சொல்லலாம்."
        if language == "தமிழ்" else
        "Your active search preferences and suggestions were cleared. You can start with new requirements."
    )

if "chat" not in st.session_state:
    st.session_state.chat = [{"role": "assistant", "content": "வணக்கம்! Namma Illam-க்கு வரவேற்கிறேன். நான் Mira, உங்கள் AI வழிகாட்டி. உங்களை என்ன சொல்லி அழைக்கலாம்? உங்கள் பெயரா, Sir/Ma’am என்றா, அல்லது நடுநிலையாகப் பேசவா—உங்கள் விருப்பம். இதைத் தவிர்க்கலாம்; தயாரானபோது எதைப் பற்றி பேச விரும்புகிறீர்களோ அதிலிருந்து தொடங்குங்கள்." if language == "தமிழ்" else "Hi, welcome to Namma Illam! I’m Mira, your AI guide. What should I call you? Your name, Sir or Ma’am, or I can keep it neutral—whichever you prefer. You can skip this and tell me what’s on your mind whenever you’re ready.", "mode": "welcome"}]
    st.session_state.last_results = pd.DataFrame()
elif st.session_state.chat and st.session_state.chat[0].get("mode") == "welcome":
    # Replace the old pushy first message for sessions that were already open.
    address_choice = str(st.session_state.get("preferred_form_of_address", "") or "")
    if address_choice and not address_choice.casefold().startswith("neutral"):
        first_message = (
            f"வணக்கம்! Namma Illam-க்கு மீண்டும் வரவேற்கிறேன். {address_choice} என்று அழைக்கிறேன். நீங்கள் தயாரானபோது பேசலாம்."
            if language == "தமிழ்" else
            f"Welcome to Namma Illam! I’ll address you as {address_choice}. We can pick up whenever you’re ready."
        )
    elif address_choice:
        first_message = (
            "வணக்கம்! Namma Illam-க்கு மீண்டும் வரவேற்கிறேன். உங்கள் வேகத்தில் பேசலாம்."
            if language == "தமிழ்" else
            "Welcome back to Namma Illam. We can continue at your pace."
        )
    else:
        first_message = (
            "வணக்கம்! Namma Illam-க்கு வரவேற்கிறேன். நான் Mira, உங்கள் AI வழிகாட்டி. உங்களை என்ன சொல்லி அழைக்கலாம்? உங்கள் பெயரா, Sir/Ma’am என்றா, அல்லது நடுநிலையாகப் பேசவா—உங்கள் விருப்பம். இதைத் தவிர்க்கலாம்; தயாரானபோது எதைப் பற்றி பேச விரும்புகிறீர்களோ அதிலிருந்து தொடங்குங்கள்."
            if language == "தமிழ்" else
            "Hi, welcome to Namma Illam! I’m Mira, your AI guide. What should I call you? Your name, Sir or Ma’am, or I can keep it neutral—whichever you prefer. You can skip this and tell me what’s on your mind whenever you’re ready."
        )
    st.session_state.chat[0]["content"] = first_message

st.session_state.setdefault("filters_applied", False)
st.session_state.setdefault("main_results", pd.DataFrame())
st.session_state.setdefault("main_results_mode", "none")
st.session_state.setdefault("main_results_total_count", 0)
st.session_state.setdefault("active_listing_view", "all")
st.session_state.setdefault("main_start_action", None)

results_mode_for_wash = st.session_state.get("main_results_mode", "none")
results_frame_for_wash = (
    apply_filters()
    if results_mode_for_wash == "filters"
    else st.session_state.get("main_results")
)
has_visible_results = (
    results_mode_for_wash != "none"
    and st.session_state.get("active_listing_view", "all") != "none"
    and isinstance(results_frame_for_wash, pd.DataFrame)
    and not results_frame_for_wash.empty
)


info_panels = (
    ("auction", f"🔨 {tr('Auction')}"),
    ("loan", f"💰 {tr('Loans')}"),
    ("area", f"📐 {tr('Area & price')}"),
    ("sources", f"🔎 {tr('Sources')}"),
    ("followups", f"🔔 {tr('Follow-up')}"),
)
st.session_state.setdefault("active_info_panel", None)


def render_main_start_choices():
    """Render all eight persistent controls as one balanced 4 by 2 grid."""
    options = (
        ("⌂ வீடு தேட உதவுங்கள்", "வீடு தேட உதவுங்கள்; முதலில் எங்குப் பார்க்கலாம்?", "பகுதி, பட்ஜெட் மற்றும் வீட்டு தேவைகளின் அடிப்படையில் வழிகாட்டப்பட்ட தேடலைத் தொடங்குங்கள்."),
        ("⚖ ஏலச் சொத்துகள்", "ஏலச் சொத்துகளைக் காட்டு", "சேமிக்கப்பட்ட வங்கி ஏலச் சொத்துகளைப் பார்த்து அவற்றின் மூல விவரங்களைச் சரிபாருங்கள்."),
        ("☷ என் விருப்பங்களை அமைக்க", "என் விருப்பங்களின்படி சொத்துகளை வடிகட்ட உதவுங்கள்.", "பகுதி, சொத்து வகை, BHK, பட்ஜெட், அளவு மற்றும் பட்டியல் வகையைத் தேர்ந்தெடுக்கவும்."),
    ) if language == "தமிழ்" else (
        ("⌂ Find a home", "I’m looking for a home. Help me get started.", "Start a guided search using your location, budget, and home requirements."),
        ("⚖ Explore auctions", "Show me auction properties.", "View saved bank-auction properties and verify their source details."),
        ("☷ Set my preferences", "Help me filter properties by my preferences.", "Choose your area, property type, BHK, budget, size, and listing type."),
    )
    selected_action = st.session_state.get("main_start_action")
    active_info_panel = st.session_state.active_info_panel
    with control_grid_slot.container(key="explore-controls"):
        st.markdown("#### 🏡 " + ("எதைப் பார்க்க விரும்புகிறீர்கள்?" if language == "தமிழ்" else "What would you like to explore?"))
        st.caption("ஒரு விருப்பத்தை மீண்டும் தேர்ந்தெடுத்தால் அதன் முடிவு மறையும்." if language == "தமிழ்" else "Select an option to show its result below. Select it again to hide the result.")
        with st.container(key="eight-toggle-grid"):
            grid_columns = [*st.columns(4, gap="small"), *st.columns(4, gap="small")]
        for index, (label, queued_prompt, _option_description) in enumerate(options):
            selected = selected_action == index
            if grid_columns[index].button(
                ("✓ " if selected else "") + label,
                key=f"results_start_{index}",
                type="primary" if selected else "secondary",
                use_container_width=True,
            ):
                previous_prompt = options[selected_action][1] if selected_action in (0, 1, 2) else ""
                chat = st.session_state.get("chat", [])
                if len(chat) >= 2 and chat[-2].get("role") == "user" and chat[-2].get("content") == previous_prompt:
                    st.session_state.chat = chat[:-2]
                st.session_state.pop("pending_prompt", None)
                st.session_state.main_results = pd.DataFrame()
                st.session_state.main_results_total_count = 0
                st.session_state.main_results_mode = "none"
                st.session_state.active_listing_view = "all"
                if selected:
                    st.session_state.main_start_action = None
                else:
                    st.session_state.main_start_action = index
                    st.session_state.pending_prompt = queued_prompt
                st.rerun()
        for offset, (panel_key, panel_label) in enumerate(info_panels, start=3):
            selected = active_info_panel == panel_key
            if grid_columns[offset].button(
                ("✓ " if selected else "") + panel_label,
                key=f"info_panel_{panel_key}",
                type="primary" if selected else "secondary",
                use_container_width=True,
            ):
                st.session_state.active_info_panel = None if selected else panel_key
                st.rerun()
    with guide_slot.container(key="start-option-guides"):
        guide_columns = st.columns(3, gap="small")
        for index, (_label, _queued_prompt, option_description) in enumerate(options):
            guide_columns[index].markdown(f'<div class="start-option-help">{escape(option_description)}</div>', unsafe_allow_html=True)
    return options, selected_action


start_options, selected_start_action = render_main_start_choices()

with results_slot.container(border=has_visible_results, key="results-content-wash-active" if has_visible_results else "results-content-wash-idle"):
    mode = st.session_state.main_results_mode
    if mode == "none":
        if selected_start_action in (0, 1, 2):
            latest_action_reply = next((
                str(item.get("content") or "")
                for item in reversed(st.session_state.chat)
                if item.get("role") == "assistant" and item.get("mode") != "welcome"
            ), "")
            inline_defaults = (
                "Let’s begin with your preferred city or area. Mira will then ask for your budget and home requirements.",
                "Loading the saved bank-auction records here. Open a result’s source before relying on its status or deadline.",
                "Let’s set your preferences one at a time. Start with the city or area you want, then add property type, BHK, budget, size, and listing type.",
            ) if language != "தமிழ்" else (
                "நீங்கள் விரும்பும் நகரம் அல்லது பகுதியில் தொடங்கலாம். அதன் பிறகு பட்ஜெட் மற்றும் வீட்டு தேவைகளை Mira கேட்பார்.",
                "சேமிக்கப்பட்ட வங்கி ஏலப் பதிவுகள் இங்கே ஏற்றப்படுகின்றன. நிலை அல்லது காலக்கெடுவை நம்புவதற்கு முன் அதன் மூலத்தைத் திறந்து சரிபார்க்கவும்.",
                "உங்கள் விருப்பங்களை ஒவ்வொன்றாக அமைப்போம். முதலில் நகரம் அல்லது பகுதி; பின்னர் சொத்து வகை, BHK, பட்ஜெட், அளவு மற்றும் பட்டியல் வகையைச் சேர்க்கலாம்.",
            )
            with st.container(border=True):
                st.markdown(f"**{start_options[selected_start_action][0]}**")
                st.write(latest_action_reply or inline_defaults[selected_start_action])
    else:
        st.markdown(
            f'<div style="margin:0 0 12px;padding:12px 16px;border-radius:14px;background:rgba(7,27,36,.84);border:1px solid rgba(226,240,234,.48);box-shadow:0 8px 20px rgba(3,18,25,.24);color:#F4F7F4;font-size:22px;font-weight:800;line-height:1.3;">🏡 {escape(tr("Search results"))}</div>',
            unsafe_allow_html=True,
        )
        view_labels = {
            "all": "⌂ " + tr("All"),
            "sales": "▦ " + tr("Sales"),
            "auctions": "⚖ " + tr("Auctions"),
        }
        listing_view = st.session_state.get("active_listing_view", "all")
        view_cols = st.columns(3, gap="small")
        for index, view in enumerate(("all", "sales", "auctions")):
            selected_marker = "✓ " if listing_view == view else ""
            if view_cols[index].button(
                selected_marker + view_labels[view],
                key=f"listing_view_{view}",
                type="primary" if listing_view == view else "secondary",
                use_container_width=True,
            ):
                st.session_state.active_listing_view = "none" if listing_view == view else view
                st.rerun()
        if listing_view == "none":
            st.info("ஒரு வகையைத் தேர்ந்தெடுத்தால் முடிவுகள் தெரியும்; தேர்ந்தெடுத்த வகையை மீண்டும் அழுத்தினால் முடிவுகள் மறையும்." if language == "தமிழ்" else "Choose a listing type to show results. Click the selected type again to hide them.")
        else:
            if mode == "chat":
                base_result = st.session_state.main_results
                result_count = st.session_state.main_results_total_count
            else:
                base_result = apply_filters()
                result_count = len(base_result)

            result = filter_listing_view(base_result, listing_view)
            if listing_view != "all":
                result_count = len(result)
            visible_limit = 3 if mode == "chat" else 8
            if mode != "chat" and listing_view == "all":
                result = filter_listing_view(base_result, listing_view, limit=visible_limit)
            category_label = view_labels[listing_view]
            results_summary = (f"{category_label}: {result_count:,} பொருத்தங்கள் · முடிந்த ஏலங்கள் தேர்வு செய்யாவிட்டால் மறைக்கப்படும்; ஏலத் தேதி இல்லாத பதிவுகளை Mira முதலில் கேட்டு உறுதிப்படுத்துவார்." if language == "தமிழ்" else f"{result_count:,} matching {category_label.lower()} · ended auctions stay hidden unless included; Mira asks before showing records with no auction date.")
            st.markdown(
                f'<div style="margin:9px 0 14px;padding:10px 13px;border-radius:12px;background:rgba(7,27,36,.84);border:1px solid rgba(226,240,234,.38);color:#F4F7F4;font-size:13px;font-weight:600;line-height:1.45;box-shadow:0 5px 14px rgba(3,18,25,.18);">{escape(results_summary)}</div>',
                unsafe_allow_html=True,
            )
            if result.empty:
                st.info("இந்த வகை மற்றும் தற்போதைய வடிகட்டிகளுக்கு பதிவுகள் இல்லை. வேறு பட்டியல் வகையையோ பகுதியையோ தேர்ந்தெடுத்துப் பாருங்கள்." if language == "தமிழ்" else "No records in this listing type match the current filters. Try another listing type or area.")
            else:
                for i, (_, row) in enumerate(result.head(visible_limit).iterrows(), 1):
                    render_property_card(row, i)
                shown_count = min(len(result), visible_limit)
                if result_count > shown_count:
                    if mode == "chat":
                        note = "Mira தேர்ந்தெடுத்த முதல் 3 பொருத்தங்கள் இங்கே உள்ளன. வடிகட்டிகள் அல்லது பட்டியல் வகையை மாற்றிப் பாருங்கள்." if language == "தமிழ்" else "Mira’s top matches are shown here. Change the filters or listing type to refine them."
                    else:
                        note = f"முதல் {shown_count} முடிவுகள் காட்டப்படுகின்றன. வடிகட்டிகளைச் சுருக்குங்கள்." if language == "தமிழ்" else f"Showing the first {shown_count} matches. Narrow the filters to see a shorter list."
                    st.info(note)

with chat_slot.container(key="mira-content-wash"):
    chat_header, expand_control = st.columns([8, 1], vertical_alignment="center")
    with chat_header:
        st.markdown("#### 💬 உங்கள் வேகத்தில் பேசலாம்" if language == "தமிழ்" else "#### 💬 Here when you’re ready")
    with expand_control:
        expand_label = "⛶"
        expand_help = (
            "உரையாடலை இயல்பான அளவுக்கு மாற்றவும்" if expand_chat else "Mira-வின் உரையாடலை விரிவாக்கு"
        ) if language == "தமிழ்" else ("Return chat to normal size" if expand_chat else "Expand Mira’s chat")
        if st.button(expand_label, key="toggle_mira_chat_size", help=expand_help, use_container_width=True):
            st.session_state.expand_mira_chat = not expand_chat
            st.rerun()
    st.caption("உங்கள் மனதில் இருப்பதை உங்கள் வேகத்தில் பகிருங்கள்." if language == "தமிழ்" else "Share what’s on your mind, at your own pace.")
    language_switch_notice = st.session_state.pop("language_switch_notice", None)
    if language_switch_notice == "தமிழ்":
        st.info("மொழி தமிழாக மாற்றப்பட்டது. இனி Mira-வின் பதில்களும் பக்கத்தின் விருப்பங்களும் தமிழில் வரும். முந்தைய உரையாடல் செய்திகள் அவை எழுதப்பட்ட மொழியிலேயே இருக்கும்.")
    elif language_switch_notice == "English":
        st.info("Language changed to English. Mira’s replies and page options will use English from now on. Earlier chat messages remain in the language they were written in.")
    if not AI_API_KEY:
        st.caption("உள்ளூர் உதவி · API கட்டணம் இல்லை" if language == "தமிழ்" else "Local assistant · no API charges")
    elif st.session_state.get("agent_rate_limited"):
        st.caption("உங்கள் விருப்பங்களுடன் தொடர்ந்து உதவுகிறேன்." if language == "தமிழ்" else "Mira · Here to help with your saved preferences")
    else:
        st.caption(f"Mira AI · {AI_PROVIDER.title()}")
    with st.expander("தனியுரிமை" if language == "தமிழ்" else "Privacy and data", expanded=False):
        st.caption(
            f"உரையாடல் உரிமையாளர் பார்வைக்கான தனிப்பட்ட கோப்பில் சேமிக்கப்படும். AI இயக்கப்பட்டால், சமீபத்திய உரையாடல், விருப்பங்கள் மற்றும் பொருந்தும் பதிவுகளின் பகுதிகள் {AI_PROVIDER.title()} சேவைக்கு அனுப்பப்படும்; முழு சொத்து கோப்பு பதிவேற்றப்படாது. Aadhaar, PAN, வங்கி கணக்கு அல்லது அடையாள ஆவணங்களை பகிர வேண்டாம். தேவையில்லாத பதிவுகளை உரிமையாளர் நீக்க வேண்டும்."
            if language == "தமிழ்" else
            f"Your conversation is saved in a private chat record. When AI is enabled, recent conversation, remembered preferences and matching record snippets are sent to {AI_PROVIDER.title()}; the full property file is not uploaded. Do not share Aadhaar, PAN, bank-account details, or identity documents. Records should be deleted when they are no longer needed."
        )
    active_memory = st.session_state.get("buyer_memory", {})
    has_active_preferences = bool(
        st.session_state.get("search_context") or active_memory.get("requirements") or
        active_memory.get("preferences") or st.session_state.get("soft_search_preferences") or
        st.session_state.get("main_results_total_count")
    )
    if has_active_preferences and not st.session_state.get("conversation_closed"):
        clear_label = "விருப்பங்களை அழி" if language == "தமிழ்" else "Clear active preferences"
        if st.button(clear_label, key="clear_active_mira_preferences", help="Remove current filters and suggestions while keeping this chat transcript."):
            clear_active_preferences()
            st.rerun()
    if st.session_state.get("preference_clear_notice"):
        st.info(st.session_state.pop("preference_clear_notice"))
    if st.session_state.get("agent_error"):
        st.caption(st.session_state.pop("agent_error"))
    if st.session_state.get("offer_delay_callback") and not st.session_state.get("conversation_closed"):
        st.caption("You can keep chatting here or request a callback from the support team. A live advisor or response time isn’t guaranteed." if language != "தமிழ்" else "இங்கே தொடரலாம் அல்லது ஆதரவு குழுவிடம் தொடர்பு கோரலாம். நேரடி ஆலோசகர் அல்லது பதில் நேரம் உறுதியில்லை.")
        if st.button("Request a human callback" if language != "தமிழ்" else "மனித ஆலோசகர் தொடர்பு கோரிக்கை", key="delay_callback_request"):
            st.session_state.offer_delay_callback = False
            st.session_state.pending_prompt = "Connect me to a human and save a callback request"
            st.rerun()
    if st.session_state.get("inquiry_log_error"):
        st.warning(st.session_state.pop("inquiry_log_error"))
    show_full_chat = st.session_state.get("show_full_chat_history", False)
    if len(st.session_state.chat) > 40 and not st.session_state.get("conversation_closed"):
        toggle_label = (
            "சமீபத்திய உரையாடலை மட்டும் காட்டு" if language == "தமிழ்" and show_full_chat else
            f"முந்தைய {len(st.session_state.chat) - 40} செய்திகளையும் காட்டு" if language == "தமிழ்" else
            "Show recent messages only" if show_full_chat else
            f"Show full conversation ({len(st.session_state.chat)} messages)"
        )
        if st.button(toggle_label, key="toggle_full_chat_history"):
            st.session_state.show_full_chat_history = not show_full_chat
            st.rerun()
        if not show_full_chat:
            st.caption("Older messages remain in Mira’s conversation context." if language != "தமிழ்" else "முந்தைய செய்திகள் Mira-வின் உரையாடல் சூழலில் உள்ளன.")
    visible_chat = st.session_state.chat if show_full_chat or len(st.session_state.chat) <= 40 else st.session_state.chat[-40:]
    if st.session_state.get("conversation_closed"):
        visible_chat = []
    start_message_index = len(st.session_state.chat) - len(visible_chat)
    for message_index, message in enumerate(visible_chat, start_message_index):
        # Let Streamlit draw its built-in role icon. Special text symbols can be
        # mistaken for image paths by some Streamlit versions.
        avatar = str(ASSISTANT_AVATAR) if message["role"] == "assistant" and ASSISTANT_AVATAR.exists() else ("🤖" if message["role"] == "assistant" else "🙂")
        with st.chat_message(message["role"], avatar=avatar):
            if message["role"] == "assistant":
                st.markdown(f'<span class="ai-label">{"AI சொத்து வழிகாட்டி" if language == "தமிழ்" else "AI PROPERTY GUIDE"}</span>', unsafe_allow_html=True)
            st.markdown(message["content"])
            if message.get("mode") == "loans":
                st.caption("வங்கி விருப்பங்களைப் பார்க்க Home loans பகுதியில் கடன் தொகை மற்றும் காலத்தைத் தேர்வு செய்யுங்கள்." if language == "தமிழ்" else "To see lender options, choose an amount and term in the Home loans panel below.")
            if message.get("mode") == "agent":
                for tool_result in message.get("tool_results", []):
                    render_agent_tool_result(tool_result, message_index)
            if message.get("mode") == "results":
                st.caption(f"{message['count']} பொருத்தமான சொத்துப் பதிவுகள்" if language == "தமிழ்" else f"{message['count']} matching property records")
                st.caption("பொருத்தமான பதிவுகள் இடதுபுறத்தில் காட்டப்படுகின்றன." if language == "தமிழ்" else "Matching records are shown in the results panel on the left.")
    if len(visible_chat) > 4 and not st.session_state.get("conversation_closed"):
        st.caption("Scroll up in this chat panel to review earlier messages." if language != "தமிழ்" else "முந்தைய செய்திகளைப் பார்க்க இந்த உரையாடல் பெட்டியில் மேலே உருட்டவும்.")
    if visible_chat and not st.session_state.get("conversation_closed"):
        keep_mira_chat_at_latest()
    if not st.session_state.get("conversation_closed") and not any(message.get("role") == "user" for message in st.session_state.chat):
        st.caption("தொடங்குவதற்கு ஒரு வழியைத் தேர்ந்தெடுக்கலாம்—அல்லது உங்கள் சொற்களில் சொல்லுங்கள்." if language == "தமிழ்" else "If a starting point helps, choose one—or just write in your own words.")
        quick_prompts = (
            ("2BHK தேடல்", "சென்னை அருகே ₹60 லட்சத்திற்குள் 2BHK தேடுங்கள்."),
            ("ஏலப் பட்டியல்கள்", "சேமிக்கப்பட்ட ஏலச் சொத்துகளை காட்டுங்கள்."),
            ("பட்டியல் விளக்கம்", "ஒரு சொத்து பட்டியலை எப்படி சரிபார்ப்பது?"),
        ) if language == "தமிழ்" else (
            ("Find a 2BHK", "Find a 2BHK near Velachery under ₹60 lakh."),
            ("Show auctions", "Show me saved auction properties."),
            ("Explain a listing", "How should I verify a property listing?"),
        )
        with st.container(key="chat-starter-options"):
            quick_cols = st.columns(3)
            for index, (label, queued_prompt) in enumerate(quick_prompts):
                if quick_cols[index].button(label, key=f"chat_starter_{index}", use_container_width=True):
                    st.session_state.pending_prompt = queued_prompt
                    st.rerun()
    if st.session_state.get("conversation_closed"):
        st.info("உரையாடல் முடிந்தது. மீண்டும் உதவி தேவைப்பட்டால் புதிய உரையாடலைத் தொடங்குங்கள்." if language == "தமிழ்" else "This conversation has ended. Start a new conversation whenever you need help again.")
        st.markdown("#### Mira எப்படி உதவினார்?" if language == "தமிழ்" else "#### How did Mira do?")
        if st.session_state.get("mira_rating_saved"):
            selected_rating = int(st.session_state.get("mira_rating") or 0)
            st.success(
                f"உங்கள் {selected_rating}/5 மதிப்பீட்டுக்கு நன்றி." if language == "தமிழ்"
                else f"Thank you for rating Mira {selected_rating}/5."
            )
        else:
            st.caption("உங்கள் திருப்திக்கேற்ப ஒரு நட்சத்திரத்தைத் தேர்ந்தெடுக்கவும்." if language == "தமிழ்" else "Choose one to five stars based on your satisfaction.")
            conversation_id = str(st.session_state.get("inquiry_conversation_id") or "")
            with st.container(key="mira-rating-stars"):
                rating_columns = st.columns(5, gap="small")
                for score, column in enumerate(rating_columns, start=1):
                    if column.button("★", key=f"mira_rating_{conversation_id}_{score}", use_container_width=True, help=f"Rate Mira {score} out of 5"):
                        if conversation_id:
                            try:
                                update_conversation_fields(conversation_id, {
                                    "Mira performance rating (1-5)": score,
                                    "User satisfaction rating (1-5)": score,
                                })
                            except Exception:
                                logging.exception("Could not save Mira rating for %s", conversation_id)
                                st.error("Your rating could not be saved. Please try again.")
                            else:
                                st.session_state.mira_rating = score
                                st.session_state.mira_rating_saved = True
                                st.rerun()
                        else:
                            st.error("This chat has no saved conversation record to rate.")
        if st.button("புதிய உரையாடலைத் தொடங்கு" if language == "தமிழ்" else "Start a new conversation", key="start_new_mira_conversation", type="primary", use_container_width=True):
            start_new_conversation()
            st.rerun()
    else:
        with st.form("mira_chat_composer", clear_on_submit=True):
            with st.container(key="mira-composer-row"):
                composer_input, composer_action = st.columns([4, 1], gap="small", vertical_alignment="center")
                with composer_input:
                    prompt = st.text_input(
                        "Message Mira",
                        placeholder="",
                        label_visibility="collapsed",
                    )
                with composer_action:
                    prompt_sent = st.form_submit_button("அனுப்பு" if language == "தமிழ்" else "Send", use_container_width=True)
        if prompt_sent and prompt.strip():
            with st.chat_message("assistant", avatar=str(ASSISTANT_AVATAR) if ASSISTANT_AVATAR.exists() else "🤖"):
                st.markdown('<span class="ai-label">AI PROPERTY GUIDE</span>', unsafe_allow_html=True)
                with st.spinner("ஒரு நிமிடம், உங்கள் கேள்வியைப் பார்க்கிறேன்…" if language == "தமிழ்" else "Give me a moment—I’m checking your request…"):
                    respond(prompt.strip())
            st.rerun()
        has_user_turn = any(message.get("role") == "user" for message in st.session_state.chat)
        if st.button("உரையாடலை முடிக்கவும்" if language == "தமிழ்" else "End chat", key="end_mira_chat", disabled=not has_user_turn, help="Save this conversation as ended in a private chat record." if language != "தமிழ்" else "இந்த உரையாடலை பாதுகாப்பான பதிவில் முடிந்ததாகச் சேமிக்கவும்.", use_container_width=True):
            close_conversation_from_button()
            st.rerun()
        if "pending_prompt" in st.session_state:
            queued = st.session_state.pop("pending_prompt")
            with st.chat_message("assistant", avatar=str(ASSISTANT_AVATAR) if ASSISTANT_AVATAR.exists() else "🤖"):
                with st.spinner("ஒரு நிமிடம், உங்கள் கேள்வியைப் பார்க்கிறேன்…" if language == "தமிழ்" else "Give me a moment—I’m checking your request…"):
                    respond(queued)
            st.rerun()

active_info_panel = st.session_state.active_info_panel
with st.container(key="info-panel-content"):
    if active_info_panel == "auction":
        st.markdown(f"#### 🔨 {tr('Explore auction properties')}")
        st.markdown("*பாருங்கள். சரிபாருங்கள். முடிவு செய்யுங்கள்.*" if language == "தமிழ்" else "*Explore. Verify. Decide.*")
        st.caption("கீழே சேமிக்கப்பட்ட வங்கி ஏலப் பதிவுகள் காட்டப்படுகின்றன. இவை நேரடி நிலைத் தகவல்கள் அல்ல; ஒவ்வொரு பதிவிலும் உள்ள சரிபார்ப்பு விருப்பத்தைத் திறந்து ஆதாரத்தைப் பாருங்கள்." if language == "தமிழ்" else "Saved bank-auction records appear below. They are not live status updates; open a record’s verification option to view its source.")
        auction_location = st.text_input(tr("City or district"), key="auction_location")
        st.markdown(f"**{tr('Property type')}**")
        auction_all = st.checkbox(tr("All"), value=True, key="auction_type_all", on_change=select_all_auction_types)
        selected_auction_types = [
            property_type for property_type in ("Plot", "House", "Flat")
            if st.checkbox(
                tr(property_type),
                key=f"auction_type_{property_type.casefold()}",
                on_change=select_specific_auction_type,
            )
        ]
        auction_include_ended = st.checkbox(tr("Include ended auctions in this search"), key="auction_include_ended")
        auction_type_filter = "Any" if auction_all or not selected_auction_types else selected_auction_types
        auctions = search_properties(
            properties,
            location=auction_location,
            property_type=auction_type_filter,
            status="Auction",
            include_ended_auctions=auction_include_ended,
        )
        st.caption(f"சேமிக்கப்பட்ட பதிவில் பொருந்தும் ஏலங்கள்: {len(auctions)}" if language == "தமிழ்" else f"{len(auctions)} matching saved auction records.")
        if auctions.empty:
            st.info("சேமிக்கப்பட்ட தகவலில் பொருத்தமான ஏலம் இல்லை. வேறு பகுதியை முயற்சிக்கவும் அல்லது முடிந்த ஏலங்களைச் சேர்க்கவும்." if language == "தமிழ்" else "No saved auction records match these filters. Try another area or include ended auctions.")
        else:
            auction_visible_limit = st.selectbox(
                "Auction cards to show" if language != "தமிழ்" else "காட்ட வேண்டிய ஏலங்கள்",
                (8, 20, 40),
                format_func=lambda count: str(count) if language == "தமிழ்" else f"Show {count}",
                key="auction_visible_limit",
            )
            for i, (_, row) in enumerate(auctions.head(auction_visible_limit).iterrows(), 1):
                render_property_card(row, i)
            if len(auctions) > auction_visible_limit:
                st.info(f"முதல் {auction_visible_limit} முடிவுகள் காட்டப்படுகின்றன. பகுதி அல்லது சொத்து வகையைச் சுருக்கிப் பாருங்கள்." if language == "தமிழ்" else f"Showing the first {auction_visible_limit} results. Narrow the area or property type to see a shorter list.")
    
    def reset_loan_shortlist():
        """Require a fresh lender shortlist when any requested loan inputs change."""
        st.session_state.loan_recommendations_requested = False
    
    
    if active_info_panel == "loan":
        st.markdown(f"#### 💰 {tr('Home loan helper')}")
        st.caption("கடன் தொகை மற்றும் திருப்பிச் செலுத்தும் காலத்தை உள்ளிடுங்கள்; சொத்து வகைக்குப் பொருந்தும் அதிகாரப்பூர்வ கடன் தகவல்களைத் தேர்வு செய்ய உதவுகிறேன்." if language == "தமிழ்" else "Choose a loan amount, repayment term, and property type. I’ll help you explore lender information that may be relevant.")
        st.info("கீழே உள்ளவை தொடக்கமாகப் பார்க்கும் விருப்பங்கள் மட்டுமே. வட்டி, கடன் கிடைப்பது, தகுதி, கட்டணங்கள் மற்றும் விதிமுறைகள் வங்கி மற்றும் விண்ணப்பதாரரைப் பொறுத்து மாறலாம்; மாறவும் செய்யலாம். இங்கு எந்த ஒப்புதலும் அல்லது விகிதமும் உறுதி செய்யப்படவில்லை. துல்லியமான தற்போதைய விவரங்களுக்கு வங்கியின் அதிகாரப்பூர்வ தளத்தைப் பார்க்கவும்." if language == "தமிழ்" else "These are options to explore, not a loan offer. Rates, availability, eligibility, fees, and terms depend on the lender and applicant and may change. No approval or rate is guaranteed here. Check the lender’s official website for current details.")
        loan_results = st.session_state.get("main_results", pd.DataFrame())
        loan_choices = {"Enter a price manually" if language != "தமிழ்" else "விலையை உள்ளிடுங்கள்": None}
        if isinstance(loan_results, pd.DataFrame) and not loan_results.empty:
            for _, listing in loan_results.iterrows():
                listed_price = pd.to_numeric(listing.get("price_inr"), errors="coerce")
                if pd.notna(listed_price) and listed_price > 0:
                    title = str(listing.get("title") or listing.get("property_type") or "Property")
                    price_label, display_price = format_price_for_card(listing)
                    loan_choices[f"{title} · {display_price}"] = float(listed_price)
        loan_left, loan_right = st.columns([1.15, 1])
        st.session_state.setdefault("loan_recommendations_requested", False)
        with loan_left:
            loan_amount = st.number_input("நீங்கள் தேடும் கடன் தொகை (₹)" if language == "தமிழ்" else "Loan amount you have in mind (₹)", min_value=0.0, value=0.0, step=100000.0, key="loan_amount", on_change=reset_loan_shortlist)
            loan_property_kind = st.selectbox("சொத்து வகை" if language == "தமிழ்" else "Property type", ["Home / flat", "Residential plot", "Auction property"], key="loan_property_kind", format_func=lambda value: {"Home / flat": "வீடு / அடுக்குமாடி வீடு", "Residential plot": "குடியிருப்பு மனை", "Auction property": "ஏலச் சொத்து"}.get(value, value) if language == "தமிழ்" else value, on_change=reset_loan_shortlist)
        with loan_right:
            loan_years = st.slider("திருப்பிச் செலுத்தும் காலம் (ஆண்டுகள்)" if language == "தமிழ்" else "Repayment term (years)", min_value=1, max_value=40, value=20, key="loan_years", on_change=reset_loan_shortlist)
            loan_rate = st.number_input("வங்கியிடம் சரிபார்த்த வருடாந்திர வட்டி (%) — விருப்பம்" if language == "தமிழ்" else "Annual rate from a lender (%) — optional", min_value=0.0, max_value=40.0, value=0.0, step=0.1, key="loan_rate")
        if st.button("பொருத்தமான வங்கி விருப்பங்களைப் பார்க்கவும்" if language == "தமிழ்" else "Show possible lender options", key="show_loan_shortlist", type="primary", disabled=loan_amount <= 0, use_container_width=False):
            st.session_state.loan_recommendations_requested = True
        if loan_amount > 0 and loan_rate > 0:
            monthly_rate = loan_rate / 1200
            months = int(loan_years * 12)
            emi = loan_amount * monthly_rate * (1 + monthly_rate) ** months / ((1 + monthly_rate) ** months - 1)
            st.metric("மாதாந்திர EMI (கணிப்பு)" if language == "தமிழ்" else "Illustrative monthly EMI", f"₹{emi:,.0f}")
            st.caption((f"மொத்தம் செலுத்தும் கணிப்பு: ₹{emi * months:,.0f} · வட்டி: ₹{emi * months - loan_amount:,.0f}. இது நீங்கள் உள்ளிட்ட வட்டி விகிதத்தை அடிப்படையாகக் கொண்ட கணிப்பு மட்டுமே." if language == "தமிழ்" else f"Estimated total paid: ₹{emi * months:,.0f} · interest: ₹{emi * months - loan_amount:,.0f}. This illustration uses the rate you entered; it is not a lender quote."))
        else:
            st.caption("உண்மையான வட்டி விகிதம் தெரிந்தபின் உள்ளிட்டால் EMI கணிப்பைக் காட்டுவேன்; வட்டி இல்லாமல் எந்த மதிப்பையும் ஊகிக்க மாட்டேன்." if language == "தமிழ்" else "Once you have a rate from a lender, enter it for an illustrative EMI. I won’t guess a rate.")
        with st.expander("சொத்து விலை மற்றும் முன்பணத்தையும் ஒப்பிடுங்கள்" if language == "தமிழ்" else "Optional: compare a property price and your contribution"):
            selected_loan_listing = st.selectbox("பட்டியலில் உள்ள சொத்தைத் தேர்வு செய்யவும்" if language == "தமிழ்" else "Choose a listed property or enter a price", list(loan_choices), key="loan_listing_choice")
            listing_price = loan_choices[selected_loan_listing]
            manual_price = st.number_input("சொத்து விலை (₹)" if language == "தமிழ்" else "Property price (₹)", min_value=0.0, value=0.0, step=100000.0, key="loan_property_price") if listing_price is None else listing_price
            upfront_amount = st.number_input("உங்களால் செலுத்தக்கூடிய தொகை (₹)" if language == "தமிழ்" else "Amount you could contribute (₹)", min_value=0.0, value=0.0, step=100000.0, key="loan_upfront_amount")
            if manual_price > 0 and upfront_amount > 0:
                funding_gap = max(float(manual_price) - float(upfront_amount), 0)
                st.metric("கணித விலை வித்தியாசம் (₹)" if language == "தமிழ்" else "Arithmetic price difference (₹)", f"₹{funding_gap:,.0f}")
                st.caption("இந்த வித்தியாசம் கடனாகக் கிடைக்கும் என்று அர்த்தமல்ல; வங்கிகள் முன்பணம், ஆவணங்கள், சொத்து மற்றும் உங்கள் தகுதியை மதிப்பிடும்." if language == "தமிழ்" else "This difference is not a promised loan amount. Lenders assess your contribution, documents, property, and eligibility.")
        loan_sources = sources[sources["category"].eq("Loan")]
        loan_sources = loan_sources[~loan_sources["name"].str.contains("terms and conditions", case=False, na=False)]
        if loan_property_kind == "Residential plot":
            candidate_patterns = (r"Union Bank residential plot", r"PNB housing loan", r"HDFC Bank home and plot")
            fit_note = "For a residential plot, these source descriptions explicitly mention plot or plot-plus-construction routes. Approval and construction conditions need direct confirmation." if language != "தமிழ்" else "குடியிருப்பு மனைக்கு, மனை அல்லது மனை-கட்டுமானக் கடன் வழிகளை ஆதார விவரங்கள் குறிப்பிடும் விருப்பங்கள் இவை. அங்கீகாரம் மற்றும் கட்டுமான நிபந்தனைகளை நேரடியாக உறுதிப்படுத்தவும்."
        elif loan_property_kind == "Auction property":
            candidate_patterns = ()
            fit_note = "The saved lender sources don’t confirm financing for auction purchases, so I can’t label a lender as suitable. Check directly with a lender before bidding, including whether its timing works for the auction." if language != "தமிழ்" else "ஏலக் கொள்முதலுக்கான நிதியை சேமித்த வங்கி ஆதாரங்கள் உறுதிப்படுத்தவில்லை; எனவே எந்த வங்கியையும் பொருத்தமானதாகக் கூற முடியாது. ஏலம் கேட்பதற்கு முன் கடன் வழங்குமா, காலக்கெடு ஏலத்துக்கு பொருந்துமா என்பதை வங்கியிடம் உறுதிப்படுத்துங்கள்."
        else:
            candidate_patterns = (r"SBI home loans", r"HDFC Bank home and plot", r"ICICI Bank home loans")
            fit_note = "Shortlisted by the product descriptions in our saved lender sources, not by live rates or your credit eligibility." if language != "தமிழ்" else "சேமித்த கடன் தயாரிப்பு விவரங்களின் அடிப்படையில் மட்டும் தேர்வு செய்யப்பட்டுள்ளது; நேரடி வட்டி அல்லது உங்கள் கடன் தகுதி மதிப்பீடு அல்ல."
        if not st.session_state.loan_recommendations_requested:
            st.caption("கடன் தொகையையும் காலத்தையும் தேர்ந்தெடுத்து ‘Show possible lender options’ என்பதை அழுத்திய பிறகே குறுகிய வங்கி பட்டியல் தோன்றும்." if language == "தமிழ்" else "The lender shortlist stays hidden until you enter a loan amount and choose “Show possible lender options.”")
        elif loan_amount <= 0:
            st.info("முதலில் கடன் தொகையை உள்ளிடுங்கள்." if language == "தமிழ்" else "Enter a loan amount first to see possible lender options.")
        elif not candidate_patterns:
            st.info(fit_note)
        else:
            selected_sources = []
            for pattern in candidate_patterns:
                matches = loan_sources[loan_sources["name"].str.contains(pattern, case=False, regex=True, na=False)]
                if not matches.empty:
                    selected_sources.append(matches.iloc[0])
            if selected_sources:
                st.markdown(f"##### {('உங்கள் தேர்வுக்கான தொடக்க விருப்பங்கள்' if language == 'தமிழ்' else 'Possible lender options for your selection')}")
                st.caption((f"₹{loan_amount:,.0f} · {loan_years} ஆண்டுகள். " if language == 'தமிழ்' else f"₹{loan_amount:,.0f} · {loan_years} years. ") + fit_note + (" சேமித்த ஆதாரங்களில் வங்கிவாரியான கடன் வரம்பு அல்லது அதிகபட்ச காலம் இல்லை; தொகை/காலத் தகுதியை உறுதிப்படுத்த முடியாது." if language == "தமிழ்" else " The saved sources don’t provide lender-specific amount limits or maximum terms, so they can’t confirm fit for this amount or tenure."))
                for source in selected_sources:
                    st.markdown(f"**{source['name']}** — {source['notes']}")
                    st.link_button(("அதிகாரப்பூர்வ தளத்தைத் திறக்கவும் ↗" if language == "தமிழ்" else "Open official lender page ↗"), str(source["url"]), key=f"loan_lender_{source['name']}")
            else:
                st.info("இந்த வகைக்கான சேமித்த அதிகாரப்பூர்வ கடன் தகவல் இப்போது இல்லை." if language == "தமிழ்" else "There isn’t a saved official lender option for this property type yet.")
    
    if active_info_panel == "area":
        st.markdown(f"#### {tr('Make area and price easier to compare')}")
        st.caption("முதலில் அளவை சதுர அடியாக மாற்றுங்கள். விலை ஒப்பீடு வேண்டுமெனில் அதையும் விருப்பமாகத் திறக்கலாம்." if language == "தமிழ்" else "Convert an area to square feet first. Open the optional price comparison only if you need it.")
        with st.container(border=True):
            st.markdown("**அளவை சதுர அடியாக மாற்றுங்கள்**" if language == "தமிழ்" else "**Convert an area to square feet**")
            area_input, unit_input = st.columns([1.2, 1])
            with area_input:
                area_value = st.number_input("எவ்வளவு பெரியது?" if language == "தமிழ்" else "Enter the area", min_value=0.0, value=0.0, step=100.0, key="area_value", help="Enter the number shown in the property details." if language != "தமிழ்" else "சொத்து விவரத்தில் உள்ள அளவை உள்ளிடுங்கள்.")
            with unit_input:
                area_unit = st.selectbox("எந்த அலகில் உள்ளது?" if language == "தமிழ்" else "Current unit", ["sq ft", "sq m", "cents", "acres", "grounds"], key="area_unit", format_func=lambda value: {"sq ft": "சதுர அடி", "sq m": "சதுர மீட்டர்", "cents": "சென்ட்", "acres": "ஏக்கர்", "grounds": "கிரவுண்ட்"}.get(value, value) if language == "தமிழ்" else value)
            if area_value > 0:
                converted = convert_area(area_value, area_unit)
                st.metric("சதுர அடி" if language == "தமிழ்" else "Area in square feet", f"{converted['sq_ft']:,.2f} சதுர அடி" if language == "தமிழ்" else f"{converted['sq_ft']:,.2f} sq ft")
                st.caption(f"{converted['sq_m']:,.2f} மீ²" if language == "தமிழ்" else f"That is also {converted['sq_m']:,.2f} m².")
                with st.expander("பிற அளவுகளையும் பார்க்கவும்" if language == "தமிழ்" else "See other common units"):
                    st.caption(f"{converted['cents']:,.2f} சென்ட் · {converted['acres']:,.4f} ஏக்கர் · {converted['grounds']:,.3f} கிரவுண்ட். கிரவுண்ட் அளவு உள்ளூர் ஆவணத்தில் மாறுபடலாம்; உறுதிப்படுத்தவும்." if language == "தமிழ்" else f"{converted['cents']:,.2f} cents · {converted['acres']:,.4f} acres · {converted['grounds']:,.3f} grounds. Ground conversions follow a common Tamil Nadu convention; check local documents.")
            else:
                st.caption("ஒரு அளவை உள்ளிடுங்கள்; சதுர அடி உடனே கணக்கிடப்படும்." if language == "தமிழ்" else "Enter an area to see its square-foot equivalent here.")
    
        with st.expander("விருப்பம்: விலையை சதுர அடிக்கு ஒப்பிடுங்கள்" if language == "தமிழ்" else "Optional: compare price per square foot"):
            st.caption("விலை மற்றும் அளவை உள்ளிட்டால் ஒரு சதுர அடிக்கான கேட்கும் / ரிசர்வ் விலையை கணக்கிடுகிறேன்." if language == "தமிழ்" else "Enter a price and area to compare the asking or reserve price per square foot.")
            price_cols = st.columns([1, 1, 1])
            total_price = price_cols[0].number_input("மொத்த விலை / ரிசர்வ் (₹)" if language == "தமிழ்" else "Total price / reserve (₹)", min_value=0.0, value=0.0, step=100000.0, key="calc_price")
            calc_size = price_cols[1].number_input("சொத்து அளவு" if language == "தமிழ்" else "Property area", min_value=0.0, value=0.0, step=100.0, key="calc_size")
            calc_unit = price_cols[2].selectbox("அளவு அலகு" if language == "தமிழ்" else "Area unit", ["sq ft", "sq m", "cents", "acres", "grounds"], key="calc_unit", format_func=lambda value: {"sq ft": "சதுர அடி", "sq m": "சதுர மீட்டர்", "cents": "சென்ட்", "acres": "ஏக்கர்", "grounds": "கிரவுண்ட்"}.get(value, value) if language == "தமிழ்" else value)
            if total_price > 0 and calc_size > 0:
                area_sq_ft = convert_area(calc_size, calc_unit)["sq_ft"]
                price_per_sq_ft = float(total_price) / area_sq_ft
                st.metric("ஒரு சதுர அடிக்கான கேட்கும் / ரிசர்வ் விலை" if language == "தமிழ்" else "Asking / reserve price per sq ft", f"₹{price_per_sq_ft:,.0f}/சதுர அடி" if language == "தமிழ்" else f"₹{price_per_sq_ft:,.0f}/sq ft")
                st.caption("நீங்கள் உள்ளிட்ட எண்களிலிருந்து கணக்கிடப்பட்டது; இது மதிப்பீடோ உறுதிப்படுத்தப்பட்ட பரிவர்த்தனை விலையோ அல்ல." if language == "தமிழ்" else "Calculated from your inputs; this isn’t a valuation or a verified transaction price.")
            else:
                st.caption("ஒப்பீட்டைக் காண விலையையும் அளவையும் உள்ளிடுங்கள்." if language == "தமிழ்" else "Add both a price and area to see the comparison.")
    
    if active_info_panel == "sources":
        st.markdown(f"#### {('விவரங்களைச் சரிபார்க்க அதிகாரப்பூர்வ தளங்கள்' if language == 'தமிழ்' else 'Official places to verify details')}")
        st.warning("சேமிக்கப்பட்ட பதிவு ஒரு தொடக்கக் குறிப்பு மட்டுமே. செயல்படுவதற்கு முன் ஏல அறிவிப்பு, காலக்கெடு, உடைமை, உரிமை, வில்லங்கம், தற்போதைய கிடைப்பு மற்றும் வங்கிக் கடன் நிபந்தனைகளை உறுதிப்படுத்தவும்." if language == "தமிழ்" else "A saved record is only a starting point. Confirm auction notices, due dates, possession, title, encumbrances, live availability and lender terms directly before taking action.")
        for category in ("Auction", "Loan", "Project reference", "Existing sale", "Approval record"):
            records = sources[sources["category"].eq(category)]
            if records.empty:
                continue
            st.markdown(f"##### {tr(category)} ஆதாரங்கள்" if language == "தமிழ்" else f"##### {category} sources")
            if category == "Approval record":
                st.info(FRIENDLY_CMDA_NOTE)
            for _, source in records.iterrows():
                with st.container(border=True):
                    st.markdown(f"**[{source['name']} ↗]({source['url']})**")
                    st.caption(f"Checked {source['last_checked']} · {source['purpose']}. {source['notes']}")
        st.markdown("##### வங்கிக் கடன் நினைவூட்டல்" if language == "தமிழ்" else "##### Bank loan reminder")
        st.write("இணைக்கப்பட்ட பக்கங்கள் வங்கித் தயாரிப்புகளை விளக்குகின்றன; கடன் ஒப்புதலை உறுதி செய்யவில்லை. மனைக்கடன், ஏலக் கொள்முதல், திட்ட அங்கீகாரம், கட்டணங்கள், வட்டி வகை மற்றும் உங்கள் தகுதியை வங்கியிடம் கேளுங்கள். வட்டி விகிதங்கள் மாறக்கூடும்." if language == "தமிழ்" else "The linked pages explain bank products; they do not promise approval. Ask each lender about plot loans, auction purchases, project approval, fees, rate type and your own eligibility. Rates change, so the agent does not hard-code an interest rate.")
        st.markdown('<div class="footnote">AI வழிகாட்டி சட்ட, நிதி, உரிமை அல்லது முதலீட்டு பரிந்துரைகள் வழங்காது.</div>' if language == "தமிழ்" else '<div class="footnote">When configured, the AI guide can call a limited set of local search and calculation tools. It does not make legal, financial, title, or investment recommendations.</div>', unsafe_allow_html=True)
    
    if active_info_panel == "followups":
        st.markdown("#### 🔔 உங்கள் தொடர் நினைவூட்டல்கள்" if language == "தமிழ்" else "#### 🔔 Your follow-up reminders")
        st.caption("உங்களுக்கு ஏற்ற முறையைத் தேர்வு செய்யுங்கள். In-app நினைவூட்டல்கள் இந்த உலாவி அமர்வில், இந்தப் பகுதியில் மட்டும் தெரியும்; Email தேர்வுக்கு உங்கள் முகவரி மற்றும் வெளிப்படையான ஒப்புதல் தேவை." if language == "தமிழ்" else "Choose how you’d like Mira to follow up. In-app reminders stay in this browser session and appear in this panel; email follow-ups require your address and explicit opt-in.")
        followup_method = st.radio("Follow-up method" if language != "தமிழ்" else "தொடர்பு முறை", ["In-app reminder", "Email follow-up"], horizontal=True, key="followup_delivery_method", format_func=lambda option: {"In-app reminder": "இந்த உலாவியில்", "Email follow-up": "மின்னஞ்சல்"}.get(option, option) if language == "தமிழ்" else option)
        if followup_method == "Email follow-up" and not FOLLOWUP_EMAIL_READY:
            st.warning("Email அனுப்புதல் இன்னும் அமைக்கப்படவில்லை. உரிமையாளர் SMTP விவரங்களையும் பகிரப்பட்ட website முகவரியையும் secrets-ல் அமைத்து, follow-up worker-ஐ திட்டமிட வேண்டும். இப்போது email அட்டவணை சேமிக்கப்படாது." if language == "தமிழ்" else "Email sending isn’t configured yet. The owner needs to add SMTP settings and the shared website URL to Streamlit secrets, then schedule the follow-up worker. Email schedules can’t be saved yet.")
        elif followup_method == "Email follow-up":
            st.caption("ஒப்புதல் அளித்தபின் மின்னஞ்சல் அட்டவணை சேமிக்கப்படும்; அமைத்துள்ள daily worker இயக்கப்படும்போது மட்டுமே அனுப்பப்படும்." if language == "தமிழ்" else "After you opt in, the email schedule is saved and sends only when the configured daily worker runs.")
        with st.form("manual_followup_form", clear_on_submit=False):
            preference_summary = st.text_area("எதை மீண்டும் பார்க்க விரும்புகிறீர்கள்?" if language == "தமிழ்" else "What would you like to revisit?", placeholder="உதாரணம்: சென்னை அருகே ₹30 லட்சத்திற்குள் மனை" if language == "தமிழ்" else "Example: plots near Chennai, up to ₹30 lakh", key="followup_summary_input")
            if followup_method == "In-app reminder":
                reminder_cols = st.columns(2)
                proposed_due = st.session_state.get("proposed_reminder_due")
                proposed_due = datetime.fromisoformat(proposed_due) if proposed_due else None
                reminder_date = reminder_cols[0].date_input("நினைவூட்டும் தேதி" if language == "தமிழ்" else "Remind me on", value=proposed_due.date() if proposed_due else datetime.now(INDIA_TZ).date() + timedelta(days=7), min_value=datetime.now(INDIA_TZ).date())
                reminder_time = reminder_cols[1].time_input("நேரம் (IST)" if language == "தமிழ்" else "Time (IST)", value=proposed_due.time() if proposed_due else datetime.strptime("10:00", "%H:%M").time())
            else:
                recipient_email = st.text_input("உங்கள் மின்னஞ்சல் முகவரி" if language == "தமிழ்" else "Your email address", placeholder="name@example.com")
                st.caption("முகவரி follow-up அனுப்புவதற்காக மட்டும் தனிப்பட்ட உள்ளூர் பதிவில் வைக்கப்படும். ஆதார், PAN அல்லது வங்கி விவரங்களை follow-up குறிப்பில் எழுத வேண்டாம்." if language == "தமிழ்" else "Your address is kept in a private local follow-up queue for these messages only. Don’t include Aadhaar, PAN, or bank details in your note.")
                email_cadence = st.selectbox("எத்தனை முறை?" if language == "தமிழ்" else "How often should Mira check in?", ["Every 3 days (up to 3 emails)", "One email after 3 days"], key="followup_email_cadence", format_func=lambda option: {"Every 3 days (up to 3 emails)": "3 நாட்களுக்கு ஒருமுறை (அதிகபட்சம் 3 மின்னஞ்சல்கள்)", "One email after 3 days": "3 நாட்களுக்குப் பிறகு ஒரு மின்னஞ்சல்"}.get(option, option) if language == "தமிழ்" else option)
                email_opt_in = st.checkbox("என் மின்னஞ்சலுக்கு இந்த follow-up-ஐ அனுப்ப ஒப்புக்கொள்கிறேன். எந்த நேரத்திலும் நிறுத்தலாம்." if language == "தமிழ்" else "I agree to receive these follow-up emails. I can stop them at any time.")
            save_manual_reminder = st.form_submit_button("நினைவூட்டலைச் சேமிக்கவும்" if language == "தமிழ்" else "Save follow-up", use_container_width=True, disabled=(followup_method == "Email follow-up" and not FOLLOWUP_EMAIL_READY))
        if save_manual_reminder:
            if followup_method == "Email follow-up" and not FOLLOWUP_EMAIL_READY:
                st.error("Email sending isn’t configured yet. Please use an in-app reminder until the owner completes email setup.")
            elif not preference_summary.strip():
                st.error("மீண்டும் எதைப் பார்க்க வேண்டும் என்பதை முதலில் எழுதுங்கள்." if language == "தமிழ்" else "Add a short note about what Mira should follow up on.")
            elif followup_method == "Email follow-up" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient_email.strip()):
                st.error("சரியான மின்னஞ்சல் முகவரியை உள்ளிடுங்கள்." if language == "தமிழ்" else "Enter a valid email address.")
            elif followup_method == "Email follow-up" and not email_opt_in:
                st.error("மின்னஞ்சல் அனுப்புவதற்கு உங்கள் ஒப்புதல் தேவை." if language == "தமிழ்" else "Please opt in before scheduling email follow-ups.")
            else:
                if followup_method == "In-app reminder":
                    due = datetime.combine(reminder_date, reminder_time, tzinfo=INDIA_TZ)
                    if due <= datetime.now(INDIA_TZ):
                        st.error("எதிர்கால நேரத்தைத் தேர்ந்தெடுக்கவும்." if language == "தமிழ்" else "Choose a future time.")
                    else:
                        conversation_id = st.session_state.setdefault("inquiry_conversation_id", str(uuid4()))
                        st.session_state.followup_schedule = {
                            "method": "In-app reminder",
                            "status": "Scheduled",
                            "cadence": "One-time",
                            "consent_at": "",
                            "next_at": due.isoformat(timespec="seconds"),
                        }
                        update_conversation_fields(conversation_id, {
                            "Follow-up method": "In-app reminder",
                            "Follow-up schedule status": "Scheduled",
                            "Follow-up cadence": "One-time",
                            "Follow-up consent timestamp (Asia/Kolkata)": "",
                            "Next follow-up time (Asia/Kolkata)": due.isoformat(timespec="seconds"),
                        })
                        st.session_state.in_app_reminders.append({
                            "id": uuid4().hex,
                            "due_at": due.isoformat(timespec="minutes"),
                            "preferences_summary": preference_summary.strip()[:500],
                            "method": "In-app reminder",
                            "status": "saved",
                        })
                        st.success("இந்த உலாவிக்கான நினைவூட்டல் சேமிக்கப்பட்டது." if language == "தமிழ்" else "In-app reminder saved for this browser session.")
                else:
                    conversation_id = st.session_state.setdefault("inquiry_conversation_id", str(uuid4()))
                    started_at = datetime.fromisoformat(st.session_state["conversation_started_at"])
                    max_messages = 3 if email_cadence.startswith("Every 3 days") else 1
                    try:
                        schedule_id = schedule_email_followup(
                            user_id=str(st.session_state.user_id),
                            conversation_id=str(conversation_id),
                            recipient_email=recipient_email.strip(),
                            customer_name=str(st.session_state.get("customer_name", "")),
                            preference_summary=preference_summary.strip(),
                            started_at=started_at,
                            max_messages=max_messages,
                        )
                        scheduled = next((item for item in list_email_followups(str(st.session_state.user_id)) if item["id"] == schedule_id), None)
                        next_time = datetime.fromisoformat(scheduled["next_send_at"]).astimezone(INDIA_TZ).strftime("%d %b %Y, %I:%M %p IST") if scheduled else ""
                        next_at = scheduled["next_send_at"] if scheduled else ""
                        consent_at = datetime.now(INDIA_TZ).isoformat(timespec="seconds")
                        cadence_label = "Every 3 days · up to 3 emails" if max_messages == 3 else "One email after 3 days"
                        st.session_state.followup_schedule = {
                            "method": "Email",
                            "status": "Scheduled",
                            "cadence": cadence_label,
                            "consent_at": consent_at,
                            "next_at": next_at,
                        }
                        update_conversation_fields(conversation_id, {
                            "Follow-up method": "Email",
                            "Follow-up schedule status": "Scheduled",
                            "Follow-up cadence": cadence_label,
                            "Follow-up consent timestamp (Asia/Kolkata)": consent_at,
                            "Next follow-up time (Asia/Kolkata)": next_at,
                        })
                        st.success((f"Email follow-up saved. First message: {next_time}. You can stop it below or from the stop link in each email." if language != "தமிழ்" else f"மின்னஞ்சல் தொடர் சேமிக்கப்பட்டது. முதல் செய்தி: {next_time}. கீழே அல்லது ஒவ்வொரு மின்னஞ்சலிலும் உள்ள நிறுத்த இணைப்பில் இதை நிறுத்தலாம்."))
                    except Exception:
                        logging.exception("Could not schedule an opted-in email follow-up")
                        st.error("மின்னஞ்சல் நினைவூட்டலைச் சேமிக்க முடியவில்லை. மீண்டும் முயற்சிக்கவும்." if language == "தமிழ்" else "Couldn’t save the email follow-up. Please try again.")
    
        @st.fragment(run_every="30s")
        def render_followup_list():
            reminders = st.session_state.in_app_reminders
            for reminder in reminders:
                due = datetime.fromisoformat(reminder["due_at"]).astimezone(INDIA_TZ)
                with st.container(border=True):
                    st.markdown(f"**{escape(reminder['preferences_summary'])}**")
                    st.caption(f"நினைவூட்டல்: {due.strftime('%d %b %Y, %I:%M %p IST')} · {reminder['status'].title()}" if language == "தமிழ்" else f"Reminder: {due.strftime('%d %b %Y, %I:%M %p IST')} · {reminder['status'].title()}")
                    if reminder["status"] == "saved" and due <= datetime.now(INDIA_TZ):
                        st.warning("இந்த விருப்பங்களை மீண்டும் பார்க்க வேண்டிய நேரம் வந்துவிட்டது." if language == "தமிழ்" else "It’s time to revisit these preferences.")
                    buttons = st.columns(2)
                    if reminder["status"] == "saved" and buttons[0].button("முடிந்தது" if language == "தமிழ்" else "Mark complete", key=f"complete_{reminder['id']}"):
                        reminder["status"] = "complete"
                        st.rerun()
                    if buttons[1].button("நீக்கு" if language == "தமிழ்" else "Remove", key=f"remove_{reminder['id']}"):
                        st.session_state.in_app_reminders = [item for item in reminders if item["id"] != reminder["id"]]
                        st.rerun()
    
            scheduled_email = list_email_followups(str(st.session_state.user_id))
            if scheduled_email:
                st.markdown("##### திட்டமிட்ட மின்னஞ்சல்கள்" if language == "தமிழ்" else "##### Scheduled email follow-ups")
                for item in scheduled_email:
                    with st.container(border=True):
                        state_label = ("திட்டமிடப்பட்டுள்ளது" if item["status"] == "scheduled" else "நிறுத்தப்பட்டது" if item["status"] == "cancelled" else "முடிந்தது") if language == "தமிழ்" else item["status"].title()
                        next_time = datetime.fromisoformat(item["next_send_at"]).astimezone(INDIA_TZ).strftime("%d %b %Y, %I:%M %p IST")
                        masked_email = item["recipient_email"]
                        if "@" in masked_email:
                            name_part, domain_part = masked_email.split("@", 1)
                            masked_email = (name_part[:1] + "***@" + domain_part) if name_part else "***@" + domain_part
                        st.markdown(f"**{escape(item['preference_summary'])}**")
                        st.caption(f"{masked_email} · {state_label} · {item['sent_count']}/{item['max_messages']} sent · Next: {next_time}" if language != "தமிழ்" else f"{masked_email} · {state_label} · {item['sent_count']}/{item['max_messages']} அனுப்பப்பட்டது · அடுத்து: {next_time}")
                        if item["status"] == "scheduled" and st.button("மின்னஞ்சல்களை நிறுத்து" if language == "தமிழ்" else "Stop email follow-ups", key=f"stop_email_followup_{item['id']}"):
                            cancel_email_followup(item["id"], str(st.session_state.user_id))
                            st.session_state.followup_schedule = {**st.session_state.get("followup_schedule", {}), "status": "Stopped by user", "next_at": ""}
                            st.rerun()
    
            if not reminders and not scheduled_email:
                st.info("இன்னும் follow-up எதுவும் அமைக்கப்படவில்லை. In-app அல்லது Email முறையைத் தேர்வு செய்து அமைக்கலாம்." if language == "தமிழ்" else "No follow-ups are scheduled yet. Choose an in-app reminder or opt in to email follow-ups above.")
    
        render_followup_list()
    
    
    
