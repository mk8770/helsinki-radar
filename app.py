from __future__ import annotations

import json
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

HELSINKI_CENTRAL = (60.1708, 24.9414)
WALK_METERS_PER_MIN = 80.0
WEBSITE_TODO = "Website to be done"
HOURS_FALLBACK = "12:00 - 20:00"
HTTP_TIMEOUT = 12

BASE_URL = "https://restful-api.dev"
DB_ID = "ff808181a09d98f701a11a66d4f61e14"
CLOUD_SLOT = f"https://api.restful-api.dev/objects/{DB_ID}"
CLOUD_NAME = "helsinki-radar"

STATUSES = [
    "🆕 Not Visited Yet",
    "✅ Visited - Interested",
    "❌ Visited - Not Interested",
    "⏳ Follow-up Needed",
]

DISTRICT_OPTIONS = [
    "All Districts",
    "Central District (Kluuvi/Kamppi)",
    "Kallio",
    "Töölö",
    "Punavuori/Ullanlinna",
]

DISTRICT_ALIASES = {
    "Central District (Kluuvi/Kamppi)": (
        "central",
        "kluuvi",
        "kamppi",
        "keskusta",
        "center",
        "centre",
    ),
    "Kallio": ("kallio",),
    "Töölö": ("töölö", "toolo", "toolö", "tölö"),
    "Punavuori/Ullanlinna": ("punavuori", "ullanlinna", "punavuori/ullanlinna"),
}

KALLIO_STREETS = (
    "linja",
    "hameentie",
    "helsinginkatu",
    "vaasankatu",
    "porthaninkatu",
    "siltasaarenkatu",
    "castreninkatu",
    "kirstinkatu",
    "fleminginkatu",
    "alppikatu",
)

TOOLO_STREETS = (
    "runeberginkatu",
    "topeliuksenkatu",
    "toolonkatu",
    "arkadiankatu",
    "caloniuksenkatu",
    "mechelininkatu",
    "sibeliuksenkatu",
)

CENTRAL_STREETS = (
    "aleksanterinkatu",
    "kaivokatu",
    "lonnrotinkatu",
    "bulevardi",
    "yronkatu",
    "yrjonkatu",
    "simonkatu",
    "fredrikinkatu",
    "urhokehtosenkatu",
    "kekkosenkatu",
    "keskuskatu",
    "pohjoisesplanadi",
    "etelaesplanadi",
)

KNOWN_COORDS = (
    ("hämeentie 38", 60.1852, 24.9602),
    ("hameentie 38", 60.1852, 24.9602),
    ("hämeentie 54-56 l 58", 60.1873, 24.9620),
    ("hameentie 54-56 l 58", 60.1873, 24.9620),
    ("hämeentie 54-56", 60.1873, 24.9620),
    ("hämeentie 54", 60.1873, 24.9620),
    ("hämeentie 56", 60.1873, 24.9620),
    ("hameentie 54-56", 60.1873, 24.9620),
    ("hameentie 54", 60.1873, 24.9620),
    ("toinen linja 23", 60.1849, 24.9506),
    ("toinen linja", 60.1849, 24.9506),
    ("pohjoisesplanadi 2", 60.1678, 24.9436),
    ("aleksanterinkatu 26", 60.1691, 24.9522),
    ("mannerheimintie 20", 60.1692, 24.9388),
    ("vaasankatu 11", 60.1878, 24.9505),
    ("topeliuksenkatu 21", 60.1835, 24.9208),
    ("museokatu 18", 60.1756, 24.9215),
    ("fredrikinkatu 19", 60.1635, 24.9380),
    ("iso roobertinkatu 8", 60.1638, 24.9412),
    ("tehtaankatu 27", 60.1589, 24.9448),
)

st.set_page_config(
    page_title="Helsinki Website Leads",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "editing_sid" not in st.session_state:
    st.session_state["editing_sid"] = ""


def is_blank_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "ignore")
    if isinstance(value, str):
        text = value.strip().strip('"').strip("'")
        return (not text) or text.lower() in {"null", "none", "undefined", "nan"}
    return False


