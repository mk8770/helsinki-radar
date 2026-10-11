import html
import json
import math
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

# Ihre VOLLSTÄNDIGE, permanente Sheety-Verbindung direkt zu Ihrem Google Sheet
API_URL = "https://api.sheety.co/af5130fd4340e5b69490c1da248a8d72/websiteLeads/sheet1"

st.set_page_config(page_title="🎯 Helsinki Website Leads", layout="wide", initial_sidebar_state="collapsed")

# INTERNER SOFORT-SPEICHER & BEARBEITUNGS-STATE
if "local_leads" not in st.session_state:
    st.session_state["local_leads"] = []
if "edit_lead_id" not in st.session_state:
    st.session_state["edit_lead_id"] = None
if "geo_cache" not in st.session_state:
    st.session_state["geo_cache"] = {}
if "user_origin" not in st.session_state:
    st.session_state["user_origin"] = None

# 1. Daten aus Google Sheets (Sheety) laden
SHEET_ID = "1Fw6T2gxui7XCTYskT90890poXIIgZ6SxLytUA1eMtns"
OPENSHEET_URL = "https://opensheet.elk.sh/" + SHEET_ID + "/sheet1"
GVIZ_URL = "https://docs.google.com/spreadsheets/d/" + SHEET_ID + "/gviz/tq?tqx=out:json"


def _row_value(row, *keys):
    lowered = {}
    for k, v in row.items():
        lowered[str(k).strip().lower()] = v
    for key in keys:
        val = lowered.get(key.strip().lower())
        if val not in (None, ""):
            return val
    return ""


def _normalize_cloud_row(row):
    return {
        "id": row.get("id"),
        "name": _row_value(row, "name"),
        "address": _row_value(row, "address", "adress"),
        "website": _row_value(row, "website", "website "),
        "hours": _row_value(row, "hours"),
        "notes": _row_value(row, "notes"),
    }


def _load_opensheet():
    req = urllib.request.Request(OPENSHEET_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if isinstance(rows, list):
        return [_normalize_cloud_row(r) for r in rows if isinstance(r, dict)]
    return []


def _load_gviz():
    req = urllib.request.Request(GVIZ_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        text = response.read().decode("utf-8")
    start = text.find("{")
    end = text.rfind("}")
    data = json.loads(text[start:end + 1])
    table = data.get("table", {})
    cols = [str(c.get("label") or "").strip().lower() for c in table.get("cols", [])]
    out = []
    for row in table.get("rows", []):
        item = {}
        cells = row.get("c") or []
        for idx, col in enumerate(cols):
            cell = cells[idx] if idx < len(cells) else None
            item[col or f"col{idx}"] = (cell or {}).get("v") if cell else ""
        out.append(_normalize_cloud_row(item))
    return out


def _http_json_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8")


def load_leads_from_sheet():
    try:
        data = json.loads(_http_json_get(API_URL))
        if "sheet1" in data and isinstance(data["sheet1"], list) and data["sheet1"]:
            return [_normalize_cloud_row(r) for r in data["sheet1"] if isinstance(r, dict)]
    except Exception:
        pass
    try:
        rows = _load_gviz()
        if rows:
            return rows
    except Exception:
        pass
    try:
        rows = _load_opensheet()
        if rows:
            return rows
    except Exception:
        pass
    return []

# 2. Neuen Lead live in Google Sheets schreiben
def save_lead_to_sheet(name, address, website, hours):
    try:
        payload = {
            "sheet1": {
                "name": name,
                "address": address,
                "website": website,
                "hours": hours,
                "notes": ""
            }
        }
        json_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            API_URL, 
            data=json_data, 
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, 
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return True
    except Exception:
        return False

# 3. Existierenden Lead (Adresse, Name, Website, Hours oder Notes) aktualisieren
def update_lead_in_sheet(lead_id, name, address, website, hours, notes):
    try:
        payload = {
            "sheet1": {
                "name": name,
                "address": address,
                "website": website,
                "hours": hours,
                "notes": notes
            }
        }
        json_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{API_URL}/{lead_id}", 
            data=json_data, 
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, 
            method="PUT"
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return True
    except Exception:
        return False

# 4. Lead aus dem Google Sheet löschen
def delete_lead_from_sheet(lead_id):
    try:
        req = urllib.request.Request(
            f"{API_URL}/{lead_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            method="DELETE"
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return True
    except Exception:
        return False

# Stadtviertel-Zuweisung für Helsinki (Kalasatama- & polku-Erkennung)
def parse_district(address_str):
    if not address_str:
        return "Unknown"
    addr = str(address_str).lower()
    if any(k in addr for k in ["kalasatama", "redi", "työpajankatu", "leonkatu", "hermannin rantatie", "polku"]):
        return "Kalasatama"
    if any(k in addr for k in ["linja", "hämeentie", "helsinginkatu", "vaasankatu", "porthaninkatu"]):
        return "Kallio"
    if any(k in addr for k in ["runeberginkatu", "topeliuksenkatu", "töölönkatu", "mechelininkatu"]):
        return "Töölö"
    return "Central District"


def haversine_m(origin, destination):
    lat1, lon1 = origin
    lat2, lon2 = destination
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, a)))


