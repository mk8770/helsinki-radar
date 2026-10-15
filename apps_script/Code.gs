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

function headerIndex_(headers, names) {
  for (let i = 0; i < headers.length; i++) {
    const h = String(headers[i] || "")
      .trim()
      .toLowerCase();
    if (names.indexOf(h) !== -1) {
      return i;
    }
  }
  return -1;
}

function writeLeadRow_(sheet, rowIndex, d) {
  const lastCol = Math.max(sheet.getLastColumn(), 5);
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const values = sheet.getRange(rowIndex, 1, 1, lastCol).getValues()[0];
  function setCol(cands, val) {
    const idx = headerIndex_(headers, cands);
    if (idx >= 0) {
      values[idx] = val;
    }
  }
  setCol(["name"], d.name || "");
  setCol(["address", "adress"], d.address || "");
  setCol(["website"], d.website || "");
  setCol(["hours"], d.hours || "");
  setCol(["notes"], d.notes || "");
  if (headerIndex_(headers, ["website"]) < 0) {
    values[2] = d.website || "";
  }
  sheet.getRange(rowIndex, 1, 1, lastCol).setValues([values]);
}

function rowMatches_(row, needle) {
  if (!needle) {
    return false;
  }
  const addr = norm_(row[1]);
  const name = norm_(row[0]);
  return addr === needle || name === needle || (addr && (addr.indexOf(needle) !== -1 || needle.indexOf(addr) !== -1));
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
  const needle = norm_(d.match || address) || norm_(name);
  const rows = sheet.getDataRange().getValues();
  const payload = { name: name, address: address, website: website, hours: hours, notes: notes };

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
      writeLeadRow_(sheet, i, payload);
      found = i;
      break;
    }
  }
  if (!found) {
    sheet.appendRow([name, address, website, hours, notes]);
  }
  return json_({ ok: true, action: found ? "update" : "insert", website: website });
}
