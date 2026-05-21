"""
Import LinkedIn connections from a Google Sheet (exported from LinkedIn archive)
into the Networking Dashboard Contacts sheet.

Reads from the LinkedIn export sheet, maps columns, deduplicates, and appends
new contacts. Run once via GitHub Actions.
"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

import config
from sheets import (
    SCOPES, TAB_CONTACTS, CONTACT_HEADERS,
    _client, _book,
)

LINKEDIN_SHEET_ID = "1C1USxmZjrokQLG-Q9syK0HMYyTedBXLd"

# LinkedIn export column names (case-insensitive matched)
COL_FIRST   = "first name"
COL_LAST    = "last name"
COL_EMAIL   = "email address"
COL_COMPANY = "company"
COL_POSITION = "position"
COL_CONNECTED = "connected on"


def _header_map(headers: list[str]) -> dict[str, int]:
    """Return lowercase-header → column-index map."""
    return {h.strip().lower(): i for i, h in enumerate(headers)}


def _build_linkedin_url(first: str, last: str) -> str:
    """Best-effort LinkedIn search URL — user can replace with real profile URL."""
    name = f"{first.strip()}-{last.strip()}".lower().replace(" ", "-")
    return f"https://www.linkedin.com/in/{name}/"


def main() -> None:
    client = _client()

    print(f"Reading LinkedIn export sheet {LINKEDIN_SHEET_ID}…")
    try:
        src = client.open_by_key(LINKEDIN_SHEET_ID)
    except gspread.exceptions.SpreadsheetNotFound:
        print("ERROR: Sheet not found. Share it with the service account as Viewer first.")
        print(f"       {json.loads(os.environ['GOOGLE_CREDENTIALS_JSON'])['client_email']}")
        raise

    ws_src = src.sheet1
    all_rows = ws_src.get_all_values()
    if not all_rows:
        print("ERROR: LinkedIn sheet is empty.")
        return

    headers = all_rows[0]
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
