import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

API_URL = "https://sheety.co"
STATUS_OPTIONS = ["Not Visited Yet", "In Progress", "Interested", "Not Interested"]

st.set_page_config(
    page_title="Helsinki Website Leads",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "local_leads" not in st.session_state:
    st.session_state["local_leads"] = []
if "deleted_addrs" not in st.session_state:
    st.session_state["deleted_addrs"] = []


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def street_key(lead):
    addr = (
        lead.get("address")
        or lead.get("adress")
        or lead.get("Address")
        or lead.get("Adress")
        or ""
    )
    return clean_text(addr).lower()


def parse_district(address_str):
    if not address_str:
        return "Unknown"
    addr = str(address_str).lower()
    if any(
        k in addr
        for k in [
            "linja",
            "hameentie",
            "h\u00e4meentie",
            "helsinginkatu",
            "vaasankatu",
            "porthaninkatu",
        ]
    ):
        return "Kallio"
    if any(
        k in addr
        for k in [
            "runeberginkatu",
            "topeliuksenkatu",
            "toolonkatu",
            "t\u00f6\u00f6l\u00f6nkatu",
            "mechelininkatu",
        ]
    ):
        return "T\u00f6\u00f6l\u00f6"
    return "Central District"


def split_notes(raw_notes):
    text = clean_text(raw_notes)
    if text.startswith("[") and "]" in text:
        status, rest = text[1:].split("]", 1)
        status = status.strip()
        notes = rest.strip()
        if status not in STATUS_OPTIONS:
            status = "Not Visited Yet"
        return status, notes
    return "Not Visited Yet", text


def normalize_lead(lead):
    name = clean_text(lead.get("name") or lead.get("Name"))
    address = clean_text(
        lead.get("address")
        or lead.get("adress")
        or lead.get("Address")
        or lead.get("Adress")
    )
    website = clean_text(lead.get("website") or lead.get("Website"))
    hours = clean_text(lead.get("hours") or lead.get("Hours"))
    notes_raw = lead.get("notes")
    if notes_raw is None:
        notes_raw = lead.get("Notes") or lead.get("fieldNotes") or ""
    status, notes = split_notes(notes_raw)
    if "status" in lead and clean_text(lead.get("status")) in STATUS_OPTIONS:
        status = clean_text(lead.get("status"))
        if not notes:
            notes = clean_text(notes_raw)
            if notes.startswith("[") and "]" in notes:
                notes = notes.split("]", 1)[1].strip()
    if website in ("", "https://", "https://."):
        website = "Website to be done"
    if not hours:
        hours = "12:00 - 20:00"
    return {
        "id": lead.get("id"),
        "name": name,
        "address": address,
        "website": website,
        "hours": hours,
        "notes": notes,
        "status": status,
        "district": lead.get("district") or parse_district(address),
    }


def load_leads_from_sheet():
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=7) as response:
            data = json.loads(response.read().decode("utf-8"))
            if "sheet1" in data and isinstance(data["sheet1"], list):
                return data["sheet1"]
    except Exception:
        pass
    return []


def save_lead_to_sheet(name, address, website, hours):
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
        response.read()


def save_lead_to_sheet_background(name, address, website, hours):
    def _run():
        try:
            save_lead_to_sheet(name, address, website, hours)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def update_notes_in_sheet(lead_id, current_status, current_notes):
    payload = {
        "sheet1": {
            "notes": "[{0}] {1}".format(current_status, current_notes)
        }
    }
    json_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "{0}/{1}".format(API_URL, lead_id),
        data=json_data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=7) as response:
        response.read()


def delete_lead_from_sheet(lead_id):
    if lead_id in (None, ""):
        return
    try:
        req = urllib.request.Request(
            "{0}/{1}".format(API_URL, lead_id),
            headers={"User-Agent": "Mozilla/5.0"},
            method="DELETE",
        )
        with urllib.request.urlopen(req, timeout=7) as response:
            response.read()
    except Exception:
        pass


def store_notes_locally(lead, current_status, current_notes):
    addr_k = street_key(lead)
    saved = dict(lead)
    saved["status"] = current_status
    saved["notes"] = current_notes
    rows = []
    found = False
    for row in st.session_state["local_leads"]:
        if street_key(row) == addr_k:
            merged = dict(row)
            merged.update(saved)
            rows.append(merged)
            found = True
        else:
            rows.append(row)
    if not found:
        rows.append(saved)
    st.session_state["local_leads"] = rows


def merge_leads(cloud_leads, local_leads, deleted_addrs):
    merged = {}
    deleted = {clean_text(a).lower() for a in deleted_addrs}
    for row in cloud_leads:
        item = normalize_lead(row)
        key = street_key(item)
        if not key or key in deleted:
            continue
        merged[key] = item
    for row in local_leads:
        item = normalize_lead(row)
        key = street_key(item)
        if not key or key in deleted:
            continue
        previous = merged.get(key, {})
        merged[key] = {**previous, **item}
        if previous.get("id") and not merged[key].get("id"):
            merged[key]["id"] = previous["id"]
    return list(merged.values())


cloud_leads = load_leads_from_sheet()
leads = merge_leads(
    cloud_leads,
    st.session_state["local_leads"],
    st.session_state["deleted_addrs"],
)

