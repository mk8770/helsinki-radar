import streamlit as st
import json
import urllib.request
import urllib.parse
import urllib.error

# Krisensichere Sheety-Anbindung direkt an Ihr Google Sheet
API_URL = "https://docs.google.com/spreadsheets/d/1Fw6T2gxui7XCTYskT90890poXIIgZ6SxLytUA1eMtns/edit?gid=0#gid=0"

st.set_page_config(page_title="🎯 Helsinki Website Leads", layout="wide", initial_sidebar_state="collapsed")

# 1. Daten aus Google Sheets (Sheety) laden
def load_leads_from_sheet():
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            # Sheety packt die Zeilen immer in den Namen der Tabelle (sheet1)
            if "sheet1" in data:
                return data["sheet1"]
    except Exception:
        pass
    return []

# 2. Neuen Lead live in Google Sheets (Sheety) schreiben
def save_lead_to_sheet(name, address, website, hours):
    try:
        # Sheety erwartet die Spaltenüberschriften immer in Kleinbuchstaben!
        payload = {
            "sheet1": {
                "name": name,
                "address": address,
                "website": website,
                "hours": hours
            }
        }
        json_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            API_URL, 
            data=json_data, 
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, 
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return True
    except Exception:
        return False

# Automatisierte Stadtviertel-Zuweisung für Helsinki
def parse_district(address):
    addr = address.lower()
    if any(k in addr for k in ["linja", "hämeentie", "helsinginkatu", "vaasankatu", "porthaninkatu"]):
        return "Kallio"
    if any(k in addr for k in ["runeberginkatu", "topeliuksenkatu", "töölönkatu", "mechelininkatu"]):
        return "Töölö"
    return "Central District"

# Daten holen
leads = load_leads_from_sheet()

st.title("🎯 Helsinki Website Leads")
st.write("### 🌐 Synchronisiertes Cloud-Dashboard (Direkt-Abgleich PC & Tablet via Google Sheets)")

# Test-Slider: Steht fest auf 6000 Meter für unseren Verbindungstest!
distance_filter = st.slider("Max walking distance from YOUR location (meters)", min_value=100, max_value=6000, value=6000)
home_mode = st.checkbox("🏠 Home Mode (Show all prepared leads)", value=True)

st.subheader(f"Aktive Leads in der Vertriebs-Pipeline ({len(leads)})")

if not leads:
    st.info("Keine Leads im Google Sheet gefunden oder Verbindung wird geladen. Trage unten einen Lead ein!")

# Layout-Karten für jeden Lead aus der Google-Tabelle
for idx, lead in enumerate(leads):
    # Sicherstellen, dass keine leeren Zeilen abstürzen
    if not lead.get("name") or not lead.get("address"):
        continue
        
    with st.container(border=True):
        col1, col2 = st.columns([1.5, 1])
        with col1:
            st.markdown(f"## {lead['name']}")
            st.write(f"📍 **Adresse:** {lead['address']} ({parse_district(lead['address'])})")
            st.write(f"⏱️ **Visiting Hours:** {lead.get('hours', '12:00 - 20:00')}")
            
            # Button-Logik für Demo-Websites
            lead_link = lead.get("website", "Website to be done")
            if lead_link in ["", "Website to be done", "https://"]:
                st.button("⚠️ Website to be done", key=f"disabled_{idx}", disabled=True)
            else:
                st.link_button("🌐 Open Demo Website", lead_link, type="primary")
                
            # Status-Meldungen direkt im Außendienst
            st.selectbox("Status", ["Not Visited Yet", "In Progress", "Interested", "Not Interested"], key=f"status_{idx}")
            st.text_area("📝 Field Notes", key=f"notes_{idx}", height=70)
            st.button("💾 Save Note", key=f"save_btn_{idx}")
            
        with col2:
            # Automatische Google-Maps Karte
            encoded_addr = urllib.parse.quote(lead['address'] + ", Helsinki")
            map_src = f"https://google.com{encoded_addr}&output=embed"
            st.components.v1.iframe(map_src, height=160)

st.hr()

# Einziges, sauberes Formular zum manuellen Hinzufügen
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
                
                # In Google Sheet speichern
                if save_lead_to_sheet(add_name.strip(), add_addr.strip(), final_link, final_hours):
                    st.success("Erfolgreich direkt im Google Sheet gespeichert!")
                    st.rerun()
                else:
                    st.error("Fehler bei der Übertragung an Google Sheets. Prüfe deine Sheety-Einstellungen!")
