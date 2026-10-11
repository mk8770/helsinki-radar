import streamlit as st
import json
import urllib.request
import urllib.parse
import urllib.error

# Ihre VOLLSTÄNDIGE, permanente Sheety-Verbindung direkt zu Ihrem Google Sheet
API_URL = "https://api.sheety.co/af5130fd4340e5b69490c1da248a8d72/websiteLeads/sheet1"

st.set_page_config(page_title="🎯 Helsinki Website Leads", layout="wide", initial_sidebar_state="collapsed")

# INTERNER SOFORT-SPEICHER & BEARBEITUNGS-STATE
if "local_leads" not in st.session_state:
    st.session_state["local_leads"] = []
if "edit_lead_id" not in st.session_state:
    st.session_state["edit_lead_id"] = None

# 1. Daten aus Google Sheets (Sheety) laden
def load_leads_from_sheet():
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=7) as response:
            data = json.loads(response.read().decode('utf-8'))
            if "sheet1" in data:
                return data["sheet1"]
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
        with urllib.request.urlopen(req, timeout=7) as response:
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
        with urllib.request.urlopen(req, timeout=7) as response:
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
        with urllib.request.urlopen(req, timeout=7) as response:
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

# DATENQUELLEN ZUSAMMENFÜHREN
cloud_leads = load_leads_from_sheet()
all_leads = []
seen_addresses = set()

for l in st.session_state["local_leads"]:
    all_leads.append(l)
    seen_addresses.add(l["address"].lower().strip())

if cloud_leads:
    for l in cloud_leads:
        addr = l.get("address", l.get("adress", "")).lower().strip()
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

# Filter auf die Gesamtliste anwenden
filtered_leads = []
for lead in all_leads:
    district = parse_district(lead["address"])
    if selected_district_filter != "All Districts" and district != selected_district_filter:
        continue
    filtered_leads.append(lead)

st.subheader(f"Active Leads in Sales Pipeline ({len(filtered_leads)})")

if not filtered_leads:
    st.info("No leads found matching the active filters. Use the form below to add a new lead!")

# Layout-Karten zeichnen
for idx, lead in enumerate(filtered_leads):
    l_id = lead.get("id")
    
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            if st.session_state["edit_lead_id"] == l_id and l_id is not None:
                st.markdown("### ✏️ Edit Entry")
                edit_name = st.text_input("Name:", value=lead['name'], key=f"edit_name_{idx}")
                edit_addr = st.text_input("Address:", value=lead['address'], key=f"edit_addr_{idx}")
                edit_site = st.text_input("Website:", value=lead['website'], key=f"edit_site_{idx}")
                edit_hours = st.text_input("Hours:", value=lead['hours'], key=f"edit_hours_{idx}")
                
                edit_col1, edit_col2 = st.columns(2)
                with edit_col1:
                    if st.button("💾 Save Changes", key=f"save_edit_{idx}", type="primary"):
                        if update_lead_in_sheet(l_id, edit_name.strip(), edit_addr.strip(), edit_site.strip(), edit_hours.strip(), lead['notes']):
                            st.session_state["edit_lead_id"] = None
                            st.success("Successfully updated!")
                            st.rerun()
                with edit_col2:
                    if st.button("Cancel", key=f"cancel_edit_{idx}"):
                        st.session_state["edit_lead_id"] = None
                        st.rerun()
            else:
                st.markdown(f"## {lead['name']}")
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
                    if l_id:
                        if st.button("✏️ Edit", key=f"edit_btn_{idx}", use_container_width=True):
                            st.session_state["edit_lead_id"] = l_id
                            st.rerun()
                with btn_col3:
                    if st.button("❌ Delete", key=f"delete_{idx}", type="secondary", use_container_width=True):
                        st.session_state["local_leads"] = [x for x in st.session_state["local_leads"] if x["address"].lower().strip() != lead["address"].lower().strip()]
                        if l_id:
                            delete_lead_from_sheet(l_id)
                        st.success("Lead deleted!")
                        st.rerun()
        
        with col2:
            # Absolut korrekter Google-Maps Link ohne Formatierungsfehler
            encoded_addr = urllib.parse.quote(str(lead['address']) + ", Helsinki")
            map_src = f"https://google.com{encoded_addr}&output=embed"
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