st.title("\U0001f3af Helsinki Website Leads")
st.write("Synchronisiertes Cloud-Dashboard (PC & Tablet via Google Sheets)")
if st.session_state.pop("note_flash", None):
    st.success("Notizen gespeichert.")

home_mode = st.checkbox(
    "\U0001f3e0 Home Mode (Show all prepared leads)",
    value=True,
    key="home_mode_toggle",
)
st.slider(
    "Max walking distance from YOUR location (meters)",
    min_value=100,
    max_value=6000,
    value=6000,
    step=50,
    disabled=bool(home_mode),
    key="max_distance",
)

st.subheader("Aktive Leads in der Vertriebs-Pipeline ({0})".format(len(leads)))
if not leads:
    st.info("Keine Leads gefunden. Verwende das Formular unten!")

for idx, lead in enumerate(leads):
    l_name = lead.get("name") or "Unbekannt"
    l_addr = lead.get("address") or ""
    l_site = lead.get("website") or "Website to be done"
    l_hours = lead.get("hours") or "12:00 - 20:00"
    l_district = lead.get("district") or parse_district(l_addr)
    l_id = lead.get("id")
    if not l_name or not l_addr:
        continue

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("## {0}".format(l_name))
            st.write("Adresse: {0}".format(l_addr))
            st.write("District: {0}".format(l_district))
            st.write("Visiting Hours: {0}".format(l_hours))
            if l_site in ("", "Website to be done", "https://"):
                st.button("Website to be done", key="disabled_{0}".format(idx), disabled=True)
            else:
                st.link_button("Open Demo Website", l_site, type="primary")

            status_key = "status_{0}".format(idx)
            notes_key = "notes_{0}".format(idx)
            if status_key not in st.session_state:
                st.session_state[status_key] = lead.get("status") or "Not Visited Yet"
            if notes_key not in st.session_state:
                st.session_state[notes_key] = lead.get("notes") or ""

            st.selectbox("Status", STATUS_OPTIONS, key=status_key)
            st.text_area("\U0001f4dd Field Notes", key=notes_key, height=70)

            if st.button("\U0001f4be Save Note", key="save_note_{0}".format(idx), type="primary"):
                current_status = st.session_state.get(status_key, "Not Visited Yet")
                current_notes = st.session_state.get(notes_key, "")
                store_notes_locally(lead, current_status, current_notes)
                if l_id:
                    try:
                        update_notes_in_sheet(l_id, current_status, current_notes)
                    except Exception as exc:
                        st.error("Cloud-Update fehlgeschlagen: {0}".format(exc))
                    else:
                        st.session_state["note_flash"] = True
                        st.rerun()
                else:
                    st.session_state["note_flash"] = True
                    st.rerun()

            if st.button(
                "\u274c Lead aus Pipeline l\u00f6schen",
                key="delete_{0}".format(idx),
                type="secondary",
            ):
                addr_k = street_key(lead)
                st.session_state["local_leads"] = [
                    row for row in st.session_state["local_leads"] if street_key(row) != addr_k
                ]
                deleted = list(st.session_state["deleted_addrs"])
                if addr_k and addr_k not in deleted:
                    deleted.append(addr_k)
                st.session_state["deleted_addrs"] = deleted
                delete_lead_from_sheet(l_id)
                st.rerun()

        with col2:
            encoded_addr = urllib.parse.quote("{0}, Helsinki".format(l_addr))
            map_src = "https://maps.google.com/maps?q={0}&output=embed".format(encoded_addr)
            st.components.v1.iframe(map_src, height=140)

st.divider()

with st.expander("\u2795 Neuen Lead manuell hinzuf\u00fcgen", expanded=True):
    with st.form("google_sheets_sync_form", clear_on_submit=True):
        add_name = st.text_input("Name des Gesch\u00e4fts / Firma:")
        add_addr = st.text_input("Adresse (z.B. H\u00e4meentie 12):")
        add_link = st.text_input("Website / Demo-Link (optional):", value="https://")
        add_hours = st.text_input("Visiting Hours (optional):", value="12:00 - 20:00")
        submitted = st.form_submit_button(
            "\U0001f4be LEAD DASHBOARD-WEIT SPEICHERN",
            use_container_width=True,
            type="primary",
        )
        if submitted:
            if not add_name.strip() or not add_addr.strip():
                st.error("Name und Adresse sind zwingend erforderlich!")
            else:
                final_link = (
                    "Website to be done"
                    if add_link.strip() in ("", "https://", "https://.")
                    else add_link.strip()
                )
                final_hours = "12:00 - 20:00" if not add_hours.strip() else add_hours.strip()
                new_lead = {
                    "name": add_name.strip(),
                    "address": add_addr.strip(),
                    "website": final_link,
                    "hours": final_hours,
                    "notes": "",
                    "status": "Not Visited Yet",
                    "district": parse_district(add_addr.strip()),
                }
                st.session_state["local_leads"].append(new_lead)
                save_lead_to_sheet_background(
                    new_lead["name"],
                    new_lead["address"],
                    new_lead["website"],
                    new_lead["hours"],
                )
                st.rerun()
