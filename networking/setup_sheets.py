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
    return gspread.authorize(creds)


def _fmt(ws: gspread.Worksheet) -> None:
    """Bold header row and freeze it."""
    ws.format("1:1", {"textFormat": {"bold": True}})
    ws.freeze(rows=1)


def main() -> None:
    client = _client()

    title = "Networking Dashboard — London Credit"
    sh = client.create(title)
    print(f"Created sheet: {sh.url}")
    print(f"SHEET_ID = {sh.id}")
    print()
    print("ACTION REQUIRED:")
    print(f"  1. Share this sheet with your service account email (Editor access)")
    print(f"  2. Add SHEET_ID={sh.id} to your .env and GitHub Secrets")
    print()

    # Rename default Sheet1 → Funds
    ws_default = sh.sheet1
    ws_default.update_title(TAB_FUNDS)
    ws_funds = ws_default

    # Contacts sheet
    ws_contacts = sh.add_worksheet(title=TAB_CONTACTS, rows=200, cols=20)

    # Meetings sheet
    ws_meetings = sh.add_worksheet(title=TAB_MEETINGS, rows=500, cols=10)

    # Write headers
    ws_funds.append_row(FUND_HEADERS, value_input_option="USER_ENTERED")
    ws_contacts.append_row(CONTACT_HEADERS, value_input_option="USER_ENTERED")
    ws_meetings.append_row(MEETING_HEADERS, value_input_option="USER_ENTERED")

    # Format headers
    for ws in [ws_funds, ws_contacts, ws_meetings]:
        _fmt(ws)

    # Seed data
    for row in SEED_FUNDS:
        ws_funds.append_row(row, value_input_option="USER_ENTERED")

    for row in SEED_CONTACTS:
        ws_contacts.append_row(row, value_input_option="USER_ENTERED")

    print("Sheet created and seeded with 1 fund, 2 contacts.")
    print(f"Open: {sh.url}")


if __name__ == "__main__":
    main()
