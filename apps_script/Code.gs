function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}

function doGet() {
  return json_({ ok: true, service: "helsinki-leads" });
}

function doPost(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const d = JSON.parse((e && e.postData && e.postData.contents) || "{}");
  const action = d.action || "upsert";
  const name = d.name || "";
  const address = d.address || d.adress || "";
  const website = d.website || "";
  const hours = d.hours || "";
  const notes = d.notes || "";
  const needle = String(address).toLowerCase().trim();
  const rows = sheet.getDataRange().getValues();

  if (action === "delete") {
    for (let i = rows.length; i >= 2; i--) {
      const rowAddr = String(rows[i - 1][1] || "").toLowerCase().trim();
      if (needle && rowAddr === needle) {
        sheet.deleteRow(i);
      }
    }
    return json_({ ok: true, action: "delete" });
  }

  let found = 0;
  for (let i = 2; i <= rows.length; i++) {
    const rowAddr = String(rows[i - 1][1] || "").toLowerCase().trim();
    if (needle && rowAddr === needle) {
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
