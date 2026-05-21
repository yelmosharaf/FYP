"""Google Sheets read/write helpers for the networking dashboard."""

import json
import os
from datetime import date, datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Sheet tab names
TAB_FUNDS = "Funds"
TAB_CONTACTS = "Contacts"
TAB_MEETINGS = "Meetings"

FUND_HEADERS = ["Fund Name", "Strategy", "AUM", "Location", "Website", "Notes"]

CONTACT_HEADERS = [
    "ID", "Name", "Fund", "Role", "LinkedIn", "Email",
    "Last Met", "Priority", "Cadence Override (days)", "Background", "Tags",
]

MEETING_HEADERS = [
    "Date", "Contact Name", "Fund", "Type", "Notes", "Action Items", "Follow Up By",
]


def _client() -> gspread.Client:
    creds_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.Client(auth=creds)


def _book() -> gspread.Spreadsheet:
    import config
    return _client().open_by_key(config.SHEET_ID)


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------

def get_funds() -> list[dict]:
    ws = _book().worksheet(TAB_FUNDS)
    return ws.get_all_records()


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

def get_contacts() -> list[dict]:
    ws = _book().worksheet(TAB_CONTACTS)
    return ws.get_all_records()


def log_meeting(contact_name: str, fund: str, meeting_date: str,
                meeting_type: str = "Coffee", notes: str = "", action_items: str = "",
                follow_up_by: str = "") -> None:
    """Append a row to the Meetings log and update Last Met on the contact."""
    book = _book()

    # Append to meeting log
    ws_meetings = book.worksheet(TAB_MEETINGS)
    ws_meetings.append_row(
        [meeting_date, contact_name, fund, meeting_type, notes, action_items, follow_up_by],
        value_input_option="USER_ENTERED",
    )

    # Update Last Met on Contacts sheet
    ws_contacts = book.worksheet(TAB_CONTACTS)
    records = ws_contacts.get_all_records()
    headers = ws_contacts.row_values(1)
    last_met_col = headers.index("Last Met") + 1

    for i, row in enumerate(records, start=2):
        if row.get("Name", "").strip().lower() == contact_name.strip().lower():
            ws_contacts.update_cell(i, last_met_col, meeting_date)
            break


def get_meetings(days_back: int = 90) -> list[dict]:
    ws = _book().worksheet(TAB_MEETINGS)
    records = ws.get_all_records()
    cutoff = date.today().toordinal() - days_back
    result = []
    for r in records:
        try:
            d = _parse_date(r.get("Date", ""))
            if d and d.toordinal() >= cutoff:
                result.append(r)
        except Exception:
            pass
    return sorted(result, key=lambda r: r.get("Date", ""), reverse=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None