def as_leads_list(value: object) -> list:
    """Always return a real Python list. Never None. Never crash on null/empty."""
    if value is None or is_blank_null(value):
        return []
    if isinstance(value, list):
        clean: list = []
        for item in value:
            if isinstance(item, dict) and clean_text(item.get("name")) and clean_text(item.get("address")):
                clean.append(item)
        return clean
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", "ignore")
        except Exception:
            return []
    if isinstance(value, str):
        text = value.strip()
        if is_blank_null(text):
            return []
        try:
            return as_leads_list(json.loads(text))
        except Exception:
            return []
    if isinstance(value, dict):
        if "leads" in value:
            return as_leads_list(value.get("leads"))
        nested = value.get("data")
        if nested is not None and nested is not value:
            return as_leads_list(nested)
        if clean_text(value.get("name")) and clean_text(value.get("address")):
            return [value]
        return []
    return []


def cloud_exchange(method: str, url: str, payload: dict | None = None) -> object:
    last_error: object = None
    for attempt in range(3):
        fetch_url = url
        if method == "GET":
            stamp = urllib.parse.quote(str(time.time()) + str(attempt), safe="")
            fetch_url = f"{url}{'&' if '?' in url else '?'}nocache={stamp}"
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(fetch_url, data=body, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "HelsinkiRadar/1.0")
        request.add_header("Cache-Control", "no-cache, no-store, must-revalidate")
        request.add_header("Pragma", "no-cache")
        if body is not None:
            request.add_header("Content-Type", "application/json; charset=utf-8")
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT, context=context) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            try:
                raw = exc.read()
            except Exception:
                time.sleep(0.25 * (attempt + 1))
                continue
            if int(exc.code) >= 500:
                time.sleep(0.25 * (attempt + 1))
                continue
        except Exception as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
            continue
        if not raw:
            last_error = "empty-body"
            time.sleep(0.25 * (attempt + 1))
            continue
        text = raw.decode("utf-8", "ignore").strip()
        if is_blank_null(text):
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            last_error = "invalid-json"
            time.sleep(0.25 * (attempt + 1))
            continue
        if parsed is None:
            return []
        return parsed
    return last_error if last_error is not None else None


def cloud_ok(result: object) -> bool:
    if result is None:
        return False
    if isinstance(result, Exception):
        return False
    if isinstance(result, str) and result in {"empty-body", "invalid-json"}:
        return False
    return True


def load_cloud_leads() -> tuple[list, bool]:
    """Always read the live cloud slot. Never wipe it when GET fails."""
    document = cloud_exchange("GET", CLOUD_SLOT)
    if not cloud_ok(document):
        return [], False
    leads = as_leads_list(document)
    return (leads if isinstance(leads, list) else []), True


def pack_cloud_payload(leads: object) -> dict:
    packed = []
    for item in as_leads_list(leads):
        packed.append(serialize_lead(item))
    return {"name": CLOUD_NAME, "data": {"leads": packed}}


def lead_in_list(leads: list, target: dict) -> bool:
    want = address_key(clean_text(target.get("address")))
    want_name = clean_text(target.get("name")).lower()
    for item in as_leads_list(leads):
        if address_key(clean_text(item.get("address"))) == want:
            if not want_name or clean_text(item.get("name")).lower() == want_name:
                return True
            return True
    return False


def save_cloud_leads(leads: object) -> bool:
    payload = pack_cloud_payload(leads)
    expected = as_leads_list(payload.get("data"))
    for _ in range(3):
        result = cloud_exchange("PUT", CLOUD_SLOT, payload)
        if not cloud_ok(result):
            time.sleep(0.2)
            continue
        stored, ok = load_cloud_leads()
        if ok and len(as_leads_list(stored)) >= len(expected):
            if not expected:
                return True
            if all(lead_in_list(stored, item) for item in expected):
                return True
        time.sleep(0.2)
    return False


