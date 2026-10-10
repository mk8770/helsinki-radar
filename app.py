from __future__ import annotations

import io
import json
import math
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

CSV_PATH = Path(__file__).resolve().parent / "samples.csv"
HELSINKI_CENTRAL = (60.1708, 24.9414)
WALK_METERS_PER_MIN = 80.0
WEBSITE_TODO = "Website to be done"
HOURS_FALLBACK = "12:00 - 20:00"
HTTP_TIMEOUT = 10

# Unique app identifier — every device uses the same named cloud slot.
REPO_NAME = "helsinki-radar"
KV_APP_KEY = "helsinki-radar"
KV_BIN_ITEM = "binid"
KV_GET = f"https://keyvalue.immanuel.co/api/KeyVal/GetValue/{KV_APP_KEY}/{KV_BIN_ITEM}"
KV_PUT_PREFIX = f"https://keyvalue.immanuel.co/api/KeyVal/UpdateValue/{KV_APP_KEY}/{KV_BIN_ITEM}/"
BLOB_API = "https://superjsonblob.com/api/jsonBlob"
RENTRY_URL = "helsinki-radar"
RENTRY_EDIT_CODE = "radarsync"
EMPTY_CLOUD = {"app": REPO_NAME, "leads": []}

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


def http_call(
    method: str,
    url: str,
    payload: object | None = None,
    form: dict[str, str] | None = None,
) -> tuple[int, object | None]:
    body: bytes | None = None
    content_type = ""
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        content_type = "application/x-www-form-urlencoded"
    elif payload is not None:
        body = json.dumps(payload).encode("utf-8")
        content_type = "application/json"
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Accept", "application/json, text/plain, */*")
    request.add_header("User-Agent", "HelsinkiRadar/1.0")
    if content_type:
        request.add_header("Content-Type", content_type)
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT, context=context) as response:
            status = int(response.status)
            raw = response.read()
            location = response.headers.get("Location") or response.headers.get("location") or ""
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        return int(exc.code), {"error": str(exc), "body": raw.decode("utf-8", "ignore")[:400]}
    except Exception as exc:
        return 0, {"error": str(exc)}
    text = raw.decode("utf-8", "ignore") if raw else ""
    if not text:
        return status, {"location": location} if location else None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return status, text
    if location and isinstance(parsed, dict) and "location" not in parsed:
        parsed["location"] = location
    elif location and not isinstance(parsed, dict):
        return status, {"data": parsed, "location": location}
    return status, parsed


def clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text.strip().strip('"')


def kv_read_bin_id() -> str:
    status, data = http_call("GET", KV_GET)
    if status != 200:
        return ""
    if isinstance(data, str):
        return clean_text(data)
    if isinstance(data, dict):
        return clean_text(data.get("value") or data.get("body") or "")
    return ""


def kv_write_bin_id(bin_id: str) -> bool:
    token = clean_text(bin_id)
    if not token:
        return False
    status, _ = http_call("POST", KV_PUT_PREFIX + urllib.parse.quote(token, safe="-"))
    return status == 200


def blob_get(bin_id: str) -> dict | None:
    status, data = http_call("GET", f"{BLOB_API}/{bin_id}")
    if status == 200 and isinstance(data, dict) and "error" not in data:
        return data
    return None


def blob_put(bin_id: str, document: dict) -> bool:
    status, _ = http_call("PUT", f"{BLOB_API}/{bin_id}", document)
    return status in {200, 201}


def blob_create() -> str:
    status, data = http_call("POST", BLOB_API, dict(EMPTY_CLOUD))
    if status not in {200, 201}:
        return ""
    if isinstance(data, dict):
        token = clean_text(data.get("id"))
        if token:
            return token
        location = clean_text(data.get("location"))
        if location:
            return location.rstrip("/").split("/")[-1]
    return ""


def rentry_fetch_text() -> str | None:
    status, data = http_call(
        "POST",
        f"https://rentry.co/api/fetch/{RENTRY_URL}",
        form={"edit_code": RENTRY_EDIT_CODE},
    )
    if status != 200 or not isinstance(data, dict):
        return None
    if str(data.get("status")) not in {"200", "ok", "OK"}:
        return None
    content = data.get("content")
    if isinstance(content, dict):
        return str(content.get("text") or "")
    if isinstance(content, str):
        return content
    return None


def rentry_save_text(text: str) -> bool:
    status, data = http_call(
        "POST",
        f"https://rentry.co/api/edit/{RENTRY_URL}",
        form={"edit_code": RENTRY_EDIT_CODE, "text": text},
    )
    if status == 200 and isinstance(data, dict) and str(data.get("status")) in {"200", "ok", "OK"}:
        return True
    created, create_data = http_call(
        "POST",
        "https://rentry.co/api/new",
        form={"url": RENTRY_URL, "edit_code": RENTRY_EDIT_CODE, "text": text},
    )
    if created == 200 and isinstance(create_data, dict) and str(create_data.get("status")) in {"200", "ok", "OK"}:
        return True
    status, data = http_call(
        "POST",
        f"https://rentry.co/api/edit/{RENTRY_URL}",
        form={"edit_code": RENTRY_EDIT_CODE, "text": text},
    )
    return status == 200 and isinstance(data, dict) and str(data.get("status")) in {"200", "ok", "OK"}


def parse_cloud_document(document: object) -> list[dict]:
    rows: list = []
    if isinstance(document, dict):
        if isinstance(document.get("leads"), list):
            rows = document["leads"]
        elif isinstance(document.get("data"), dict) and isinstance(document["data"].get("leads"), list):
            rows = document["data"]["leads"]
        elif isinstance(document.get("data"), list):
            rows = document["data"]
    elif isinstance(document, list):
        rows = document
    elif isinstance(document, str) and document.strip():
        try:
            return parse_cloud_document(json.loads(document))
        except json.JSONDecodeError:
            return []
    leads: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = clean_text(row.get("name"))
        address = clean_text(row.get("address"))
        if not name or not address:
            continue
        leads.append(
            empty_lead(
                name=name,
                address=address,
                website=row.get("website", ""),
                hours=row.get("hours", ""),
                status=row.get("status", ""),
                notes=row.get("notes", ""),
                src="cloud",
            )
        )
    return leads


def ensure_cloud_storage() -> dict:
    """Create the shared helsinki-radar cloud bin automatically if it does not exist."""
    cached = st.session_state.get("cloud_bin_id")
    if cached:
        document = blob_get(cached)
        if document is not None:
            return {"backend": "blob", "bin_id": cached, "document": document, "error": ""}

    bin_id = kv_read_bin_id()
    if bin_id:
        document = blob_get(bin_id)
        if document is not None:
            st.session_state["cloud_bin_id"] = bin_id
            return {"backend": "blob", "bin_id": bin_id, "document": document, "error": ""}

    bin_id = blob_create()
    if bin_id:
        kv_write_bin_id(bin_id)
        st.session_state["cloud_bin_id"] = bin_id
        document = blob_get(bin_id) or dict(EMPTY_CLOUD)
        return {"backend": "blob", "bin_id": bin_id, "document": document, "error": ""}

    text = rentry_fetch_text()
    if text is None:
        if rentry_save_text(json.dumps(EMPTY_CLOUD)):
            text = rentry_fetch_text() or json.dumps(EMPTY_CLOUD)
        else:
            return {"backend": "", "bin_id": "", "document": dict(EMPTY_CLOUD), "error": "Cloud bin could not be created"}
    try:
        document = json.loads(text) if text.strip() else dict(EMPTY_CLOUD)
    except json.JSONDecodeError:
        document = dict(EMPTY_CLOUD)
    st.session_state["cloud_backend"] = "rentry"
    return {"backend": "rentry", "bin_id": RENTRY_URL, "document": document, "error": ""}


def save_cloud_document(document: dict) -> str:
    bin_id = clean_text(st.session_state.get("cloud_bin_id"))
    if bin_id and blob_put(bin_id, document):
        rentry_save_text(json.dumps(document, ensure_ascii=False))
        return ""
    storage = ensure_cloud_storage()
    if storage["error"]:
        return storage["error"]
    if storage["backend"] == "blob" and blob_put(storage["bin_id"], document):
        st.session_state["cloud_bin_id"] = storage["bin_id"]
        rentry_save_text(json.dumps(document, ensure_ascii=False))
        return ""
    if rentry_save_text(json.dumps(document, ensure_ascii=False)):
        return ""
    return "Cloud PUT failed"


def fetch_cloud_leads() -> tuple[list[dict], str]:
    storage = ensure_cloud_storage()
    if storage["error"]:
        return [], storage["error"]
    return parse_cloud_document(storage["document"]), ""


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


def pick_col(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    normalized = {str(col).strip().lower(): col for col in df.columns}
    for cand in candidates:
        if cand in normalized:
            return normalized[cand]
    for key, original in normalized.items():
        for cand in candidates:
            if cand in key or key in cand:
                return original
    return None


def load_samples_csv() -> pd.DataFrame:
    if not CSV_PATH.exists():
        st.error("Could not find samples.csv next to the app.")
        st.stop()
    raw = CSV_PATH.read_bytes()
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="utf-8-sig").fillna("")
    except pd.errors.ParserError:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="utf-8-sig", sep=";").fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        df[col] = df[col].map(clean_text)
    return df.reset_index(drop=True)


def empty_lead(
    name: str,
    address: str,
    website: str = "",
    hours: str = "",
    status: str = "",
    notes: str = "",
    src: str = "cloud",
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
        "src": src,
        "sid": f"a_{address_key(address_text)[:24] or 'unknown'}",
    }


def serialize_lead(lead: dict) -> dict:
    return {
        "name": clean_text(lead.get("name")),
        "address": clean_text(lead.get("address")),
        "website": normalize_website(lead.get("website")),
        "hours": normalize_hours(lead.get("hours")),
        "status": normalize_status(lead.get("status", "")),
        "notes": clean_text(lead.get("notes")),
        "district": infer_district(clean_text(lead.get("address"))),
    }


def put_cloud_leads(leads: list[dict]) -> str:
    packed = [
        serialize_lead(lead)
        for lead in leads
        if clean_text(lead.get("name")) and clean_text(lead.get("address"))
    ]
    return save_cloud_document({"app": REPO_NAME, "leads": packed})


def upsert_cloud_lead(lead: dict) -> str:
    cloud_leads, err = fetch_cloud_leads()
    if err:
        return err
    merged: dict[str, dict] = {}
    for item in cloud_leads:
        merged[address_key(item["address"])] = serialize_lead(item)
    merged[address_key(lead["address"])] = serialize_lead(lead)
    return put_cloud_leads(list(merged.values()))


def leads_from_csv(df: pd.DataFrame) -> list[dict]:
    name_col = pick_col(df, ("company-name", "company_name", "name", "firma", "company"))
    addr_col = pick_col(df, ("street-address", "street_address", "address", "adresse", "street"))
    link_col = pick_col(df, ("sample-link", "sample_link", "website", "url", "link"))
    hours_col = pick_col(df, ("visiting-hours", "visiting_hours", "hours"))
    if name_col is None or addr_col is None:
        st.error("samples.csv needs Company-Name and Street-Address columns.")
        st.stop()
    leads: list[dict] = []
    for _, row in df.iterrows():
        name = clean_text(row[name_col])
        address = clean_text(row[addr_col])
        if not name or not address:
            continue
        website = clean_text(row[link_col]) if link_col else ""
        hours = clean_text(row[hours_col]) if hours_col else ""
        leads.append(
            empty_lead(
                name=name,
                address=address,
                website=website,
                hours=hours,
                src="csv",
            )
        )
    return leads


def merge_equal_weight(csv_leads: list[dict], cloud_leads: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for lead in csv_leads:
        merged[address_key(lead["address"])] = dict(lead)
    for lead in cloud_leads:
        merged[address_key(lead["address"])] = dict(lead)
    return list(merged.values())


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
    "Prepared leads come from `samples.csv`. Manual adds and edits sync automatically "
    f"through the shared **{REPO_NAME}** cloud bin — no database account, no URL copying. "
    "Same street address = cloud record overwrites the CSV row on every device."
)

csv_df = load_samples_csv()
csv_leads = leads_from_csv(csv_df)
cloud_leads, cloud_error = fetch_cloud_leads()
all_leads = merge_equal_weight(csv_leads, cloud_leads)

if cloud_error:
    st.warning(f"Cloud sync unavailable right now ({cloud_error}). Showing samples.csv only.")
else:
    st.caption(f"Cloud sync OK · {len(cloud_leads)} manual/edited lead(s) in the {REPO_NAME} database.")

st.subheader("Distance")
filter_left, filter_right = st.columns(2)
with filter_left:
    home_mode = st.session_state.get("home_mode", False)
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
    home_mode = st.session_state["home_mode"]
with filter_right:
    industry_keyword = st.text_input(
        "Industry Keyword Filter (e.g., Ravintola, Café, Barber)",
        key="industry_keyword",
    )
    district_filter = st.selectbox("District Filter", options=DISTRICT_OPTIONS, key="district_filter")

origin_lat, origin_lon = HELSINKI_CENTRAL
keyword = industry_keyword.strip().lower()

enriched_rows: list[dict] = []
for lead in all_leads:
    lat, lon = coords_for_address(lead["address"])
    distance_m = haversine_m(origin_lat, origin_lon, lat, lon)
    if not district_matches(lead["district"], district_filter):
        continue
    if keyword:
        blob = f"{lead['name']} {lead['address']} {lead['district']}".lower()
        if keyword not in blob:
            continue
    if not home_mode and distance_m > float(st.session_state["max_distance"]):
        continue
    item = dict(lead)
    item["latitude"] = lat
    item["longitude"] = lon
    item["distance_m"] = distance_m
    enriched_rows.append(item)

enriched_rows.sort(
    key=lambda item: (0 if item["status"] == STATUSES[0] else 1, item["distance_m"], item["name"])
)

st.markdown("---")
st.subheader("Active Lead Pipeline")
st.caption(
    f"{len(enriched_rows)} lead(s) visible "
    f"({len(csv_leads)} from samples.csv + {len(cloud_leads)} from cloud; same address = cloud wins)."
)

if not enriched_rows:
    st.info("No leads match these filters. Turn on Home Mode or relax the filters.")

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
                            save_err = upsert_cloud_lead(
                                empty_lead(
                                    name=new_name,
                                    address=new_addr,
                                    website=new_link,
                                    hours=new_hours,
                                    status=st.session_state[status_key],
                                    notes=st.session_state[notes_key],
                                )
                            )
                            if save_err:
                                st.error(save_err)
                            else:
                                st.session_state["editing_sid"] = ""
                                st.rerun()
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
                save_err = upsert_cloud_lead(
                    empty_lead(
                        name=lead["name"],
                        address=lead["address"],
                        website=lead["website"],
                        hours=lead["hours"],
                        status=chosen_status,
                        notes=st.session_state[notes_key],
                    )
                )
                if save_err:
                    st.error(save_err)
                else:
                    st.rerun()

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
            save_err = upsert_cloud_lead(
                empty_lead(
                    name=lead["name"],
                    address=lead["address"],
                    website=lead["website"],
                    hours=lead["hours"],
                    status=st.session_state[status_key],
                    notes=st.session_state[notes_key],
                )
            )
            if save_err:
                st.error(save_err)
            else:
                st.rerun()

st.markdown("---")
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=False):
    st.caption(
        "Nur Name und Adresse sind Pflicht. Speichern schreibt den Lead in die "
        f"{REPO_NAME}-Cloud — sichtbar auf jedem Gerät mit dem normalen Lesezeichen."
    )
    with st.form("automated_cloud_form", clear_on_submit=True):
        add_name = st.text_input("Name des Geschäfts / Firma", key="form_add_name")
        add_addr = st.text_input("Adresse (z.B. Hämeentie 38)", key="form_add_addr")
        add_link = st.text_input("Website / Demo-Link", value="https://", key="form_add_link")
        add_hours = st.text_input("Visiting Hours", value="12:00 - 20:00", key="form_add_hours")
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
            st.warning("Bitte Name des Geschäfts und Adresse ausfüllen.")
        else:
            new_lead = empty_lead(
                name=add_name,
                address=add_addr,
                website=add_link,
                hours=add_hours,
            )
            new_lead["district"] = infer_district(add_addr)
            save_err = upsert_cloud_lead(new_lead)
            if save_err:
                st.error(save_err)
            else:
                st.rerun()
