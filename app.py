from __future__ import annotations

import base64
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

ENDPOINT_URL = "https://immanuel.co"
GET_URL = "https://immanuel.co"
KV_API = "https://keyvalue.immanuel.co"
KV_APP_KEY = "hkradar1"
KV_CHUNK = 800
HTTP_TIMEOUT = 12

HELSINKI_CENTRAL = (60.1708, 24.9414)
WALK_METERS_PER_MIN = 80.0
WEBSITE_TODO = "Website to be done"
HOURS_FALLBACK = "12:00 - 20:00"

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

if "home_mode" not in st.session_state:
    st.session_state["home_mode"] = True


def clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def is_blank_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip().strip('"').strip("'")
        return (not text) or text.lower() in {"null", "none", "undefined", "nan"}
    return False


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
    return normalize_website(raw) == WEBSITE_TODO


def ensure_https(raw: object) -> str:
    text = clean_text(raw)
    if website_is_todo(text):
        return ""
    if text.lower().startswith(("http://", "https://")):
        return text
    return f"https://{text.lstrip('/')}"


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


def normalize_status(raw: object) -> str:
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


def pack_lead(raw: dict) -> dict | None:
    name = clean_text(raw.get("name"))
    address = clean_text(raw.get("address"))
    if not name or not address:
        return None
    saved_at = 0
    try:
        saved_at = int(raw.get("saved_at") or 0)
    except Exception:
        saved_at = 0
    return {
        "name": name,
        "address": address,
        "website": normalize_website(raw.get("website")),
        "hours": normalize_hours(raw.get("hours")),
        "status": normalize_status(raw.get("status")),
        "notes": clean_text(raw.get("notes")),
        "district": infer_district(address),
        "saved_at": saved_at,
        "sid": f"a_{address_key(address)[:24] or 'unknown'}",
    }


def as_leads_list(value: object) -> list[dict]:
    if value is None or is_blank_null(value):
        return []
    if isinstance(value, list):
        leads: list[dict] = []
        for item in value:
            if isinstance(item, dict):
                packed = pack_lead(item)
                if packed:
                    leads.append(packed)
        return leads
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
        if "data" in value:
            return as_leads_list(value.get("data"))
        packed = pack_lead(value)
        return [packed] if packed else []
    return []


def http_call(method: str, url: str) -> object:
    last_error: object = None
    for attempt in range(3):
        fetch_url = url
        if method == "GET":
            stamp = urllib.parse.quote(f"{time.time()}-{attempt}", safe="")
            fetch_url = f"{url}{'&' if '?' in url else '?'}nocache={stamp}"
        request = urllib.request.Request(fetch_url, data=None, method=method)
        request.add_header("Accept", "application/json, text/plain, */*")
        request.add_header("User-Agent", "HelsinkiRadar/1.0")
        request.add_header("Cache-Control", "no-cache, no-store, must-revalidate")
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT, context=context) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            time.sleep(0.2 * (attempt + 1))
            continue
        except Exception as exc:
            last_error = exc
            time.sleep(0.2 * (attempt + 1))
            continue
        if not raw:
            return ""
        text = raw.decode("utf-8", "ignore").strip()
        if is_blank_null(text):
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            return text
        return [] if parsed is None else parsed
    return last_error


def kv_get(item: str) -> str:
    result = http_call("GET", f"{KV_API}/api/KeyVal/GetValue/{KV_APP_KEY}/{item}")
    if isinstance(result, str):
        return result.strip().strip('"')
    if isinstance(result, (int, float)):
        return str(result)
    return ""


def kv_put(item: str, value: str) -> bool:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(value))
    if not safe:
        safe = "W10"
    result = http_call("POST", f"{KV_API}/api/KeyVal/UpdateValue/{KV_APP_KEY}/{item}/{safe}")
    return result is True or str(result).lower() == "true"