def upsert_cloud_lead(lead: dict) -> bool:
    current, ok = load_cloud_leads()
    if not ok or not isinstance(current, list):
        return False
    incoming = serialize_lead(lead)
    if not incoming["name"] or not incoming["address"]:
        return False
    key = address_key(incoming["address"])
    updated: list = []
    replaced = False
    for item in current:
        if not isinstance(item, dict):
            continue
        if address_key(clean_text(item.get("address"))) == key:
            incoming_full = dict(serialize_lead(item))
            incoming_full.update(incoming)
            updated.append(incoming_full)
            replaced = True
        else:
            updated.append(serialize_lead(item))
    if not replaced:
        updated.append(incoming)
    if not save_cloud_leads(updated):
        return False
    stored, stored_ok = load_cloud_leads()
    return stored_ok and lead_in_list(stored, incoming)


def forget_lead_widget_state() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith(("status_", "notes_", "edit_name_", "edit_addr_", "edit_link_", "edit_hours_")):
            del st.session_state[key]


def clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def normalize_hours(raw: object) -> str:
    text = clean_text(raw)
    return text if text else HOURS_FALLBACK


def normalize_website(raw: object) -> str:
    text = clean_text(raw)
    low = text.lower().rstrip("/")
    if not text or low in {"https:", "http:", "https://", "http://", "https", "http"}:
        return WEBSITE_TODO
    if "google.com/search" in low:
        return WEBSITE_TODO
    return text


def website_is_todo(raw: object) -> bool:
    text = normalize_website(raw)
    return (not text) or text == WEBSITE_TODO


def ensure_https(raw: object) -> str:
    text = clean_text(raw)
    if website_is_todo(text):
        return ""
    if text.lower().startswith(("http://", "https://")):
        return text
    return f"https://{text.lstrip('/')}"


def live_website_url(raw: object) -> str:
    return ensure_https(normalize_website(raw))


def normalize_addr(address: str) -> str:
    text = address.lower().replace("ß", "ss")
    text = re.sub(r"[.,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fold_fi(text: str) -> str:
    return text.lower().replace("ä", "a").replace("ö", "o").replace("å", "a").replace("é", "e")


def address_key(address: str) -> str:
    return fold_fi(str(address).lower().strip())


def first_street_number(address: str) -> int | None:
    match = re.search(r"(\d+)", normalize_addr(address))
    if not match:
        return None
    return int(match.group(1))


def infer_district(address: str) -> str:
    haystack = fold_fi(normalize_addr(address))
    if not haystack:
        return "Central District (Kluuvi/Kamppi)"
    if "mannerheimintie" in haystack:
        number = first_street_number(address)
        if number is not None and number > 30:
            return "Töölö"
        return "Central District (Kluuvi/Kamppi)"
    if any(street in haystack for street in KALLIO_STREETS):
        return "Kallio"
    if any(street in haystack for street in TOOLO_STREETS):
        return "Töölö"
    if any(street in haystack for street in CENTRAL_STREETS):
        return "Central District (Kluuvi/Kamppi)"
    return "Central District (Kluuvi/Kamppi)"


def district_matches(row_district: str, selected: str) -> bool:
    if selected == "All Districts":
        return True
    if selected.lower() in row_district.lower():
        return True
    low = normalize_addr(row_district)
    aliases = DISTRICT_ALIASES.get(selected, ())
    return any(alias in low for alias in aliases)


def normalize_status(raw: str) -> str:
    text = clean_text(raw)
    if text in STATUSES:
        return text
    low = text.lower()
    if "not interested" in low:
        return STATUSES[2]
    if "interested" in low:
        return STATUSES[1]
    if "follow-up" in low or "follow up" in low:
        return STATUSES[3]
    return STATUSES[0]


def coords_for_address(address: str) -> tuple[float, float]:
    haystack = normalize_addr(address)
    for fragment, c_lat, c_lon in KNOWN_COORDS:
        if fragment in haystack:
            return c_lat, c_lon
    return HELSINKI_CENTRAL


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, a)))


def walking_minutes(meters: float) -> int:
    if meters <= 0:
        return 0
    return max(1, int(round(meters / WALK_METERS_PER_MIN)))