def geocode_address(address):
    key = str(address or "").strip().lower()
    if not key:
        return None
    cache = st.session_state["geo_cache"]
    if key in cache:
        return cache[key]
    query = str(address).strip()
    if "helsinki" not in query.lower():
        query = query + ", Helsinki, Finland"
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": "1", "countrycodes": "fi"}
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HelsinkiLeads/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data:
            coords = (float(data[0]["lat"]), float(data[0]["lon"]))
            cache[key] = coords
            return coords
    except Exception:
        pass
    cache[key] = None
    return None


def get_user_origin():
    if st.session_state.get("user_origin"):
        return st.session_state["user_origin"]
    try:
        from streamlit_js_eval import get_geolocation
    except Exception:
        return None
    loc = get_geolocation()
    if not isinstance(loc, dict):
        return None
    coords = loc.get("coords") or loc
    try:
        lat = float(coords.get("latitude"))
        lon = float(coords.get("longitude"))
    except Exception:
        return None
    origin = (lat, lon)
    st.session_state["user_origin"] = origin
    return origin


def distance_to_lead_m(address, origin):
    if not origin:
        return None
    coords = geocode_address(address)
    if not coords:
        return None
    return int(round(haversine_m(origin, coords)))


def maps_navigation_url(address, origin=None):
    query = str(address or "").strip()
    if "helsinki" not in query.lower():
        query = query + ", Helsinki"
    dest = urllib.parse.quote(query)
    if origin:
        return (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={origin[0]},{origin[1]}"
            f"&destination={dest}"
            "&travelmode=walking"
        )
    return "https://www.google.com/maps/dir/?api=1&destination=" + dest + "&travelmode=walking"


# DATENQUELLEN ZUSAMMENFÜHREN
cloud_leads = load_leads_from_sheet()
all_leads = []
seen_addresses = set()

for l in st.session_state["local_leads"]:
    all_leads.append(l)
    seen_addresses.add(l["address"].lower().strip())

if cloud_leads:
    for l in cloud_leads:
        addr = str(l.get("address") or l.get("adress") or "").lower().strip()
        if addr not in seen_addresses and l.get("name"):
            all_leads.append({
                "id": l.get("id"),
                "name": l.get("name"),
                "address": l.get("address", l.get("adress", "")),
                "website": l.get("website", "Website to be done"),
                "hours": l.get("hours", "12:00 - 20:00"),
                "notes": l.get("notes", "")
            })

st.title("🎯 Helsinki Website Leads")
st.write("### 🌐 Synchronisiertes Cloud-Dashboard (Echtzeit-Abgleich PC & Tablet via Google Sheets)")
# Filter-Bereich oben
distance_filter = st.slider("Max walking distance from YOUR location (meters)", min_value=100, max_value=6000, value=6000)
home_mode = st.checkbox("🏠 Home Mode (Show all prepared leads)", value=True, key="home_mode_widget")
selected_district_filter = st.selectbox("🌍 Filter by District", ["All Districts", "Kallio", "Töölö", "Kalasatama", "Central District"])

