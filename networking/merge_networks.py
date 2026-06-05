"""
Merge multiple HL officers' LinkedIn networks into the master Contacts sheet.

Usage:
  python merge_networks.py

Add each officer's LinkedIn export Google Sheet to OFFICER_SOURCES below.
Each contact is tagged "via: Officer Name" so you know whose network it came from.
Contacts already in the sheet get their Tags updated with new source info.
"""

import json
import os

import gspread

import config
from sheets import TAB_CONTACTS, _client, _book

# ── Configure sources here ────────────────────────────────────────────────────
# Format: (google_sheet_id, officer_name)
# Share each sheet with the service account as Viewer before running.
OFFICER_SOURCES = [
    ("1q8ue4nYRDH5jTJqP_i45x9b-8hKPVxXX613CYFJbkhY", "Yousif Elmusharf"),
    # ("SHEET_ID_2", "MD Name"),
    # ("SHEET_ID_3", "Analyst Name"),
]
# ─────────────────────────────────────────────────────────────────────────────

COL_FIRST    = "first name"
COL_LAST     = "last name"
COL_EMAIL    = "email address"
COL_COMPANY  = "company"
COL_POSITION = "position"


def _s(v) -> str:
    return str(v or "").strip()


def _header_map(headers: list[str]) -> dict[str, int]:
    return {h.strip().lower(): i for i, h in enumerate(headers)}


def _find_header_row(rows: list[list[str]]) -> int:
    for i, row in enumerate(rows):
        lower = [c.strip().lower() for c in row]
        if COL_FIRST in lower or "firstname" in lower:
            return i
    return -1


def _linkedin_url(first: str, last: str) -> str:
    slug = f"{first.strip()}-{last.strip()}".lower().replace(" ", "-")
    return f"https://www.linkedin.com/in/{slug}/"


def _add_via_tag(existing_tags: str, officer: str) -> str:
    tag = f"via: {officer}"
    parts = [t.strip() for t in existing_tags.split(";") if t.strip()]
    if tag not in parts:
        parts.append(tag)
    return "; ".join(parts)


def _fetch_source(client: gspread.Client, sheet_id: str, officer: str) -> list[dict]:
    """Return list of contact dicts from one LinkedIn export sheet."""
    try:
        src = client.open_by_key(sheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
        print(f"  ERROR: sheet {sheet_id} not found. Share it with the service account:")
        print(f"    {creds_dict['client_email']}")
        return []

    all_rows = src.sheet1.get_all_values()
    if not all_rows:
        print(f"  WARNING: sheet for {officer} is empty, skipping.")
        return []

    header_idx = _find_header_row(all_rows)
    if header_idx == -1:
        print(f"  WARNING: no header row found for {officer}, skipping.")
        return []

    if header_idx > 0:
        print(f"    Skipped {header_idx} metadata row(s)")

    headers   = all_rows[header_idx]
    data_rows = all_rows[header_idx + 1:]
    hmap      = _header_map(headers)
    print(f"    {len(data_rows)} rows from {officer}'s export")

    contacts = []
    for row in data_rows:
        def get(col: str, _row=row, _hmap=hmap) -> str:
            idx = _hmap.get(col)
            return _row[idx].strip() if idx is not None and idx < len(_row) else ""

        first    = get(COL_FIRST)
        last     = get(COL_LAST)
        company  = get(COL_COMPANY)
        position = get(COL_POSITION)
        email    = get(COL_EMAIL)

        if not first and not last:
            continue

        full_name = f"{first} {last}".strip()
        contacts.append({
            "name":     full_name,
            "fund":     company,
            "role":     position,
            "email":    email,
            "linkedin": _linkedin_url(first, last),
            "officer":  officer,
        })

    return contacts


def main() -> None:
    client = _client()
    book   = _book()
    ws     = book.worksheet(TAB_CONTACTS)

    # ── Load existing contacts ────────────────────────────────────────────────
    print("Loading existing contacts…")
    existing_records = ws.get_all_records()
    headers          = ws.row_values(1)
    tags_col         = headers.index("Tags") + 1  # 1-based

    # name.lower() → {row_index (2-based), current_tags}
    existing: dict[str, dict] = {}
    for i, r in enumerate(existing_records, start=2):
        name = _s(r.get("Name")).lower()
        if name:
            existing[name] = {
                "row":  i,
                "tags": _s(r.get("Tags")),
            }

    print(f"  {len(existing)} existing contacts")

    # ── Collect from all sources ──────────────────────────────────────────────
    # merged_new: dedup key → contact dict (first source wins for field values)
    # merged_new: we also accumulate all officers for the Tags field
    merged: dict[str, dict] = {}  # name.lower() → contact

    for sheet_id, officer in OFFICER_SOURCES:
        print(f"\nFetching {officer}'s network (sheet {sheet_id})…")
        contacts = _fetch_source(client, sheet_id, officer)
        for c in contacts:
            key = c["name"].lower()
            if key in merged:
                # Already seen from another officer — just add the source tag
                existing_tags = merged[key]["officers"]
                tag = f"via: {officer}"
                if tag not in existing_tags:
                    existing_tags.append(tag)
            else:
                merged[key] = {
                    "name":     c["name"],
                    "fund":     c["fund"],
                    "role":     c["role"],
                    "email":    c["email"],
                    "linkedin": c["linkedin"],
                    "officers": [f"via: {officer}"],
                }

    print(f"\nTotal unique contacts across all sources: {len(merged)}")

    # ── Split: new vs already-in-sheet ───────────────────────────────────────
    to_add:    list[list[str]] = []
    to_update: list[tuple[int, str]] = []  # (row_index, new_tags_value)

    next_id = len(existing_records) + 1

    for key, c in merged.items():
        via_tag = "; ".join(c["officers"])
        if key in existing:
            # Contact exists — update Tags column only if new source info
            ex = existing[key]
            new_tags = ex["tags"]
            for tag in c["officers"]:
                if tag not in new_tags:
                    new_tags = _add_via_tag(new_tags, tag.replace("via: ", ""))
            if new_tags != ex["tags"]:
                to_update.append((ex["row"], new_tags))
        else:
            to_add.append([
                str(next_id),
                c["name"],
                c["fund"],
                c["role"],
                c["linkedin"],
                c["email"],
                "",        # Last Met
                "2",       # Priority default P2
                "",        # Cadence Override
                "",        # Background
                via_tag,   # Tags — "via: Officer A; via: Officer B"
            ])
            next_id += 1

    # ── Write new contacts ────────────────────────────────────────────────────
    if to_add:
        print(f"\nAdding {len(to_add)} new contacts…")
        for i in range(0, len(to_add), 500):
            ws.append_rows(to_add[i:i+500], value_input_option="USER_ENTERED")
            print(f"  Written rows {i+1}–{min(i+500, len(to_add))}")
    else:
        print("\nNo new contacts to add.")

    # ── Update tags on existing contacts ─────────────────────────────────────
    if to_update:
        print(f"Updating Tags on {len(to_update)} existing contacts…")
        # Batch as individual cell updates (no bulk API for scattered cells)
        for row_idx, new_tags in to_update:
            ws.update_cell(row_idx, tags_col, new_tags)
        print(f"  Done.")
    else:
        print("No tag updates needed.")

    added    = len(to_add)
    updated  = len(to_update)
    skipped  = len(merged) - added - updated
    print(f"\nSummary: {added} added · {updated} tags updated · {skipped} already fully up to date")
    print(f"Sheet: https://docs.google.com/spreadsheets/d/{config.SHEET_ID}/edit")


if __name__ == "__main__":
    main()
