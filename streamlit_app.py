import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

API_URL = "https://api.sheety.co/af5130fd4340e5b69490c1da248a8d72/websiteLeads/sheet1"

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
    if website in ("", "https://", "https://."):
        website = "Website to be done"
    if not hours:
        hours = "12:00 - 20:00"
    return {
        "id": lead.get("id"),
        "name": name,
        "address": address,
        "adress": address,
        "website": website,
        "hours": hours,
        "district": lead.get("district") or parse_district(address),
        "status": lead.get("status") or "Not Visited Yet",
        "notes": lead.get("notes") or "",
    }


def parse_district(address_str):
    if not address_str:
        return "Unknown"
    addr = str(address_str).lower()
    if any(
        k in addr
        for k in [
            "linja",
            "hameentie",
            "hämeentie",
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
            "töölönkatu",
            "mechelininkatu",
        ]
    ):
        return "Töölö"
    return "Central District"


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


def post_lead_to_sheet(name, address, website, hours):
    payload = {
        "sheet1": {
            "name": name,
            "adress": address,
            "website": website,
            "hours": hours,
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
            post_lead_to_sheet(name, address, website, hours)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def delete_lead_from_sheet(lead_id):
    if lead_id in (None, ""):
        return
    try:
        req = urllib.request.Request(
            f"{API_URL}/{lead_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            method="DELETE",
        )
        with urllib.request.urlopen(req, timeout=7) as response:
            response.read()
    except Exception:
        pass


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

st.title("🎯 Helsinki Website Leads")
st.write("Synchronisiertes Cloud-Dashboard (PC & Tablet via Google Sheets)")

home_mode = st.checkbox(
    "🏠 Home Mode (Show all prepared leads)",
    value=True,
    key="home_mode_toggle",
)
max_distance = st.slider(
    "Max walking distance from YOUR location (meters)",
    min_value=100,
    max_value=6000,
    value=6000,
    step=50,
    disabled=bool(home_mode),
    key="max_distance",
)

st.subheader(f"Aktive Leads in der Vertriebs-Pipeline ({len(leads)})")
if not leads:
    st.info("Keine Leads gefunden. Verwende das Formular unten!")

for idx, lead in enumerate(leads):
    l_name = lead.get("name") or "Unbekannt"
    l_addr = lead.get("address") or lead.get("adress") or ""
    l_site = lead.get("website") or "Website to be done"
    l_hours = lead.get("hours") or "12:00 - 20:00"
    l_district = lead.get("district") or parse_district(l_addr)
    l_id = lead.get("id")
    if not l_name or not l_addr:
        continue
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"## {l_name}")
            st.write(f"Adresse: {l_addr}")
            st.write(f"District: {l_district}")
            st.write(f"Visiting Hours: {l_hours}")
            if l_site in ("", "Website to be done", "https://"):
                st.button("Website to be done", key=f"disabled_{idx}", disabled=True)
            else:
                st.link_button("Open Demo Website", l_site, type="primary")
            st.selectbox(
                "Visit Status",
                ["Not Visited Yet", "In Progress", "Interested", "Not Interested"],
                key=f"status_{idx}",
            )
            st.text_area("Field Notes", key=f"notes_{idx}", height=70)
            if st.button(
                "❌ Lead aus Pipeline löschen",
                key=f"delete_{idx}",
                type="secondary",
            ):
                addr_k = street_key(lead)
                st.session_state["local_leads"] = [
                    row
                    for row in st.session_state["local_leads"]
                    if street_key(row) != addr_k
                ]
                deleted = list(st.session_state["deleted_addrs"])
                if addr_k and addr_k not in deleted:
                    deleted.append(addr_k)
                st.session_state["deleted_addrs"] = deleted
                delete_lead_from_sheet(l_id)
                st.rerun()
        with col2:
            encoded_addr = urllib.parse.quote(f"{l_addr}, Helsinki")
            map_src = f"https://maps.google.com/maps?q={encoded_addr}&output=embed"
            st.components.v1.iframe(map_src, height=140)

st.divider()

with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=True):
    with st.form("google_sheets_sync_form", clear_on_submit=True):
        add_name = st.text_input("Name des Geschäfts / Firma:")
        add_addr = st.text_input("Adresse (z.B. Hämeentie 12):")
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
                    if add_link.strip() in ("", "https://", "https://.")
                    else add_link.strip()
                )
                final_hours = (
                    "12:00 - 20:00" if not add_hours.strip() else add_hours.strip()
                )
                district = parse_district(add_addr.strip())
                new_lead = {
                    "name": add_name.strip(),
                    "address": add_addr.strip(),
                    "adress": add_addr.strip(),
                    "website": final_link,
                    "hours": final_hours,
                    "district": district,
                    "status": "Not Visited Yet",
                    "notes": "",
                }
                st.session_state["local_leads"].append(new_lead)
                save_lead_to_sheet_background(
                    new_lead["name"],
                    new_lead["adress"],
                    new_lead["website"],
                    new_lead["hours"],
                )
                st.rerun()
