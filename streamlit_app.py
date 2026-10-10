import streamlit as st
import json
import urllib.request
import urllib.parse
import urllib.error

# Ihre VOLLSTÄNDIGE, permanente Sheety-Verbindung direkt zu Ihrem Google Sheet
API_URL = "https://sheety.co"

st.set_page_config(page_title="🎯 Helsinki Website Leads", layout="wide", initial_sidebar_state="collapsed")

# 1. Daten aus Google Sheets (Sheety) laden
def load_leads_from_sheet():
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=7) as response:
            data = json.loads(response.read().decode('utf-8'))
            if "sheet1" in data:
                return data["sheet1"]
    except Exception as e:
        st.error(f"Fehler beim Laden aus der Cloud: {str(e)}")
    return []

# 2. Neuen Lead live in Google Sheets (Sheety) schreiben
def save_lead_to_sheet(name, address, website, hours):
    try:
        # Sheety verlangt die Spaltenüberschriften im JSON IMMER komplett klein geschrieben!
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
        with urllib.request.urlopen(req, timeout=7) as response:
            return True
    except Exception as e:
        st.error(f"Fehler beim Speichern in der Cloud: {str(e)}")
        return False

# 3. Lead über die Sheety-API aus dem Google Sheet löschen
def delete_lead_from_sheet(lead_id):
    try:
        delete_url = f"{API_URL}/{lead_id}"
        req = urllib.request.Request(
            delete_url,
            headers={"User-Agent": "Mozilla/5.0"},
            method="DELETE"
        )
        with urllib.request.urlopen(req, timeout=7) as response:
            return True
    except Exception as e:
        st.error(f"Fehler beim Löschen aus der Cloud: {str(e)}")
        return False

# Automatisierte Stadtviertel-Zuweisung für Helsinki
def parse_district(address_str):
    if not address_str:
        return "Unknown"
    addr = str(address_str).lower()
    if any(k in addr for k in ["linja", "hämeentie", "helsinginkatu", "vaasankatu", "porthaninkatu"]):
        return "Kallio"
    if any(k in addr for k in ["runeberginkatu", "topeliuksenkatu", "töölönkatu", "mechelininkatu"]):
        return "Töölö"
    return "Central District"

# Daten holen
leads = load_leads_from_sheet()

st.title("🎯 Helsinki Website Leads")
st.write("### 🌐 Synchronisiertes Cloud-Dashboard (Direkt-Abgleich PC & Tablet via Google Sheets)")

# Unser Slider-Test: Steht fest auf 6000 Meter!
distance_filter = st.slider("Max walking distance from YOUR location (meters)", min_value=100, max_value=6000, value=6000)

# Eindeutiger Key für den Home Mode ohne Widget-Dopplung
if "home_mode_state" not in st.session_state:
    st.session_state["home_mode_state"] = True

home_mode = st.checkbox("🏠 Home Mode (Show all prepared leads)", key="home_mode_widget")

st.subheader(f"Aktive Leads in der Vertriebs-Pipeline ({len(leads)})")

if not leads:
    st.info("Keine Leads im Google Sheet gefunden. Verwende das Formular unten!")

# Layout-Karten für jeden Lead aus der Google-Tabelle
for idx, lead in enumerate(leads):
    # Abfangen von Groß-/Kleinschreibung bei den Sheety-Spalten
    l_name = lead.get("name", "Unbekannt")
    l_addr = lead.get("address", lead.get("adress", lead.get("Address", "")))
    l_site = lead.get("website", lead.get("Website", "Website to be done"))
    l_hours = lead.get("hours", lead.get("Hours", "12:00 - 20:00"))
    l_id = lead.get("id")
    
    if not l_name or not l_addr:
        continue
        
    with st.container(border=True):
        col1, col2 = st.columns()
        with col1:
            st.markdown(f"## {l_name}")
            st.write(f"📍 **Adresse:** {l_addr} ({parse_district(l_addr)})")
            st.write(f"⏱️ **Visiting Hours:** {l_hours}")
            
            if l_site in ["", "Website to be done", "https://"]:
                st.button("⚠️ Website to be done", key=f"disabled_{idx}", disabled=True)
            else:
                st.link_button("🌐 Open Demo Website", l_site, type="primary")
                
            st.selectbox("Status", ["Not Visited Yet", "In Progress", "Interested", "Not Interested"], key=f"status_{idx}")
            st.text_area("📝 Field Notes", key=f"notes_{idx}", height=70)
            st.button("💾 Save Note", key=f"save_btn_{idx}")
            
            # Voll funktionsfähiger Lösch-Button auf jeder Karte
            if l_id:
                if st.button("❌ Lead aus Pipeline löschen", key=f"delete_{idx}", type="secondary"):
                    if delete_lead_from_sheet(l_id):
                        st.success("Lead gelöscht!")
                        st.rerun()
        
        with col2:
            encoded_addr = urllib.parse.quote(str(l_addr) + ", Helsinki")
            map_src = f"https://google.com{encoded_addr}&output=embed"
            st.components.v1.iframe(map_src, height=160)

st.hr()

# Formular zum manuellen Hinzufügen (Direkt in Google Sheets speichern)
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
                
                if save_lead_to_sheet(add_name.strip(), add_addr.strip(), final_link, final_hours):
                    st.success("Erfolgreich direkt im Google Sheet gespeichert!")
                    st.rerun()
