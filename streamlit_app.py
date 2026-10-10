import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

# Ihre echte, unzerstoerbare Sheety-Verbindung direkt zu Ihrem Google Sheet
API_URL = "https://api.sheety.co/af5130fd4340e5b69490c1da248a8d72/websiteLeads/sheet1"

st.set_page_config(page_title="Helsinki Website Leads", layout="wide", initial_sidebar_state="collapsed")

if "local_leads" not in st.session_state:
    st.session_state["local_leads"] = []
if "edit_lead_id" not in st.session_state:
    st.session_state["edit_lead_id"] = None


def load_leads_from_sheet():
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=7) as response:
            data = json.loads(response.read().decode("utf-8"))
            if "sheet1" in data:
                return data["sheet1"]
    except Exception:
        pass
    return []


def save_lead_to_sheet(name, address, website, hours):
    try:
        payload = {
            "sheet1": {
                "name": name,
                "address": address,
                "website": website,
                "hours": hours,
                "notes": "",
            }
        }
        json_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            API_URL,
            data=json_data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=7) as response:
            return True
    except Exception:
        return False


def update_notes_in_sheet(lead_id, status, notes):
    try:
        combined_text = f"[{status}] {notes}" if notes else f"[{status}]"
        payload = {"sheet1": {"notes": combined_text}}
        json_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{API_URL}/{lead_id}",
            data=json_data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=7) as response:
            return True
    except Exception:
        return False


def update_lead_in_sheet(lead_id, name, address, website, hours):
    payload = {
        "sheet1": {
            "name": name,
            "address": address,
            "website": website,
            "hours": hours,
        }
    }
    json_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}/{lead_id}",
        data=json_data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=7) as response:
        response.read()


def update_lead_in_sheet_background(lead_id, name, address, website, hours):
    def _run():
        try:
            update_lead_in_sheet(lead_id, name, address, website, hours)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def delete_lead_from_sheet(lead_id):
    try:
        req = urllib.request.Request(
            f"{API_URL}/{lead_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            method="DELETE",
        )
        with urllib.request.urlopen(req, timeout=7) as response:
            return True
    except Exception:
        return False


def parse_district(address_str):
    if not address_str:
        return "Unknown"
    addr = str(address_str).lower()
    if any(k in addr for k in [
        "kalasatama",
        "redi",
        "tyopajankatu",
        "ty" + chr(0xf6) + "pajankatu",
        "leonkatu",
        "hermannin rantatie",
    ]):
        return "Kalasatama"
    if any(k in addr for k in [
        "linja",
        "hameentie",
        "h" + chr(0xe4) + "meentie",
        "helsinginkatu",
        "vaasankatu",
        "porthaninkatu",
    ]):
        return "Kallio"
    if any(k in addr for k in [
        "runeberginkatu",
        "topeliuksenkatu",
        "t" + chr(0xf6)*2 + "l" + chr(0xf6) + "nkatu",
        "mechelininkatu",
    ]):
        return "T" + chr(0xf6)*2 + "l" + chr(0xf6)
    return "Central District"


def lead_edit_key(lead, idx):
    if lead.get("id") not in (None, ""):
        return lead.get("id")
    return f"local-{idx}"


def apply_local_lead_update(old_address, new_fields):
    updated = []
    found = False
    old_key = str(old_address).lower().strip()
    for row in st.session_state["local_leads"]:
        if str(row.get("address", "")).lower().strip() == old_key:
            merged = dict(row)
            merged.update(new_fields)
            updated.append(merged)
            found = True
        else:
            updated.append(row)
    if not found:
        updated.append(dict(new_fields))
    st.session_state["local_leads"] = updated


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
            all_leads.append(
                {
                    "id": l.get("id"),
                    "name": l.get("name"),
                    "address": l.get("address", l.get("adress", "")),
                    "website": l.get("website", "Website to be done"),
                    "hours": l.get("hours", "12:00 - 20:00"),
                    "notes": l.get("notes", ""),
                }
            )

st.title("🎯 Helsinki Website Leads")
st.write("### Synchronisiertes Cloud-Dashboard (Echtzeit-Abgleich PC & Tablet)")

distance_filter = st.slider(
    "Max walking distance from YOUR location (meters)",
    min_value=100,
    max_value=6000,
    value=6000,
)
home_mode = st.checkbox("🏠 Home Mode (Show all prepared leads)", value=True, key="home_mode_widget")

st.subheader(f"Aktive Leads in der Vertriebs-Pipeline ({len(all_leads)})")

if not all_leads:
    st.info("Keine Leads im Google Sheet gefunden. Verwende das Formular unten!")

