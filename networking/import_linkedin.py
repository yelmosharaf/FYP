"""
Import LinkedIn connections from a Google Sheet (exported from LinkedIn archive)
into the Networking Dashboard Contacts sheet.

Works with both native Google Sheets AND Excel (.xlsx) files stored in Drive.
"""

import csv
import io
import json
import os

import gspread
import google.auth.transport.requests
from google.oauth2.service_account import Credentials

import config
from sheets import SCOPES, TAB_CONTACTS, _client, _book

LINKEDIN_FILE_ID = "1C1USxmZjrokQLG-Q9syK0HMYyTedBXLd"

COL_FIRST    = "first name"
COL_LAST     = "last name"
COL_EMAIL    = "email address"
COL_COMPANY  = "company"
COL_POSITION = "position"


def _header_map(headers: list[str]) -> dict[str, int]:
    return {h.strip().lower(): i for i, h in enumerate(headers)}


def _build_linkedin_url(first: str, last: str) -> str:
    name = f"{first.strip()}-{last.strip()}".lower().replace(" ", "-")
    return f"https://www.linkedin.com/in/{name}/"


def _fetch_as_csv() -> list[list[str]]:
    """Download the file via Drive export API — works for both xlsx and Sheets."""
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"]), scopes=SCOPES
    )
    creds.refresh(google.auth.transport.requests.Request())

    import urllib.request as ur
    url = (
        f"https://www.googleapis.com/drive/v3/files/{LINKEDIN_FILE_ID}/export"
        f"?mimeType=text%2Fcsv"
    )
    req = ur.Request(url, headers={"Authorization": f"Bearer {creds.token}"})
    try:
        with ur.urlopen(req) as resp:
            content = resp.read().decode("utf-8-sig")  # strip BOM if present
        print(f"  Downloaded via Drive export API ({len(content)} bytes)")
        reader = csv.reader(io.StringIO(content))
        return list(reader)
    except Exception as e:
        print(f"  Drive export failed: {e}")
        raise


def main() -> None:
    print(f"Fetching LinkedIn export (file {LINKEDIN_FILE_ID})…")
    all_rows = _fetch_as_csv()

    if not all_rows:
        print("ERROR: file is empty.")
        return

    headers = all_rows[0]
    hmap = _header_map(headers)
    data_rows = all_rows[1:]
    print(f"  Columns: {headers}")
    print(f"  {len(data_rows)} connections found")

    # Load existing contacts to deduplicate
    dest = _book()
    ws_contacts = dest.worksheet(TAB_CONTACTS)
    existing = ws_contacts.get_all_records()
    existing_names = {r.get("Name", "").strip().lower() for r in existing}
    next_id = len(existing) + 1

    added = 0
    skipped = 0
    new_rows = []

    for row in data_rows:
        def get(col_key: str) -> str:
            idx = hmap.get(col_key)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        first    = get(COL_FIRST)
        last     = get(COL_LAST)
        email    = get(COL_EMAIL)
        company  = get(COL_COMPANY)
        position = get(COL_POSITION)

        if not first and not last:
            continue

        full_name = f"{first} {last}".strip()
        if full_name.lower() in existing_names:
            skipped += 1
            continue

        new_rows.append([
            str(next_id), full_name, company, position,
            _build_linkedin_url(first, last), email,
            "", "2", "", "", "",
        ])
        existing_names.add(full_name.lower())
        next_id += 1
        added += 1

    if new_rows:
        ws_contacts.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"Done: {added} contacts added, {skipped} duplicates skipped.")
    else:
        print(f"Done: nothing new to add ({skipped} duplicates skipped).")

    print(f"Sheet: https://docs.google.com/spreadsheets/d/{config.SHEET_ID}/edit")


if __name__ == "__main__":
    main()

    hmap = _header_map(headers)
    print(f"  Columns found: {headers}")
    data_rows = all_rows[1:]
    print(f"  {len(data_rows)} connections to process")

    # Load existing contacts to deduplicate
    dest = _book()
    ws_contacts = dest.worksheet(TAB_CONTACTS)
    existing = ws_contacts.get_all_records()
    existing_names = {r.get("Name", "").strip().lower() for r in existing}
    next_id = len(existing) + 1

    added = 0
    skipped = 0
    new_rows = []

    for row in data_rows:
        def get(col_key: str) -> str:
            idx = hmap.get(col_key)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        first    = get(COL_FIRST)
        last     = get(COL_LAST)
        email    = get(COL_EMAIL)
        company  = get(COL_COMPANY)
        position = get(COL_POSITION)

        if not first and not last:
            continue

        full_name = f"{first} {last}".strip()
        if full_name.lower() in existing_names:
            skipped += 1
            continue

        linkedin_url = _build_linkedin_url(first, last)

        new_rows.append([
            str(next_id),    # ID
            full_name,       # Name
            company,         # Fund
            position,        # Role
            linkedin_url,    # LinkedIn (best-effort)
            email,           # Email
            "",              # Last Met
            "2",             # Priority (default: medium)
            "",              # Cadence Override
            "",              # Background
            "",              # Tags
        ])
        existing_names.add(full_name.lower())
        next_id += 1
        added += 1

    if new_rows:
        ws_contacts.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"Done: {added} contacts added, {skipped} duplicates skipped.")
    else:
        print(f"Done: no new contacts to add ({skipped} duplicates skipped).")

    print(f"Open your sheet: https://docs.google.com/spreadsheets/d/{config.SHEET_ID}/edit")


if __name__ == "__main__":
    main()