def native_geo_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def render_google_map(address: str) -> None:
    query = urllib.parse.quote(f"{address}, Helsinki, Finland")
    st.components.v1.html(
        f"""
<iframe
    width="100%"
    height="140"
    frameborder="0"
    style="border:0; border-radius:8px; background-color:#ffffff;"
    src="https://maps.google.com/maps?q={query}&t=&z=15&ie=UTF8&iwloc=&output=embed">
</iframe>
""",
        height=145,
    )


def empty_lead(
    name: str,
    address: str,
    website: str = "",
    hours: str = "",
    status: str = "",
    notes: str = "",
) -> dict:
    address_text = clean_text(address)
    return {
        "name": clean_text(name),
        "address": address_text,
        "website": normalize_website(website),
        "hours": normalize_hours(hours),
        "status": normalize_status(status),
        "notes": clean_text(notes),
        "district": infer_district(address_text),
        "sid": f"a_{address_key(address_text)[:24] or 'unknown'}",
    }


def serialize_lead(lead: dict) -> dict:
    address_text = clean_text(lead.get("address"))
    return {
        "name": clean_text(lead.get("name")),
        "address": address_text,
        "website": normalize_website(lead.get("website")),
        "hours": normalize_hours(lead.get("hours")),
        "status": normalize_status(lead.get("status", "")),
        "notes": clean_text(lead.get("notes")),
        "district": infer_district(address_text),
    }


