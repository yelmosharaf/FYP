"""
One-time setup: populate an existing Google Sheet with headers and seed data.

The sheet must already exist and be shared with the service account (Editor).
Set SHEET_ID in GitHub Secrets to the ID from the sheet URL before running.

Usage (local):
    export GOOGLE_CREDENTIALS_JSON='...'
    export SHEET_ID='your-sheet-id'
    python setup_sheets.py
"""

import json
import os

import gspread
from google.oauth2.service_account import Credentials

from sheets import (
    FUND_HEADERS, CONTACT_HEADERS, MEETING_HEADERS,
    TAB_FUNDS, TAB_CONTACTS, TAB_MEETINGS, SCOPES,
)

SEED_FUNDS = [
    [
        "Davidson Kempner Capital Management",
        "Multi-Strategy: Distressed Debt, Corporate Credit, Private Lending, Restructuring",
        "$36B+ AUM",
        "London / New York / HK",
        "davidsonkempner.com",
        "Event-driven, bottom-up fundamental. Major player in European distressed and direct lending.",
    ],
]

SEED_CONTACTS = [
    [
        "1",
        "Hady Eid",
        "Davidson Kempner Capital Management",
        "",
        "https://www.linkedin.com/in/hadyeid/",
        "",
        "",
        "1",
        "",
        (
            "MSc Advanced Finance, IE Business School. "
            "Posts regularly on private credit market dynamics — specifically questions "
            "around falling recovery rates and whether direct lending is maturing. "
            "Thoughtful credit thinker; good for market views on European private credit."
        ),
        "credit, distressed, private lending",
    ],
    [
        "2",
        "Guerino Panetta",
        "",
        "",
        "https://www.linkedin.com/in/guerinopanetta/",
        "",
        "",
        "1",
        "",
        (
            "London-based, Imperial College London background. "
            "Active interest in sovereign debt (Ukraine bondholder situations, BlackRock/Amundi), "
            "and infrastructure investment. UK-focused finance professional."
        ),
        "sovereign, infrastructure, credit",
    ],
]


def _client() -> gspread.Client:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.Client(auth=creds)


def _fmt(ws: gspread.Worksheet) -> None:
    ws.format("1:1", {"textFormat": {"bold": True}})
    ws.freeze(rows=1)


def _get_or_create_tab(spreadsheet, title: str, rows: int = 200, cols: int = 20):
    try:
        return spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def main() -> None:
    import config
    sheet_id = config.SHEET_ID

    print("Step 1/4: Authenticating with Google…")
    client = _client()
    print("         OK")

    # Raw Sheets API probe — shows exact error before gspread wraps it
    print("Step 1b: Raw Sheets API probe…")
    import google.auth.transport.requests
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"]), scopes=SCOPES
    )
    creds.refresh(google.auth.transport.requests.Request())
    import urllib.request as _ur
    req = _ur.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?fields=spreadsheetId",
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    try:
        with _ur.urlopen(req) as resp:
            print(f"         Sheets API OK — {resp.read()}")
    except Exception as probe_err:
        print(f"         Sheets API raw error: {probe_err}")

    print(f"Step 2/4: Opening sheet {sheet_id}…")
    try:
        spreadsheet = client.open_by_key(sheet_id)
        print(f"         OK — '{spreadsheet.title}'")
    except gspread.exceptions.APIError as e:
        print(f"         FAILED — HTTP {e.response.status_code}")
        print(f"         Response body: {e.response.text}")
        raise
    except gspread.exceptions.SpreadsheetNotFound:
        print("         FAILED — SpreadsheetNotFound")
        print("         Possible causes:")
        print("           1. Sheet not shared with service account (check Manage Access)")
        print("           2. Wrong sheet ID hardcoded in config.py")
        print(f"          Service account: {json.loads(os.environ['GOOGLE_CREDENTIALS_JSON'])['client_email']}")
        print(f"          Sheet ID used:   {sheet_id}")
        # Try listing sheets the service account CAN see
        print("         Sheets visible to this service account:")
        try:
            for s in client.list_spreadsheet_files():
                print(f"           - {s['name']} ({s['id']})")
        except Exception as list_err:
            print(f"           (could not list: {list_err})")
        raise

    print("Step 3/4: Creating tabs and writing headers…")
    ws_funds    = _get_or_create_tab(spreadsheet, TAB_FUNDS, rows=50, cols=10)
    ws_contacts = _get_or_create_tab(spreadsheet, TAB_CONTACTS, rows=200, cols=20)
    ws_meetings = _get_or_create_tab(spreadsheet, TAB_MEETINGS, rows=500, cols=10)

    # Only write headers if the sheet is empty
    for ws, headers in [
        (ws_funds,    FUND_HEADERS),
        (ws_contacts, CONTACT_HEADERS),
        (ws_meetings, MEETING_HEADERS),
    ]:
        if ws.row_values(1) != headers:
            ws.clear()
            ws.append_row(headers, value_input_option="USER_ENTERED")
            _fmt(ws)
    print("         OK — Funds, Contacts, Meetings tabs ready")

    print("Step 4/4: Seeding contact data…")
    # Only seed if contacts sheet has just the header row
    if len(ws_contacts.get_all_records()) == 0:
        for row in SEED_FUNDS:
            ws_funds.append_row(row, value_input_option="USER_ENTERED")
        for row in SEED_CONTACTS:
            ws_contacts.append_row(row, value_input_option="USER_ENTERED")
        print("         OK — 1 fund, 2 contacts seeded")
    else:
        print("         Skipped — sheet already has data")

    print()
    print("Setup complete. You can now run 'Weekly Networking Digest'.")
    print(f"Sheet URL: {spreadsheet.url}")


if __name__ == "__main__":
    main()
