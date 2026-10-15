import html
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import streamlit as st

# Ihre VOLLSTÄNDIGE, permanente Sheety-Verbindung direkt zu Ihrem Google Sheet
API_URL = "https://api.sheety.co/af5130fd4340e5b69490c1da248a8d72/websiteLeads/sheet1"
# Optional: Google Apps Script Web App URL (anyone-access) used when Sheety quota is exceeded.
# Paste the /exec URL here or in Streamlit secrets as GAS_WEBAPP_URL.
GAS_WEBAPP_URL = ""

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
if "ls_hydrated" not in st.session_state:
    st.session_state["ls_hydrated"] = False
if "deleted_addrs" not in st.session_state:
    st.session_state["deleted_addrs"] = []
if "pending_sync" not in st.session_state:
    st.session_state["pending_sync"] = {}

LS_KEY = "helsinki_leads_v1"

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
    gviz_url = GVIZ_URL + "&nocache=" + str(int(time.time()))
    req = urllib.request.Request(gviz_url, headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"})
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

def _secret_or_default(key, default=""):
    try:
        value = st.secrets[key]
        if value:
            return str(value).strip()
    except Exception:
        pass
    return default


class _KeepPostRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code in (301, 302, 303, 307, 308) and req.get_method() == "POST":
            return urllib.request.Request(
                newurl.replace(" ", "%20"),
                data=req.data,
                headers={"Content-Type": "text/plain;charset=utf-8", "User-Agent": "Mozilla/5.0"},
                method="POST",
            )
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl
        )


def _post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "text/plain;charset=utf-8", "User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(_KeepPostRedirectHandler)
    try:
        with opener.open(req, timeout=20) as response:
            return response.getcode(), response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = ""
        try:
            detail = err.read().decode("utf-8")
        except Exception:
            detail = str(err)
        raise RuntimeError("HTTP {0}: {1}".format(err.code, detail))


SYNC_MARKER = "__helsinki_sync__"


def get_write_url():
    return (
        _secret_or_default("GAS_WEBAPP_URL", GAS_WEBAPP_URL)
        or str(st.session_state.get("gas_url") or "").strip()
    )


def _addr_key(row_or_addr):
    if isinstance(row_or_addr, dict):
        return str(row_or_addr.get("address") or row_or_addr.get("adress") or "").lower().strip()
    return str(row_or_addr or "").lower().strip()


def _remember_pending(lead):
    addr = _addr_key(lead)
    if not addr:
        return
    pending = dict(st.session_state.get("pending_sync") or {})
    pending[addr] = {
        "id": lead.get("id"),
        "name": lead.get("name"),
        "address": lead.get("address") or lead.get("adress") or "",
        "website": lead.get("website") or "Website to be done",
        "hours": lead.get("hours") or "12:00 - 20:00",
        "notes": lead.get("notes") or "",
    }
    st.session_state["pending_sync"] = pending


def _webhook_write(action, name, address, website="", hours="", notes=""):
    webhook = get_write_url()
    if not webhook:
        return False
    payload = {
        "action": action,
        "name": name,
        "address": address,
        "adress": address,
        "website": website,
        "hours": hours,
        "notes": notes or "",
    }
    status, raw = _post_json(webhook, payload)
    if not (200 <= int(status) < 400):
        return False
    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        parsed = {}
    if parsed.get("service") == "helsinki-leads" and parsed.get("action") is None:
        raise RuntimeError("Sheets webhook ignored the write (GET instead of POST).")
    if parsed.get("ok") is False:
        return False
    return True