for idx, lead in enumerate(all_leads):
    current_edit_id = lead_edit_key(lead, idx)
    with st.container(border=True):
        if st.session_state["edit_lead_id"] == current_edit_id:
            st.markdown("### Eintrag bearbeiten")
            name_key = f"edit_name_{idx}"
            addr_key = f"edit_addr_{idx}"
            site_key = f"edit_site_{idx}"
            hours_key = f"edit_hours_{idx}"
            if name_key not in st.session_state:
                st.session_state[name_key] = lead.get("name", "")
            if addr_key not in st.session_state:
                st.session_state[addr_key] = lead.get("address", "")
            if site_key not in st.session_state:
                st.session_state[site_key] = lead.get("website", "")
            if hours_key not in st.session_state:
                st.session_state[hours_key] = lead.get("hours", "")
            st.text_input("Name", key=name_key)
            st.text_input("Address", key=addr_key)
            st.text_input("Website", key=site_key)
            st.text_input("Hours", key=hours_key)
            save_col, cancel_col = st.columns(2)
            with save_col:
                if st.button("💾 Änderungen speichern", key=f"save_edit_{idx}", type="primary"):
                    new_name = st.session_state.get(name_key, "").strip()
                    new_addr = st.session_state.get(addr_key, "").strip()
                    new_site = st.session_state.get(site_key, "").strip()
                    new_hours = st.session_state.get(hours_key, "").strip()
                    if not new_name or not new_addr:
                        st.error("Name und Adresse sind zwingend erforderlich!")
                    else:
                        apply_local_lead_update(
                            lead.get("address", ""),
                            {
                                "id": lead.get("id"),
                                "name": new_name,
                                "address": new_addr,
                                "website": new_site or "Website to be done",
                                "hours": new_hours or "12:00 - 20:00",
                                "notes": lead.get("notes", ""),
                            },
                        )
                        if lead.get("id"):
                            update_lead_in_sheet_background(
                                lead["id"],
                                new_name,
                                new_addr,
                                new_site or "Website to be done",
                                new_hours or "12:00 - 20:00",
                            )
                        st.session_state["edit_lead_id"] = None
                        st.rerun()
            with cancel_col:
                if st.button("Abbrechen", key=f"cancel_edit_{idx}", type="secondary"):
                    st.session_state["edit_lead_id"] = None
                    st.rerun()
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"## {lead['name']}")
                st.write(f"**Adresse:** {lead['address']} ({parse_district(lead['address'])})")
                st.write(f"**Visiting Hours:** {lead['hours']}")

                if lead["website"] in ["", "Website to be done", "https://"]:
                    st.button("Website to be done", key=f"disabled_{idx}", disabled=True)
                else:
                    st.link_button("Open Demo Website", lead["website"], type="primary")

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

                btn1, btn2, btn3 = st.columns(3)
                with btn1:
                    if st.button("💾 Save Note", key=f"save_btn_{idx}", type="primary"):
                        if lead.get("id"):
                            if update_notes_in_sheet(lead["id"], selected_status, typed_notes):
                                st.success("Notiz erfolgreich in Google Sheets gespeichert!")
                                st.rerun()
                        else:
                            lead["notes"] = f"[{selected_status}] {typed_notes}"
                            st.success("Notiz lokal gemerkt!")
                            st.rerun()
                with btn2:
                    if st.button("✏️ Bearbeiten", key=f"edit_btn_{idx}"):
                        st.session_state["edit_lead_id"] = current_edit_id
                        st.rerun()
                with btn3:
                    if st.button("❌ L?schen", key=f"delete_{idx}", type="secondary"):
                        st.session_state["local_leads"] = [
                            x
                            for x in st.session_state["local_leads"]
                            if x["address"].lower().strip() != lead["address"].lower().strip()
                        ]
                        if lead.get("id"):
                            delete_lead_from_sheet(lead["id"])
                        st.session_state["edit_lead_id"] = None
                        st.success("Lead gel?scht!")
                        st.rerun()

            with col2:
                encoded_addr = urllib.parse.quote(str(lead["address"]) + ", Helsinki")
                map_src = f"https://maps.google.com/maps?q={encoded_addr}&output=embed"
                st.components.v1.iframe(map_src, height=160)

st.divider()

with st.expander("➕ Neuen Lead manuell hinzuf?gen", expanded=True):
    with st.form("google_sheets_sync_form", clear_on_submit=True):
        add_name = st.text_input("Name des Gesch?fts / Firma:")
        add_addr = st.text_input("Adresse (z.B. H?meentie 12):")
        add_link = st.text_input("Website / Demo-Link (optional):", value="https://")
        add_hours = st.text_input("Visiting Hours (optional):", value="12:00 - 20:00")

        submitted = st.form_submit_button(
            "💾 LEAD DASHBOARD-WEIT SPEICHERN",
            use_container_width=True,
            type="primary",
        )

        if submitted:
            if not add_name.strip() or not add_addr.strip():
                st.error("Name und Adresse sind zwingend erforderlich!")
            else:
                final_link = (
                    "Website to be done"
                    if add_link.strip() in ["", "https://", "https://."]
                    else add_link.strip()
                )
                final_hours = "12:00 - 20:00" if not add_hours.strip() else add_hours.strip()

                new_lead_dict = {
                    "name": add_name.strip(),
                    "address": add_addr.strip(),
                    "website": final_link,
                    "hours": final_hours,
                    "notes": "",
                }

                st.session_state["local_leads"].append(new_lead_dict)
                save_lead_to_sheet(add_name.strip(), add_addr.strip(), final_link, final_hours)
                st.success("Erfolgreich gespeichert!")
                st.rerun()
