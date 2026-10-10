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

API_URL = "https://sheety.co"
SHEET_ID = "1Fw6T2gxui7XCTYskT90890poXIIgZ6SxLytUA1eMtns"
SHEET1_GET_URL = "https://opensheet.elk.sh/" + SHEET_ID + "/sheet1"
GVIZ_URL = (
    "https://docs.google.com/spreadsheets/d/"
    + SHEET_ID
    + "/gviz/tq?tqx=out:json&gid=0"
)
HTTP_TIMEOUT = 12

HELSINKI_CENTRAL = (60.1708, 24.9414)
WALK_METERS_PER_MIN = 80.0
WEBSITE_TODO = "Website to be done"
HOURS_FALLBACK = "12:00 - 20:00"

STATUSES = [
    "Not Visited Yet",
    "Visited - Interested",
    "Visited - Not Interested",
    "Follow-up Needed",
]

DISTRICT_OPTIONS = [
    "All Districts",
    "Central District (Kluuvi/Kamppi)",
    "Kallio",
    "Toolo",
    "Punavuori/Ullanlinna",
]

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
    ("hameentie 38", 60.1852, 24.9602),
    ("hameentie 54-56 l 58", 60.1873, 24.9620),
    ("hameentie 54-56", 60.1873, 24.9620),
    ("hameentie 54", 60.1873, 24.9620),
    ("toinen linja 23", 60.1849, 24.9506),
    ("toinen linja", 60.1849, 24.9506),
    ("pohjoisesplanadi 2", 60.1678, 24.9436),
    ("aleksanterinkatu 26", 60.1691, 24.9522),
    ("mannerheimintie 20", 60.1692, 24.9388),
    ("vaasankatu 11", 60.1878, 24.9505),
    ("topeliuksenkatu 21", 60.1835, 24.9208),
    ("fredrikinkatu 19", 60.1635, 24.9380),
)

st.set_page_config(
    page_title="Helsinki Website Leads",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)



def clean_text(value: object) -> str:
    if value is None:
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


def row_get(row: dict, *names: str) -> str:
    folded = {str(key).strip().lower(): row.get(key) for key in row.keys()}
    for name in names:
        if name.lower() in folded:
            return clean_text(folded[name.lower()])
    return ""


def normalize_hours(raw: object) -> str:
    text = clean_text(raw)
    return text if text else HOURS_FALLBACK


def normalize_website(raw: object) -> str:
    text = clean_text(raw)
    low = text.lower().rstrip("/")
    if not text or low in {"https:", "http:", "https://", "http://", "https", "http"}:
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
    return "https://" + text.lstrip("/")


def fold_fi(text: str) -> str:
    return (
        text.lower()
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("å", "a")
        .replace("é", "e")
    )


def normalize_addr(address: str) -> str:
    text = fold_fi(address.lower().replace("ß", "ss"))
    text = re.sub(r"[.,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def address_key(address: str) -> str:
    return normalize_addr(str(address))


def first_street_number(address: str) -> int | None:
    match = re.search(r"(\d+)", normalize_addr(address))
    if not match:
        return None
    return int(match.group(1))


def infer_district(address: str) -> str:
    haystack = normalize_addr(address)
    if not haystack:
        return "Central District (Kluuvi/Kamppi)"
    if "mannerheimintie" in haystack:
        number = first_street_number(address)
        if number is not None and number > 30:
            return "Toolo"
        return "Central District (Kluuvi/Kamppi)"
    if any(street in haystack for street in KALLIO_STREETS):
        return "Kallio"
    if any(street in haystack for street in TOOLO_STREETS):
        return "Toolo"
    if any(street in haystack for street in CENTRAL_STREETS):
        return "Central District (Kluuvi/Kamppi)"
    return "Central District (Kluuvi/Kamppi)"


def district_matches(row_district: str, selected: str) -> bool:
    if selected == "All Districts":
        return True
    return selected.lower() in row_district.lower()


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
    radius = 6371000.0
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
    return "https://www.google.com/maps/search/?api=1&query={:.6f},{:.6f}".format(lat, lon)


def pack_lead(row: dict) -> dict | None:
    name = row_get(row, "name", "company-name", "company")
    address = row_get(row, "address", "adress", "street-address")
    if not name or not address:
        return None
    address = re.sub(r",?\s*helsinki\s*$", "", address, flags=re.I).strip() or address
    return {
        "id": row_get(row, "id"),
        "name": name,
        "address": address,
        "website": normalize_website(row_get(row, "website", "url")),
        "hours": normalize_hours(row_get(row, "hours")),
        "status": normalize_status(row_get(row, "status")),
        "notes": row_get(row, "notes"),
        "district": infer_district(address),
        "sid": "a_" + (address_key(address)[:24] or "unknown"),
    }


def as_leads_list(value: object) -> list[dict]:
    if value is None or is_blank_null(value):
        return []
    rows: list = []
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        if isinstance(value.get("sheet1"), list):
            rows = value.get("sheet1") or []
        elif isinstance(value.get("Sheet1"), list):
            rows = value.get("Sheet1") or []
        elif pack_lead(value):
            rows = [value]
    elif isinstance(value, str):
        text = value.strip()
        if is_blank_null(text):
            return []
        try:
            return as_leads_list(json.loads(text))
        except Exception:
            return []
    merged: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        packed = pack_lead(row)
        if packed:
            merged[address_key(packed["address"])] = packed
    return list(merged.values())


def http_call(method: str, url: str, payload: dict | None = None) -> object:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    fetch_url = url
    if method == "GET":
        stamp = urllib.parse.quote(str(time.time()), safe="")
        fetch_url = url + ("&" if "?" in url else "?") + "nocache=" + stamp
    request = urllib.request.Request(fetch_url, data=body, method=method)
    request.add_header("Accept", "application/json, text/plain, */*")
    request.add_header("User-Agent", "HelsinkiRadar/1.0")
    request.add_header("Cache-Control", "no-cache")
    if body is not None:
        request.add_header("Content-Type", "application/json; charset=utf-8")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT, context=context) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:
            return None
        if not raw:
            return None
    except Exception:
        return None
    if not raw:
        return []
    text = raw.decode("utf-8", "ignore").strip()
    if is_blank_null(text):
        return []
    if text.startswith("/*"):
        start = text.find("(")
        end = text.rfind(")")
        if start >= 0 and end > start:
            text = text[start + 1 : end]
    try:
        parsed = json.loads(text)
    except Exception:
        return None if "<html" in text.lower() else text
    return [] if parsed is None else parsed