# 2. Neuen Lead live in Google Sheets schreiben
def save_lead_to_sheet(name, address, website, hours, notes=""):
    try:
        if _webhook_write("upsert", name, address, website, hours, notes):
            return True, None
    except Exception as webhook_exc:
        webhook_error = str(webhook_exc)
    else:
        webhook_error = "Sheets webhook is not connected."
    payload = {
        "sheet1": {
            "name": name,
            "address": address,
            "adress": address,
            "website": website,
            "hours": hours,
            "notes": notes or "",
        }
    }
    try:
        status, _body = _post_json(API_URL, payload)
        if 200 <= int(status) < 400:
            return True, None
    except Exception as exc:
        return False, "{0} | {1}".format(webhook_error, exc)
    return False, webhook_error


# 3. Existierenden Lead (Adresse, Name, Website, Hours oder Notes) aktualisieren
def update_lead_in_sheet(lead_id, name, address, website, hours, notes):
    try:
        if _webhook_write("upsert", name, address, website, hours, notes):
            return True
    except Exception:
        pass
    if lead_id in (None, ""):
        return False
    try:
        payload = {
            "sheet1": {
                "name": name,
                "address": address,
                "website": website,
                "hours": hours,
                "notes": notes,
            }
        }
        json_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{API_URL}/{lead_id}",
            data=json_data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return True
    except Exception:
        return False


# 4. Lead aus dem Google Sheet löschen
def delete_lead_from_sheet(lead_id, address=""):
    try:
        if address and _webhook_write("delete", "", address):
            return True
    except Exception:
        pass
    if lead_id in (None, ""):
        return False
    try:
        req = urllib.request.Request(
            f"{API_URL}/{lead_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            method="DELETE",
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


def _js_eval(expression, key):
    try:
        from streamlit_js_eval import streamlit_js_eval
        return streamlit_js_eval(js_expressions=expression, key=key)
    except Exception:
        return None


def _clean_lead(row):
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "address": row.get("address") or row.get("adress") or "",
        "website": row.get("website") or "Website to be done",
        "hours": row.get("hours") or "12:00 - 20:00",
        "notes": row.get("notes") or "",
    }


def hydrate_leads_from_browser():
    if st.session_state.get("ls_hydrated"):
        return
    raw = _js_eval("localStorage.getItem('{0}')".format(LS_KEY), "load_leads_ls")
    if raw is None:
        return
    st.session_state["ls_hydrated"] = True
    if not raw or raw in ("null", "undefined"):
        return
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return
    if not isinstance(rows, list):
        return
    existing = {
        str(x.get("address") or "").lower().strip(): True
        for x in st.session_state["local_leads"]
    }
    for row in rows:
        item = _clean_lead(row)
        addr = str(item.get("address") or "").lower().strip()
        if item.get("name") == SYNC_MARKER:
            continue
        if addr and item.get("name") and addr not in existing:
            st.session_state["local_leads"].append(item)
            existing[addr] = True


def persist_leads_to_browser(leads):
    if not st.session_state.get("ls_hydrated"):
        return
    clean = [
        _clean_lead(row)
        for row in leads
        if row.get("name") and row.get("address") and row.get("name") != SYNC_MARKER
    ]
    payload = json.dumps(clean, ensure_ascii=True)
    js = "localStorage.setItem('{0}', {1})".format(LS_KEY, json.dumps(payload))
    sig = "|".join(sorted(str(x.get("address")) for x in clean))
    _js_eval(js, "persist_leads_" + str(abs(hash(sig)) % 1000000000))


# DATENQUELLEN ZUSAMMENFÜHREN
hydrate_leads_from_browser()
cloud_leads = load_leads_from_sheet()
visible_cloud = []
for row in cloud_leads or []:
    if str(row.get("name") or "").strip() == SYNC_MARKER:
        marker_url = str(row.get("address") or row.get("website") or "").strip()
        if marker_url.startswith("http"):
            st.session_state["gas_url"] = marker_url
        continue
    visible_cloud.append(row)
cloud_leads = visible_cloud
all_leads = []
seen_addresses = set()