st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .hours-line { text-align: left; margin: 0 0 0.35rem 0; }
    .addr-line, .district-line { display: block; margin: 0 0 0.2rem 0; line-height: 1.35; }
    .nav-link {
        display: inline-block;
        font-weight: 800;
        color: #4285F4 !important;
        text-decoration: none;
        font-size: 0.95rem;
        text-align: left;
        margin: 0.1rem 0 0.4rem 0;
    }
    div[data-testid="stForm"] button[kind="primary"] {
        background-color: #dc2626 !important;
        border-color: #b91c1c !important;
        color: #ffffff !important;
        font-weight: 800 !important;
        min-height: 3.1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎯 Helsinki Website Leads")
st.markdown(
    "All leads are stored in the shared cloud database. "
    "The browser address bar stays clean — use the same short bookmark on every device."
)

all_leads, cloud_live = load_cloud_leads()
if not isinstance(all_leads, list):
    all_leads = []
if cloud_live:
    st.caption(f"Cloud live via {BASE_URL} · {len(all_leads)} lead(s) loaded from the server.")
else:
    st.error("Cloud GET failed — showing an empty pipeline. Manual save is blocked until the cloud answers.")

st.subheader("Distance")
filter_left, filter_right = st.columns(2)
with filter_left:
    home_mode = bool(st.session_state.get("home_mode", False))
    st.slider(
        "Max walking distance from YOUR location (meters)",
        min_value=100,
        max_value=5000,
        value=2000,
        step=50,
        disabled=home_mode,
        key="max_distance",
    )
    st.checkbox("🏠 Home Mode (Show all prepared leads)", key="home_mode")
    home_mode = bool(st.session_state.get("home_mode", False))
with filter_right:
    industry_keyword = st.text_input(
        "Industry Keyword Filter (e.g., Ravintola, Café, Barber)",
        key="industry_keyword",
    )
    district_filter = st.selectbox("District Filter", options=DISTRICT_OPTIONS, key="district_filter")

origin_lat, origin_lon = HELSINKI_CENTRAL
keyword = (industry_keyword or "").strip().lower()

enriched_rows: list[dict] = []
for lead in all_leads:
    if not isinstance(lead, dict):
        continue
    display = empty_lead(
        name=lead.get("name", ""),
        address=lead.get("address", ""),
        website=lead.get("website", ""),
        hours=lead.get("hours", ""),
        status=lead.get("status", ""),
        notes=lead.get("notes", ""),
    )
    lat, lon = coords_for_address(display["address"])
    distance_m = haversine_m(origin_lat, origin_lon, lat, lon)
    if not district_matches(display["district"], district_filter):
        continue
    if keyword:
        blob = f"{display['name']} {display['address']} {display['district']}".lower()
        if keyword not in blob:
            continue
    if not home_mode and distance_m > float(st.session_state.get("max_distance", 2000)):
        continue
    display["latitude"] = lat
    display["longitude"] = lon
    display["distance_m"] = distance_m
    enriched_rows.append(display)

enriched_rows.sort(
    key=lambda item: (0 if item["status"] == STATUSES[0] else 1, item["distance_m"], item["name"])
)

st.markdown("---")
st.subheader("Active Lead Pipeline")
st.caption(f"{len(enriched_rows)} lead(s) visible of {len(all_leads)} stored in the cloud.")

if not enriched_rows:
    st.info("No leads match these filters. Turn on Home Mode, relax the filters, or add a lead below.")

for lead in enriched_rows:
    uid = lead["sid"]
    status_key = f"status_{uid}"
    notes_key = f"notes_{uid}"
    if status_key not in st.session_state:
        st.session_state[status_key] = lead["status"]
    if notes_key not in st.session_state:
        st.session_state[notes_key] = lead["notes"]

    with st.container(border=True):
        c1, c2 = st.columns([1.3, 1.0])
        with c1:
            editing = st.session_state.get("editing_sid") == uid
            if editing:
                if f"edit_name_{uid}" not in st.session_state:
                    st.session_state[f"edit_name_{uid}"] = lead["name"]
                if f"edit_addr_{uid}" not in st.session_state:
                    st.session_state[f"edit_addr_{uid}"] = lead["address"]
                if f"edit_link_{uid}" not in st.session_state:
                    st.session_state[f"edit_link_{uid}"] = (
                        "" if website_is_todo(lead["website"]) else lead["website"]
                    )
                if f"edit_hours_{uid}" not in st.session_state:
                    st.session_state[f"edit_hours_{uid}"] = lead["hours"]
                st.text_input("Edit Name", key=f"edit_name_{uid}")
                st.text_input("Edit Address", key=f"edit_addr_{uid}")
                st.text_input("Edit Website Link", key=f"edit_link_{uid}")
                st.text_input("Edit Visiting Hours", key=f"edit_hours_{uid}")
                save_col, cancel_col = st.columns(2)
                with save_col:
                    if st.button("💾 Save Changes", key=f"save_info_{uid}", type="primary", use_container_width=True):
                        new_name = clean_text(st.session_state[f"edit_name_{uid}"])
                        new_addr = clean_text(st.session_state[f"edit_addr_{uid}"])
                        new_link = normalize_website(st.session_state[f"edit_link_{uid}"])
                        new_hours = normalize_hours(st.session_state[f"edit_hours_{uid}"])
                        if new_name and new_addr:
                            ok = upsert_cloud_lead(
                                empty_lead(
                                    name=new_name,
                                    address=new_addr,
                                    website=new_link,
                                    hours=new_hours,
                                    status=st.session_state[status_key],
                                    notes=st.session_state[notes_key],
                                )
                            )
                            if ok:
                                st.session_state["editing_sid"] = ""
                                forget_lead_widget_state()
                                st.rerun()
                            else:
                                st.error("Cloud save failed. The lead was not confirmed on the server.")
                        else:
                            st.warning("Name and address are required.")
                with cancel_col:
                    if st.button("❌ Cancel", key=f"cancel_info_{uid}", use_container_width=True):
                        st.session_state["editing_sid"] = ""
                        st.rerun()
            else:
                st.markdown(f"### {lead['name']}")
                st.markdown(
                    f"<div class='addr-line'>📍 Address: {lead['address']}, Helsinki</div>",
                    unsafe_allow_html=True,
                )
                if st.button("✏️ Edit Lead Info", key=f"edit_btn_{uid}"):
                    st.session_state["editing_sid"] = uid
                    st.rerun()

            st.markdown(
                f"<div class='district-line'>🏙️ District: {lead['district']}</div>",
                unsafe_allow_html=True,
            )
            if home_mode:
                st.markdown("🚶‍♂️ Distance to you: N/A")
            else:
                meters = int(round(lead["distance_m"]))
                minutes = walking_minutes(lead["distance_m"])
                st.markdown(f"🚶‍♂️ Distance to you: {meters} m (ca. {minutes} Min. Fußweg)")

            chosen_status = st.selectbox(
                "Visit status",
                options=STATUSES,
                key=status_key,
                label_visibility="collapsed",
            )
            if chosen_status != lead["status"]:
                ok = upsert_cloud_lead(
                    empty_lead(
                        name=lead["name"],
                        address=lead["address"],
                        website=lead["website"],
                        hours=lead["hours"],
                        status=chosen_status,
                        notes=st.session_state[notes_key],
                    )
                )
                if ok:
                    forget_lead_widget_state()
                    st.rerun()
                else:
                    st.error("Cloud save failed. The lead was not confirmed on the server.")

            demo_href = live_website_url(lead["website"])
            if website_is_todo(lead["website"]) or not demo_href:
                st.button("⚠️ Website to be done", key=f"todo_web_{uid}", disabled=True, use_container_width=True)
            else:
                st.link_button(
                    f"🌐 Click here to open Demo Website for {lead['name']}",
                    url=demo_href,
                    type="primary",
                    use_container_width=True,
                )

        with c2:
            st.markdown(
                f"<div class='hours-line'>⏱️ Visiting Hours: <code>{lead['hours']}</code></div>",
                unsafe_allow_html=True,
            )
            geo_url = native_geo_url(lead["latitude"], lead["longitude"])
            st.markdown(
                f'<a class="nav-link" href="{geo_url}" target="_blank" rel="noopener noreferrer">🗺️ Navigation</a>',
                unsafe_allow_html=True,
            )
            render_google_map(lead["address"])

        st.text_area("✍️ Field Notes (e.g. Email, Mobile):", key=notes_key)
        if st.button("💾 Save Note", key=f"save_note_{uid}", use_container_width=True, type="secondary"):
            ok = upsert_cloud_lead(
                empty_lead(
                    name=lead["name"],
                    address=lead["address"],
                    website=lead["website"],
                    hours=lead["hours"],
                    status=st.session_state[status_key],
                    notes=st.session_state[notes_key],
                )
            )
            if ok:
                forget_lead_widget_state()
                st.rerun()
            else:
                st.error("Cloud save failed. The note was not confirmed on the server.")

st.markdown("---")
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=True):
    st.caption("Nur Name und Adresse sind Pflicht. Speichern hat höchste Priorität und überschreibt die Cloud sofort.")
    with st.form("final_cloud_only_form", clear_on_submit=True):
        add_name = st.text_input("Name des Geschäfts / Firma", key="form_add_name")
        add_addr = st.text_input("Adresse (z.B. Hämeentie 38)", key="form_add_addr")
        add_link = st.text_input("Website / Demo-Link", key="form_add_link")
        add_hours = st.text_input("Visiting Hours", key="form_add_hours")
        submitted = st.form_submit_button(
            "💾 LEAD DASHBOARD-WEIT SPEICHERN",
            use_container_width=True,
            type="primary",
            disabled=not cloud_live,
        )

    if submitted:
        add_name = clean_text(add_name)
        add_addr = clean_text(add_addr)
        add_link = normalize_website(add_link)
        add_hours = normalize_hours(add_hours)
        if not add_name or not add_addr:
            st.warning("Bitte Name des Geschäfts und Adresse ausfüllen.")
        else:
            new_lead = empty_lead(
                name=add_name,
                address=add_addr,
                website=add_link,
                hours=add_hours,
            )
            new_lead["district"] = infer_district(add_addr)
            ok = upsert_cloud_lead(new_lead)
            if ok:
                forget_lead_widget_state()
                st.session_state["home_mode"] = True
                st.rerun()
            else:
                st.error("Cloud save failed. The lead was not confirmed on the server.")
