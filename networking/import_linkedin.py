"""
Import LinkedIn connections from a Google Sheet into the Networking Dashboard.
Handles LinkedIn exports that have metadata rows before the actual headers.
"""

import json
import os

import gspread

import config
from sheets import TAB_CONTACTS, _client, _book

LINKEDIN_FILE_ID = "1q8ue4nYRDH5jTJqP_i45x9b-8hKPVxXX613CYFJbkhY"

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


def _fetch_rows() -> list[list[str]]:
    client = _client()
    try:
        src = client.open_by_key(LINKEDIN_FILE_ID)
    except gspread.exceptions.SpreadsheetNotFound:
        creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
        print("ERROR: sheet not found. Share it with the service account as Viewer:")
        print(f"  {creds_dict['client_email']}")
        raise
    rows = src.sheet1.get_all_values()
    print(f"  Read {len(rows)} rows")
    return rows


def _find_header_row(all_rows: list[list[str]]) -> int:
    """LinkedIn exports have metadata lines before the real header row.
    Scan until we find a row containing 'First Name'."""
    for i, row in enumerate(all_rows):
        row_lower = [c.strip().lower() for c in row]
        if COL_FIRST in row_lower or "firstname" in row_lower:
            return i
    return -1


def main() -> None:
    print(f"Fetching LinkedIn export (file {LINKEDIN_FILE_ID})…")
    all_rows = _fetch_rows()

    if not all_rows:
        print("ERROR: file is empty.")
        return

    header_idx = _find_header_row(all_rows)
    if header_idx == -1:
        print("ERROR: could not find header row with 'First Name'.")
        print(f"  First 5 rows: {all_rows[:5]}")
        return

    if header_idx > 0:
        print(f"  Skipped {header_idx} metadata row(s) before headers")

    headers   = all_rows[header_idx]
    data_rows = all_rows[header_idx + 1:]
    hmap      = _header_map(headers)
    print(f"  Columns: {headers}")
    print(f"  {len(data_rows)} connections to process")

    # Load existing contacts to deduplicate
    ws_contacts = _book().worksheet(TAB_CONTACTS)
    existing = ws_contacts.get_all_records()
    existing_names = {r.get("Name", "").strip().lower() for r in existing}
    next_id = len(existing) + 1

    new_rows = []
    added = skipped = 0

    for row in data_rows:
        def get(col_key: str, _row: list = row, _hmap: dict = hmap) -> str:
            idx = _hmap.get(col_key)
            return _row[idx].strip() if idx is not None and idx < len(_row) else ""

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
        # Write in batches of 500 to avoid API limits
        for i in range(0, len(new_rows), 500):
            ws_contacts.append_rows(new_rows[i:i+500], value_input_option="USER_ENTERED")
            print(f"  Written rows {i+1}–{min(i+500, len(new_rows))}")
        print(f"Done: {added} contacts added, {skipped} duplicates skipped.")
    else:
        print(f"Done: nothing new to add ({skipped} duplicates skipped).")

    print(f"Sheet: https://docs.google.com/spreadsheets/d/{config.SHEET_ID}/edit")


if __name__ == "__main__":
    main()