deleted = {
    str(a).lower().strip()
    for a in (st.session_state.get("deleted_addrs") or [])
    if str(a).strip()
}
if get_write_url():
    still_deleted = []
    for addr in deleted:
        try:
            delete_lead_from_sheet(None, addr)
        except Exception:
            still_deleted.append(addr)
            continue
        still_deleted.append(addr)
    st.session_state["deleted_addrs"] = still_deleted

if cloud_leads:
    for l in cloud_leads:
        addr = _addr_key(l)
        if addr in deleted:
            continue
        if addr in seen_addresses or not l.get("name"):
            continue
        all_leads.append({
            "id": l.get("id"),
            "name": l.get("name"),
            "address": l.get("address", l.get("adress", "")),
            "website": l.get("website") or "Website to be done",
            "hours": l.get("hours") or "12:00 - 20:00",
            "notes": l.get("notes") or "",
        })
        seen_addresses.add(addr)

pending = dict(st.session_state.get("pending_sync") or {})
cleared_pending = {}
for addr, row in pending.items():
    if not addr or addr in deleted:
        continue
    cloud_row = next((x for x in all_leads if _addr_key(x) == addr), None)
    if cloud_row and str(cloud_row.get("website") or "") == str(row.get("website") or "") and str(cloud_row.get("name") or "") == str(row.get("name") or ""):
        continue
    all_leads = [x for x in all_leads if _addr_key(x) != addr]
    all_leads.append(row)
    seen_addresses.add(addr)
    cleared_pending[addr] = row
st.session_state["pending_sync"] = cleared_pending

for l in st.session_state["local_leads"]:
    addr = _addr_key(l)
    if not addr or addr in deleted or addr in seen_addresses:
        continue
    all_leads.append(l)
    seen_addresses.add(addr)

persist_leads_to_browser(all_leads)

st.title("🎯 Helsinki Website Leads")
st.write("### 🌐 Synchronisiertes Cloud-Dashboard (Echtzeit-Abgleich PC & Tablet via Google Sheets)")
if st.session_state.pop("last_save_ok", None):
    st.success("Saved to the shared Google Sheet. Refresh the phone to see the new demo link.")
last_save_error = st.session_state.pop("last_save_error", None)
if last_save_error:
    st.error(last_save_error)

if not get_write_url():
    st.warning("Multi-device saving is off. Connect the Google Sheet webhook once so phones and PCs share the same leads.")
    with st.expander("Connect Google Sheet for all devices (one-time)", expanded=True):
        st.markdown(
            "1. Open your Helsinki leads Google Sheet → **Extensions → Apps Script**.\n"
            "2. Delete any placeholder code, paste the script below, click **Save**.\n"
            "3. **Deploy → New deployment → Web app**. Execute as **Me**. Who has access: **Anyone**.\n"
            "4. Paste the `/exec` URL here and click Connect."
        )
        try:
            script_path = Path(__file__).resolve().parent.joinpath("apps_script", "Code.gs")
            script_text = script_path.read_text(encoding="utf-8")
        except Exception:
            script_text = "See apps_script/Code.gs in the GitHub repo."
        st.code(script_text, language="javascript")
        pasted_url = st.text_input("Web app URL", placeholder="https://script.google.com/macros/s/.../exec")
        if st.button("Connect Google Sheet", type="primary"):
            url = (pasted_url or "").strip()
            if not url.startswith("http"):
                st.error("Paste the full /exec URL from Apps Script.")
            else:
                try:
                    st.session_state["gas_url"] = url
                    _webhook_write(
                        "upsert",
                        SYNC_MARKER,
                        url,
                        "",
                        "",
                        "sync",
                    )
                    st.success("Connected. Other devices will pick this up from the sheet.")
                    st.rerun()
                except Exception as exc:
                    st.session_state["gas_url"] = url
                    st.error("URL saved on this session, but the test write failed: {0}".format(exc))
