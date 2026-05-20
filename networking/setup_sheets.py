"""
One-time setup: create the networking Google Sheet with headers and seed data.

Usage:
    export GOOGLE_CREDENTIALS_JSON='<service-account-json>'
    python setup_sheets.py

After running, copy the printed SHEET_ID into your .env and GitHub Secret.
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
        "",                                           # Role — fill in when known
        "https://www.linkedin.com/in/hadyeid/",
        "",                                           # Email
        "",                                           # Last Met — blank until you log first meeting
        "1",                                          # Priority
        "",                                           # Cadence override
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
        "",                                           # Fund — fill in when confirmed
        "",                                           # Role
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
    """Bold header row and freeze it."""
    ws.format("1:1", {"textFormat": {"bold": True}})
    ws.freeze(rows=1)


OWNER_EMAIL = "elmusharf@gmail.com"


def main() -> None:
    print("Step 1/6: Authenticating with Google…")
    client = _client()
    print("         OK")

    print("Step 2/6: Creating spreadsheet…")
    title = "Networking Dashboard — London Credit"
    spreadsheet = client.create(title)
    print(f"         OK — id={spreadsheet.id}")

    print(f"Step 3/6: Sharing with {OWNER_EMAIL}…")
    spreadsheet.share(OWNER_EMAIL, perm_type="user", role="writer", notify=False)
    print("         OK")

    print("Step 4/6: Creating tabs…")
    ws_default = spreadsheet.sheet1
    ws_default.update_title(TAB_FUNDS)
    ws_funds = ws_default
    ws_contacts = spreadsheet.add_worksheet(title=TAB_CONTACTS, rows=200, cols=20)
    ws_meetings = spreadsheet.add_worksheet(title=TAB_MEETINGS, rows=500, cols=10)
    print("         OK — Funds, Contacts, Meetings")

    print("Step 5/6: Writing headers…")
    ws_funds.append_row(FUND_HEADERS, value_input_option="USER_ENTERED")
    ws_contacts.append_row(CONTACT_HEADERS, value_input_option="USER_ENTERED")
    ws_meetings.append_row(MEETING_HEADERS, value_input_option="USER_ENTERED")
    for ws in [ws_funds, ws_contacts, ws_meetings]:
        _fmt(ws)
    print("         OK")

    print("Step 6/6: Seeding contact data…")
    for row in SEED_FUNDS:
        ws_funds.append_row(row, value_input_option="USER_ENTERED")
    for row in SEED_CONTACTS:
        ws_contacts.append_row(row, value_input_option="USER_ENTERED")
    print("         OK — 1 fund, 2 contacts")

    print()
    print(f"::notice::SHEET_ID={spreadsheet.id}")
    print(f"Sheet URL: {spreadsheet.url}")
    print()
    print("NEXT STEP: add SHEET_ID as a GitHub Secret, then run 'Weekly Networking Digest'")


if __name__ == "__main__":
    main()
