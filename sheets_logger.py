"""
9nth Dimension LLC — Google Sheets Logger
Logs every post to the central dashboard sheet.

Sheet columns:
Date | Time | Account | Niche | Topic | Hook | Pillar/Style | Platform | Status | Post ID | Error
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("sheets_logger")

SHEET_ID = "1EipIbJBLikma708GPGpoIDH75r4vX5KPn8hSt88wZFQ"
SHEET_TAB = "Posts"

def _get_service():
    """Build Google Sheets service from credentials."""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        # Try Railway env var first, then local file
        creds_json = os.environ.get("GOOGLE_SHEETS_CREDS")
        if creds_json:
            creds_info = json.loads(creds_json)
        else:
            # Look for local credentials file
            creds_path = Path(__file__).parent / "google_creds.json"
            if not creds_path.exists():
                log.warning("No Google credentials found — skipping sheets logging")
                return None
            creds_info = json.loads(creds_path.read_text())

        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        log.warning(f"Google Sheets auth failed: {e}")
        return None


def log_post(account: str, niche: str, topic: str, hook: str,
             pillar: str, platform: str, status: str,
             post_id: str = "", error: str = ""):
    """
    Log a post result to the central Google Sheet.
    Fails silently — never crashes the pipeline.
    """
    try:
        service = _get_service()
        if not service:
            return

        now = datetime.now()
        row = [
            now.strftime("%Y-%m-%d"),           # Date
            now.strftime("%H:%M:%S"),           # Time
            account,                             # Account
            niche,                               # Niche
            topic[:80],                          # Topic
            hook[:100],                          # Hook
            pillar,                              # Pillar/Style
            platform,                            # Platform
            status,                              # Status
            post_id,                             # Post ID
            error[:200] if error else "",        # Error
        ]

        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"{SHEET_TAB}!A:K",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]}
        ).execute()

        log.info(f"  Logged to sheets: {account} — {status}")

    except Exception as e:
        log.warning(f"  Sheets logging failed (non-critical): {e}")


def setup_sheet_headers():
    """
    Creates the header row if the sheet is empty.
    Run once manually or on first deploy.
    """
    try:
        service = _get_service()
        if not service:
            return

        headers = [[
            "Date", "Time", "Account", "Niche", "Topic",
            "Hook", "Pillar/Style", "Platform", "Status", "Post ID", "Error"
        ]]

        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=f"{SHEET_TAB}!A1:K1",
            valueInputOption="RAW",
            body={"values": headers}
        ).execute()

        print("Sheet headers created successfully.")

    except Exception as e:
        print(f"Failed to create headers: {e}")


if __name__ == "__main__":
    setup_sheet_headers()
    print("Testing sheets logger...")
    log_post(
        account="@pixielandmedia",
        niche="AI Education",
        topic="Test topic",
        hook="Test hook",
        pillar="technology",
        platform="instagram",
        status="test",
        post_id="test123"
    )
    print("Done — check your Google Sheet!")
