import os

# Google Sheets
SHEET_ID = os.environ.get("SHEET_ID", "1-WBZGPRubFQoqmYy-kbIElnPtxX49HxybGTzPeqpnyY")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

# Gmail SMTP
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "elmusharf@gmail.com"
SMTP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
DIGEST_TO = "elmusharf@gmail.com"

# Days between meetings by priority level
CADENCE_DAYS = {1: 30, 2: 60, 3: 90}

# Contacts not met within this many extra days past cadence are flagged urgent
URGENT_BUFFER_DAYS = 14