user_origin = get_user_origin()
if user_origin:
    loc_col, refresh_col = st.columns([4, 1])
    with loc_col:
        st.caption("Distances are measured from your current GPS position.")
    with refresh_col:
        if st.button("📍 Refresh GPS", key="refresh_gps"):
            st.session_state["user_origin"] = None
            st.rerun()
else:
    st.info("Allow location access in the browser to see walking distance from where you are standing.")

# Filter auf die Gesamtliste anwenden
filtered_leads = []
for lead in all_leads:
    district = parse_district(lead["address"])
    if selected_district_filter != "All Districts" and district != selected_district_filter:
        continue
    lead_distance = distance_to_lead_m(lead["address"], user_origin)
    lead["_distance_m"] = lead_distance
    if not home_mode and lead_distance is not None and lead_distance > float(distance_filter):
        continue
    filtered_leads.append(lead)

st.subheader(f"Active Leads in Sales Pipeline ({len(filtered_leads)})")

if not filtered_leads:
    st.info("No leads found matching the active filters. Use the form below to add a new lead!")

# Layout-Karten zeichnen
for idx, lead in enumerate(filtered_leads):
    l_id = lead.get("id")
    current_edit_id = l_id if l_id not in (None, "") else f"local-{idx}"
    
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            if st.session_state["edit_lead_id"] == current_edit_id:
                st.markdown("### ✏️ Edit Entry")
                edit_name = st.text_input("Name:", value=lead['name'], key=f"edit_name_{idx}")
                edit_addr = st.text_input("Address:", value=lead['address'], key=f"edit_addr_{idx}")
                edit_site = st.text_input("Website:", value=lead['website'], key=f"edit_site_{idx}")
                edit_hours = st.text_input("Hours:", value=lead['hours'], key=f"edit_hours_{idx}")
                
                edit_col1, edit_col2 = st.columns(2)
                with edit_col1:
                    if st.button("💾 Save Changes", key=f"save_edit_{idx}", type="primary"):
                        new_name = edit_name.strip()
                        new_addr = edit_addr.strip()
                        new_site = edit_site.strip() or "Website to be done"
                        new_hours = edit_hours.strip() or "12:00 - 20:00"
                        old_addr = str(lead.get("address") or "").lower().strip()
                        updated_local = False
                        new_local = []
                        for row in st.session_state["local_leads"]:
                            if str(row.get("address") or "").lower().strip() == old_addr:
                                merged = dict(row)
                                merged.update({
                                    "id": l_id,
                                    "name": new_name,
                                    "address": new_addr,
                                    "website": new_site,
                                    "hours": new_hours,
                                    "notes": lead.get("notes", ""),
                                })
                                new_local.append(merged)
                                updated_local = True
                            else:
                                new_local.append(row)
                        if not updated_local:
                            new_local.append({
                                "id": l_id,
                                "name": new_name,
                                "address": new_addr,
                                "website": new_site,
                                "hours": new_hours,
                                "notes": lead.get("notes", ""),
                            })
                        st.session_state["local_leads"] = new_local
                        if l_id:
                            update_lead_in_sheet(l_id, new_name, new_addr, new_site, new_hours, lead.get("notes", ""))
                        st.session_state["edit_lead_id"] = None
                        st.success("Successfully updated!")
                        st.rerun()
                with edit_col2:
                    if st.button("Cancel", key=f"cancel_edit_{idx}"):
                        st.session_state["edit_lead_id"] = None
                        st.rerun()
            else:
                distance_m = lead.get("_distance_m")
                distance_label = f"{distance_m} m" if distance_m is not None else "N/A"
                safe_name = html.escape(str(lead["name"]))
                st.markdown(
                    f'<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;">'
                    f'<h2 style="margin:0;">{safe_name}</h2>'
                    f'<span style="color:#16a34a;font-size:2rem;font-weight:800;line-height:1;">{distance_label}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.link_button(
                    "🧭 Navigation",
                    maps_navigation_url(lead["address"], user_origin),
                    type="primary",
                )
                st.write(f"📍 **Address:** {lead['address']} ({parse_district(lead['address'])})")
                st.write(f"⏱️ **Visiting Hours:** {lead['hours']}")
                
                if lead['website'] in ["", "Website to be done", "https://"]:
                    st.button("⚠️ Website to be done", key=f"disabled_{idx}", disabled=True)
                else:
                    st.link_button("🌐 Open Demo Website", lead['website'], type="primary")
                
                # Status extrahieren
                saved_notes = lead.get("notes", "")
                current_status = "Not Visited Yet"
                display_notes = saved_notes
                if saved_notes.startswith("[") and "]" in saved_notes:
                    parts = saved_notes.split("]", 1)
                    current_status = parts[0].replace("[", "").strip()
                    display_notes = parts[1].strip()
                
                status_options = ["Not Visited Yet", "In Progress", "Interested", "Not Interested"]
                default_status_idx = status_options.index(current_status) if current_status in status_options else 0
                
                selected_status = st.selectbox("Status", status_options, index=default_status_idx, key=f"status_{idx}")
                typed_notes = st.text_area("📝 Field Notes", value=display_notes, key=f"notes_{idx}", height=70)
                
                # Englische Button-Reihe für die Mitarbeiterin
                btn_col1, btn_col2, btn_col3 = st.columns(3)
                with btn_col1:
                    if st.button("💾 Save Note", key=f"save_btn_{idx}", type="primary", use_container_width=True):
                        combined_text = f"[{selected_status}] {typed_notes}" if typed_notes else f"[{selected_status}]"
                        if l_id:
                            if update_lead_in_sheet(l_id, lead['name'], lead['address'], lead['website'], lead['hours'], combined_text):
                                st.success("Note saved!")
                                st.rerun()
                with btn_col2:
                    if st.button("✏️ Edit", key=f"edit_btn_{idx}", use_container_width=True):
                        st.session_state["edit_lead_id"] = current_edit_id
                        st.rerun()
                with btn_col3:
                    if st.button("❌ Delete", key=f"delete_{idx}", type="secondary", use_container_width=True):
                        st.session_state["local_leads"] = [x for x in st.session_state["local_leads"] if x["address"].lower().strip() != lead["address"].lower().strip()]
                        if l_id:
                            delete_lead_from_sheet(l_id)
                        st.success("Lead deleted!")
                        st.rerun()
        
        with col2:
            # Absolut korrekter Google-Maps Link ohne Variablenfehler!
            encoded_address = urllib.parse.quote(str(lead['address']) + ", Helsinki")
            map_src = f"https://maps.google.com/maps?q={encoded_address}&output=embed"


            st.components.v1.iframe(map_src, height=160)

