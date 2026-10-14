function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}

function doGet() {
  return json_({ ok: true, service: "helsinki-leads" });
}

function norm_(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function rowMatches_(row, needle) {
  if (!needle) {
    return false;
  }
  const addr = norm_(row[1]);
  const name = norm_(row[0]);
  return addr === needle || name === needle || addr.indexOf(needle) !== -1 || needle.indexOf(addr) !== -1;
}

function parseBody_(e) {
  const raw = (e && e.postData && e.postData.contents) || "";
  if (raw) {
    try {
      return JSON.parse(raw);
    } catch (err) {
      return {};
    }
  }
  if (e && e.parameter && e.parameter.payload) {
    try {
      return JSON.parse(e.parameter.payload);
    } catch (err) {
      return {};
    }
  }
  return {};
}

function doPost(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const d = parseBody_(e);
  const action = d.action || "upsert";
  const name = d.name || "";
  const address = d.address || d.adress || "";
  const website = d.website || "";
  const hours = d.hours || "";
  const notes = d.notes || "";
  const needle = norm_(address) || norm_(name);
  const rows = sheet.getDataRange().getValues();

  if (action === "delete") {
    let removed = 0;
    for (let i = rows.length; i >= 2; i--) {
      if (rowMatches_(rows[i - 1], needle)) {
        sheet.deleteRow(i);
        removed += 1;
      }
    }
    return json_({ ok: true, action: "delete", removed: removed });
  }

  let found = 0;
  for (let i = 2; i <= rows.length; i++) {
    if (rowMatches_(rows[i - 1], needle)) {
      sheet.getRange(i, 1, 1, 5).setValues([[name, address, website, hours, notes]]);
      found = i;
      break;
    }
  }
  if (!found) {
    sheet.appendRow([name, address, website, hours, notes]);
  }
  return json_({ ok: true, action: found ? "update" : "insert" });
}