def encode_payload(leads: list) -> list[str]:
    blob = json.dumps(leads, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=") or "W10"
    return [token[i : i + KV_CHUNK] for i in range(0, len(token), KV_CHUNK)] or ["W10"]


def decode_payload(pieces: list[str]) -> list[dict]:
    token = re.sub(r"[^A-Za-z0-9_-]", "", "".join(pieces))
    if not token:
        return []
    padding = "=" * ((4 - len(token) % 4) % 4)
    try:
        parsed = json.loads(base64.urlsafe_b64decode(token + padding).decode("utf-8"))
    except Exception:
        return []
    return as_leads_list(parsed)


def initialize_empty_cloud() -> list:
    kv_put("n", "1")
    kv_put("c0", "W10")
    return []


def load_cloud_leads() -> list[dict]:
    n_raw = kv_get("n")
    c0 = kv_get("c0")
    if is_blank_null(n_raw) and is_blank_null(c0):
        return initialize_empty_cloud()
    try:
        n_chunks = max(1, min(40, int(n_raw or "1")))
    except ValueError:
        n_chunks = 1
    pieces = [c0 if i == 0 else kv_get(f"c{i}") for i in range(n_chunks)]
    leads = decode_payload(pieces)
    return leads if isinstance(leads, list) else []


def save_cloud_leads(leads: object) -> bool:
    packed = [item for item in as_leads_list(leads)]
    chunks = encode_payload(packed)
    if not kv_put("n", str(len(chunks))):
        return False
    if not all(kv_put(f"c{index}", chunk) for index, chunk in enumerate(chunks)):
        return False
    stored = load_cloud_leads()
    want = {address_key(item["address"]) for item in packed}
    have = {address_key(item["address"]) for item in stored}
    return want.issubset(have)


def upsert_cloud_lead(lead: dict) -> bool:
    current = load_cloud_leads()
    if not isinstance(current, list):
        current = []
    incoming = pack_lead(lead)
    if incoming is None:
        return False
    incoming["saved_at"] = int(time.time())
    key = address_key(incoming["address"])
    updated: list[dict] = []
    replaced = False
    for item in current:
        packed = pack_lead(item)
        if packed is None:
            continue
        if address_key(packed["address"]) == key:
            packed.update(incoming)
            updated.append(packed)
            replaced = True
        else:
            updated.append(packed)
    if not replaced:
        updated.append(incoming)
    return save_cloud_leads(updated)


def maps_embed_src(address: str) -> str:
    encoded_address = urllib.parse.quote(f"{address}, Helsinki, Finland")
    return f"https://maps.google.com/maps?q={encoded_address}&output=embed"


def render_google_map(address: str) -> None:
    src = maps_embed_src(address)
    st.components.v1.html(
        f"""
<iframe
    width="100%"
    height="140"
    frameborder="0"
    style="border:0; border-radius:8px; background-color:#ffffff;"
    src="{src}">
</iframe>
""",
        height=145,
    )


st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp { background: #0f172a; }
    h1 { color: #f8fafc !important; letter-spacing: -0.03em; }
    .addr-line, .district-line, .hours-line {
        display: block;
        margin: 0 0 0.35rem 0;
        line-height: 1.4;
        color: #e2e8f0;
    }
    .district-badge {
        display: inline-block;
        background: #1e293b;
        color: #93c5fd;
        border: 1px solid #334155;
        border-radius: 999px;
        padding: 0.15rem 0.7rem;
        font-weight: 700;
        font-size: 0.85rem;
        margin: 0.15rem 0 0.35rem 0;
    }
    .nav-link {
        display: inline-block;
        font-weight: 800;
        color: #3b82f6 !important;
        text-decoration: none;
        font-size: 1rem;
        text-align: left;
        margin: 0.15rem 0 0.45rem 0;
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
st.write("### 🌐 Synchronisiertes Cloud-Vertriebs-Dashboard (Echtzeit-Abgleich zwischen PC und Tablet)")

all_leads = load_cloud_leads()
if not isinstance(all_leads, list):
    all_leads = []

st.caption(f"Live-Daten von {ENDPOINT_URL} · {len(all_leads)} Lead(s) in der Cloud.")

st.subheader("Distance")
filter_left, filter_right = st.columns(2)
with filter_left:
    home_mode = bool(st.session_state.get("home_mode", True))
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
    home_mode = bool(st.session_state.get("home_mode", True))
with filter_right:
    industry_keyword = st.text_input(
        "Industry Keyword Filter (e.g., Ravintola, Café, Barber)",
        key="industry_keyword",
    )
    district_filter = st.selectbox("District Filter", options=DISTRICT_OPTIONS, key="district_filter")

origin_lat, origin_lon = HELSINKI_CENTRAL
keyword = (industry_keyword or "").strip().lower()
visible: list[dict] = []
for lead in all_leads:
    packed = pack_lead(lead)
    if packed is None:
        continue
    lat, lon = coords_for_address(packed["address"])
    distance_m = haversine_m(origin_lat, origin_lon, lat, lon)
    if not district_matches(packed["district"], district_filter):
        continue
    if keyword:
        blob = f"{packed['name']} {packed['address']} {packed['district']}".lower()
        if keyword not in blob:
            continue
    if not home_mode and distance_m > float(st.session_state.get("max_distance", 2000)):
        continue
    packed["latitude"] = lat
    packed["longitude"] = lon
    packed["distance_m"] = distance_m
    visible.append(packed)

visible.sort(key=lambda item: (0 if item["status"] == STATUSES[0] else 1, item["distance_m"], item["name"]))

st.markdown("---")
st.subheader("Active Lead Pipeline")
st.caption(f"{len(visible)} sichtbar · {len(all_leads)} in der Cloud.")

if not visible:
    st.info("Keine Leads sichtbar. Home Mode aktivieren oder unten einen Lead speichern.")

for lead in visible:
    uid = lead["sid"]
    status_key = f"status_{uid}"
    notes_key = f"notes_{uid}"
    if status_key not in st.session_state:
        st.session_state[status_key] = lead["status"]
    if notes_key not in st.session_state:
        st.session_state[notes_key] = lead["notes"]

    with st.container(border=True):
        left, right = st.columns([1.3, 1.0])
        with left:
            st.markdown(f"### {lead['name']}")
            st.markdown(
                f"<div class='addr-line'>📍 {lead['address']}, Helsinki</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<span class='district-badge'>🏙️ {lead['district']}</span>",
                unsafe_allow_html=True,
            )
            if home_mode:
                st.markdown("🚶‍♂️ Distance to you: N/A")
            else:
                meters = int(round(lead["distance_m"]))
                minutes = walking_minutes(lead["distance_m"])
                st.markdown(f"🚶‍♂️ Distance to you: {meters} m (ca. {minutes} Min. Fußweg)")
        with right:
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

        demo_href = ensure_https(lead["website"])
        if website_is_todo(lead["website"]) or not demo_href:
            st.button("⚠️ Website to be done", key=f"todo_web_{uid}", disabled=True, use_container_width=True)
        else:
            st.link_button(
                "🌐 Open Demo Website",
                url=demo_href,
                type="primary",
                use_container_width=True,
            )

        chosen_status = st.selectbox("Visit Status", options=STATUSES, key=status_key)
        if chosen_status != lead["status"]:
            if upsert_cloud_lead({**lead, "status": chosen_status, "notes": st.session_state[notes_key]}):
                st.rerun()
            else:
                st.error("Status konnte nicht in der Cloud gespeichert werden.")

        st.text_area("📝 Field Notes (e.g. Email, Mobile):", key=notes_key)
        if st.button("💾 Save Note", key=f"save_note_{uid}", use_container_width=True, type="primary"):
            if upsert_cloud_lead({**lead, "status": st.session_state[status_key], "notes": st.session_state[notes_key]}):
                st.rerun()
            else:
                st.error("Notiz konnte nicht in der Cloud gespeichert werden.")

st.markdown("---")
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=False):
    st.caption("Nur Name und Adresse sind Pflicht. Speichern schreibt in die Cloud — PC und Tablet sehen denselben Stand.")
    with st.form("unzerstörbare_cloud_only_form", clear_on_submit=True):
        add_name = st.text_input("Name des Geschäfts / Firma")
        add_addr = st.text_input("Adresse (z.B. Hämeentie 38)")
        add_link = st.text_input("Website / Demo-Link")
        add_hours = st.text_input("Visiting Hours")
        submitted = st.form_submit_button(
            "💾 LEAD DASHBOARD-WEIT SPEICHERN",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        add_name = clean_text(add_name)
        add_addr = clean_text(add_addr)
        add_link = normalize_website(add_link)
        add_hours = normalize_hours(add_hours)
        if not add_name or not add_addr:
            st.warning("Bitte Name und Adresse ausfüllen.")
        else:
            new_lead = {
                "name": add_name,
                "address": add_addr,
                "website": add_link,
                "hours": add_hours,
                "district": infer_district(add_addr),
                "status": STATUSES[0],
                "notes": "",
            }
            if upsert_cloud_lead(new_lead):
                st.session_state["home_mode"] = True
                st.rerun()
            else:
                st.error("Cloud-Speichern fehlgeschlagen. Bitte erneut versuchen.")