elif get_write_url():
    st.caption("Shared Google Sheet sync is on. New leads are visible on other devices after refresh.")
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
        nav_url = maps_navigation_url(lead["address"], user_origin)
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
                        updated_lead = {
                            "id": l_id,
                            "name": new_name,
                            "address": new_addr,
                            "website": new_site,
                            "hours": new_hours,
                            "notes": lead.get("notes", ""),
                        }
                        _remember_pending(updated_lead)
                        wrote = update_lead_in_sheet(l_id, new_name, new_addr, new_site, new_hours, lead.get("notes", ""))
                        st.session_state["edit_lead_id"] = None
                        st.session_state["last_save_ok"] = bool(wrote)
                        st.session_state["last_save_error"] = None if wrote else "Saved on this device only. Other phones will keep the old demo link until Google Sheet sync is connected."
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
                    f'<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:8px;">'
                    f'<h2 style="margin:0;">{safe_name}</h2>'
                    f'<span style="color:#16a34a;font-size:2rem;font-weight:800;line-height:1;">{distance_label}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
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
                        lead["notes"] = combined_text
                        apply_local = False
                        new_local = []
                        addr_k = str(lead.get("address") or "").lower().strip()
                        for row in st.session_state["local_leads"]:
                            if str(row.get("address") or "").lower().strip() == addr_k:
                                merged = dict(row)
                                merged["notes"] = combined_text
                                new_local.append(merged)
                                apply_local = True
                            else:
                                new_local.append(row)
                        if not apply_local:
                            new_local.append(dict(lead))
                        st.session_state["local_leads"] = new_local
                        _remember_pending({
                            "id": l_id,
                            "name": lead["name"],
                            "address": lead["address"],
                            "website": lead["website"],
                            "hours": lead["hours"],
                            "notes": combined_text,
                        })
                        update_lead_in_sheet(
                            l_id,
                            lead["name"],
                            lead["address"],
                            lead["website"],
                            lead["hours"],
                            combined_text,
                        )
                        st.rerun()
                with btn_col2:
                    if st.button("✏️ Edit", key=f"edit_btn_{idx}", use_container_width=True):
                        st.session_state["edit_lead_id"] = current_edit_id
                        st.rerun()
                with btn_col3:
                    if st.button("❌ Delete", key=f"delete_{idx}", type="secondary", use_container_width=True):
                        addr_k = str(lead.get("address") or "").lower().strip()
                        st.session_state["local_leads"] = [
                            x
                            for x in st.session_state["local_leads"]
                            if str(x.get("address") or "").lower().strip() != addr_k
                        ]
                        deleted = list(st.session_state.get("deleted_addrs") or [])
                        if addr_k and addr_k not in deleted:
                            deleted.append(addr_k)
                        st.session_state["deleted_addrs"] = deleted
                        delete_lead_from_sheet(l_id, lead.get("address", ""))
                        st.session_state["ls_hydrated"] = True
                        persist_leads_to_browser(st.session_state["local_leads"])
                        st.rerun()
        
        with col2:
            safe_nav = html.escape(nav_url, quote=True)
            st.markdown(
                f'<div style="text-align:left;margin:0 0 8px 0;">'
                f'<a href="{safe_nav}" target="_blank" rel="noopener noreferrer" '
                f'style="display:inline-block;background:#1c83e1;color:#fff;text-decoration:none;'
                f'font-weight:700;padding:8px 16px;border-radius:10px;white-space:nowrap;">'
                f"🧭 Navigation</a></div>",
                unsafe_allow_html=True,
            )
            encoded_address = urllib.parse.quote(str(lead["address"]) + ", Helsinki")
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
                st.session_state["ls_hydrated"] = True
                _remember_pending(new_lead_dict)
                persist_leads_to_browser(st.session_state["local_leads"])
                save_lead_to_sheet(add_name.strip(), add_addr.strip(), final_link, final_hours)
                st.session_state["last_save_ok"] = True
                st.session_state["last_save_error"] = None
                st.rerun()