def parse_gviz(document: object) -> list[dict]:
    if not isinstance(document, dict):
        return []
    table = document.get("table") or {}
    cols = table.get("cols") or []
    labels = [clean_text(col.get("label") or col.get("id")) for col in cols]
    rows: list[dict] = []
    for row in table.get("rows") or []:
        cells = row.get("c") or []
        item: dict = {}
        for index, cell in enumerate(cells):
            label = labels[index] if index < len(labels) else "col{}".format(index)
            value = ""
            if isinstance(cell, dict):
                value = cell.get("v")
            item[label] = value
        packed = pack_lead(item)
        if packed:
            rows.append(packed)
    return rows


def load_cloud_leads() -> list[dict]:
    sheety = http_call("GET", API_URL)
    leads = as_leads_list(sheety)
    if leads:
        return leads
    sheet = http_call("GET", SHEET1_GET_URL)
    leads = as_leads_list(sheet)
    if leads:
        return leads
    parsed = parse_gviz(http_call("GET", GVIZ_URL))
    return parsed if parsed else []


def delete_lead_from_sheet(lead_id: object) -> bool:
    row_id = clean_text(lead_id)
    if not row_id:
        return False
    url = API_URL + "/" + row_id
    request = urllib.request.Request(url, method="DELETE")
    request.add_header("User-Agent", "HelsinkiRadar/1.0")
    request.add_header("Accept", "application/json, text/plain, */*")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT, context=context) as response:
            response.read()
        return True
    except urllib.error.HTTPError as exc:
        return 200 <= int(exc.code) < 300
    except Exception:
        return False


def render_google_map(address: str) -> None:
    encoded_address = urllib.parse.quote(address + ", Helsinki, Finland")
    src = "https://maps.google.com/maps?q=" + encoded_address + "&output=embed"
    html = (
        '<iframe width="100%" height="140" frameborder="0" '
        'style="border:0; border-radius:8px; background-color:#ffffff;" '
        'src="' + src + '"></iframe>'
    )
    st.components.v1.html(html, height=145)