st.divider()

# Formular zum manuellen Hinzufügen
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=True):
    with st.form("google_sheets_sync_form", clear_on_submit=True):
        add_name = st.text_input("Name des Geschäfts / Firma:")
        add_addr = st.text_input("Adresse (z.B. Työpajankatu 12):")
        add_link = st.text_input("Website / Demo-Link (optional):", value="https://")
        add_hours = st.text_input("Visiting Hours (optional):", value="12:00 - 20:00")
        
        submitted = st.form_submit_button("💾 LEAD DASHBOARD-WEIT SPEICHERN", use_container_width=True, type="primary")
        
        if submitted:
            if not add_name.strip() or not add_addr.strip():
                st.error("Name und Adresse sind zwingend erforderlich!")
            else:
                final_link = "Website to be done" if add_link.strip() in ["", "https://", "https://."] else add_link.strip()
                final_hours = "12:00 - 20:00" if not add_hours.strip() else add_hours.strip()
                
                new_lead_dict = {
                    "name": add_name.strip(),
                    "address": add_addr.strip(),
                    "website": final_link,
                    "hours": final_hours,
                    "notes": ""
                }
                
                st.session_state["local_leads"].append(new_lead_dict)
                save_lead_to_sheet(add_name.strip(), add_addr.strip(), final_link, final_hours)
                st.success("Erfolgreich gespeichert!")
                st.rerun()
