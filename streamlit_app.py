import streamlit as st
import json
import urllib.request
import urllib.parse
import urllib.error

# Ihre echte, unzerstörbare Sheety-Verbindung direkt zu Ihrem Google Sheet
API_URL = "https://api.sheety.co/af5130fd4340e5b69490c1da248a8d72/websiteLeads/sheet1"

st.set_page_config(page_title="🎯 Helsinki Website Leads", layout="wide", initial_sidebar_state="collapsed")

# INTERNER SOFORT-SPEICHER (Garantiert sofortiges Speichern auf dem Bildschirm!)
if "local_leads" not in st.session_state:
    st.session_state["local_leads"] = []

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

# 2. Neuen Lead live in Google Sheets (Sheety) schreiben
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

# 3. Notizen und Status in Google Sheets aktualisieren
def update_notes_in_sheet(lead_id, status, notes):
    try:
        combined_text = f"[{status}] {notes}" if notes else f"[{status}]"
        payload = {
            "sheet1": {
                "notes": combined_text
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

# Stadtviertel-Zuweisung für Helsinki
def parse_district(address_str):
    if not address_str:
        return "Unknown"
    addr = str(address_str).lower()
    if any(k in addr for k in ["linja", "hämeentie", "helsinginkatu", "vaasankatu", "porthaninkatu"]):
        return "Kallio"
    if any(k in addr for k in ["runeberginkatu", "topeliuksenkatu", "töölönkatu", "mechelininkatu"]):
        return "Töölö"
    return "Central District"

# DATENQUELLEN ZUSAMMENFÜHREN
cloud_leads = load_leads_from_sheet()
all_leads = []
seen_addresses = set()

# Erst die lokalen Sofort-Leads anzeigen
for l in st.session_state["local_leads"]:
    all_leads.append(l)
    seen_addresses.add(l["address"].lower().strip())

# Dann die Cloud-Leads hinzufügen (ohne Duplikate)
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
st.write("### 🌐 Synchronisiertes Cloud-Dashboard (Echtzeit-Abgleich PC & Tablet)")

# Unser Slider-Test: Steht fest auf 6000 Meter!
distance_filter = st.slider("Max walking distance from YOUR location (meters)", min_value=100, max_value=6000, value=6000)
home_mode = st.checkbox("🏠 Home Mode (Show all prepared leads)", value=True, key="home_mode_widget")

st.subheader(f"Aktive Leads in der Vertriebs-Pipeline ({len(all_leads)})")

if not all_leads:
    st.info("Keine Leads im Google Sheet gefunden. Verwende das Formular unten!")

# Layout-Karten zeichnen
for idx, lead in enumerate(all_leads):
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"## {lead['name']}")
            st.write(f"📍 **Adresse:** {lead['address']} ({parse_district(lead['address'])})")
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
            
            # Speicher-Button für Notizen
            if st.button("💾 Save Note", key=f"save_btn_{idx}", type="primary"):
                if lead.get("id"):
                    if update_notes_in_sheet(lead["id"], selected_status, typed_notes):
                        st.success("Notiz erfolgreich in Google Sheets gespeichert!")
                        st.rerun()
                else:
                    lead["notes"] = f"[{selected_status}] {typed_notes}"
                    st.success("Notiz lokal gemerkt!")
                    st.rerun()
            
            # Löschen-Button
            if st.button("❌ Lead aus Pipeline löschen", key=f"delete_{idx}", type="secondary"):
                st.session_state["local_leads"] = [x for x in st.session_state["local_leads"] if x["address"].lower().strip() != lead["address"].lower().strip()]
                if lead.get("id"):
                    delete_lead_from_sheet(lead["id"])
                st.success("Lead gelöscht!")
                st.rerun()
        
        with col2:
            encoded_addr = urllib.parse.quote(str(lead['address']) + ", Helsinki")
            map_src = f"https://maps.google.com/maps?q={encoded_addr}&output=embed"
            st.components.v1.iframe(map_src, height=160)

st.divider()

# Formular zum manuellen Hinzufügen
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=True):
    with st.form("google_sheets_sync_form", clear_on_submit=True):
        add_name = st.text_input("Name des Geschäfts / Firma:")
        add_addr = st.text_input("Adresse (z.B. Hämeentie 12):")
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