st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp { background: #0f172a; }
    h1 { color: #f8fafc !important; }
    .addr-line, .hours-line { display: block; margin: 0 0 0.35rem 0; color: #e2e8f0; }
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
st.write("### 🌐 Synchronisierte Google-Sheets-Pipeline (Echtzeit-Abgleich zwischen PC und Tablet)")

all_leads = load_cloud_leads()
if not isinstance(all_leads, list):
    all_leads = []

st.caption("Google Sheets / Sheety · {} Lead(s) geladen.".format(len(all_leads)))

st.subheader("Distance")
filter_left, filter_right = st.columns(2)
with filter_left:
    home_mode = bool(st.session_state.get("home_mode_toggle", True))
    st.slider(
        "Max walking distance from YOUR location (meters)",
        min_value=100,
        max_value=6000,
        value=6000,
        step=50,
        disabled=home_mode,
        key="max_distance",
    )
    st.checkbox("🏠 Home Mode (Show all prepared leads)", value=True, key="home_mode_toggle")
    home_mode = bool(st.session_state.get("home_mode_toggle", True))
with filter_right:
    industry_keyword = st.text_input(
        "Industry Keyword Filter (e.g., Ravintola, Cafe, Barber)",
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
        blob = "{} {} {}".format(packed["name"], packed["address"], packed["district"]).lower()
        if keyword not in blob:
            continue
    if not home_mode and distance_m > float(st.session_state.get("max_distance", 6000)):
        continue
    packed["latitude"] = lat
    packed["longitude"] = lon
    packed["distance_m"] = distance_m
    visible.append(packed)

visible.sort(key=lambda item: (0 if item["status"] == STATUSES[0] else 1, item["distance_m"], item["name"]))

st.markdown("---")
st.subheader("Active Lead Pipeline")
st.caption("{} sichtbar · {} in Google Sheets.".format(len(visible), len(all_leads)))

if not visible:
    st.info("Keine Leads sichtbar. Home Mode aktivieren oder unten einen Lead speichern.")

for idx, lead in enumerate(visible):
    uid = lead["sid"]
    status_key = "status_{}".format(uid)
    notes_key = "notes_{}".format(uid)
    if status_key not in st.session_state:
        st.session_state[status_key] = lead["status"]
    if notes_key not in st.session_state:
        st.session_state[notes_key] = lead["notes"]

    with st.container(border=True):
        left, right = st.columns([1.3, 1.0])
        with left:
            st.markdown("### {}".format(lead["name"]))
            st.markdown(
                "<div class='addr-line'>Address: {}, Helsinki</div>".format(lead["address"]),
                unsafe_allow_html=True,
            )
            st.markdown(
                "<span class='district-badge'>District: {}</span>".format(lead["district"]),
                unsafe_allow_html=True,
            )
            if home_mode:
                st.markdown("Distance to you: N/A")
            else:
                meters = int(round(lead["distance_m"]))
                minutes = walking_minutes(lead["distance_m"])
                st.markdown("Distance to you: {} m (ca. {} min walk)".format(meters, minutes))
        with right:
            st.markdown(
                "<div class='hours-line'>Visiting Hours: <code>{}</code></div>".format(lead["hours"]),
                unsafe_allow_html=True,
            )
            geo_url = native_geo_url(lead["latitude"], lead["longitude"])
            st.markdown(
                '<a class="nav-link" href="{}" target="_blank" rel="noopener noreferrer">🗺️ Navigation</a>'.format(geo_url),
                unsafe_allow_html=True,
            )
            render_google_map(lead["address"])

        demo_href = ensure_https(lead["website"])
        if website_is_todo(lead["website"]) or not demo_href:
            st.button("⚠️ Website to be done", key="todo_web_{}".format(uid), disabled=True, use_container_width=True)
        else:
            st.link_button(
                "🌐 Open Demo Website",
                url=demo_href,
                type="primary",
                use_container_width=True,
            )

        st.selectbox("Visit Status", options=STATUSES, key=status_key)
        st.text_area("📝 Field Notes (e.g. Email, Mobile):", key=notes_key)
        if st.button("💾 Save Note", key="save_note_{}".format(uid), use_container_width=True, type="primary"):
            payload = {
                "sheet1": {
                    "name": lead["name"],
                    "address": lead["address"],
                    "website": lead["website"],
                    "hours": lead["hours"],
                }
            }
            http_call("POST", API_URL, payload)
            st.rerun()

        if st.button("❌ Lead aus Pipeline löschen", key="delete_{}".format(idx), type="secondary"):
            delete_lead_from_sheet(lead["id"])
            st.rerun()

st.markdown("---")
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=True):
    st.caption("Nur Name und Adresse sind Pflicht. Speichern schreibt in Google Sheets.")
    with st.form("google_sheets_sync_form", clear_on_submit=True):
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
            infer_district(add_addr)
            payload = {
                "sheet1": {
                    "name": add_name,
                    "address": add_addr,
                    "website": add_link,
                    "hours": add_hours,
                }
            }
            request = urllib.request.Request(
                API_URL,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
            )
            request.add_header("Content-Type", "application/json; charset=utf-8")
            request.add_header("User-Agent", "HelsinkiRadar/1.0")
            context = ssl.create_default_context()
            try:
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT, context=context) as response:
                    response.read()
            except Exception:
                pass
            st.rerun()
