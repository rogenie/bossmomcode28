"""
@bossmomcode28 — Config
Wealthy Single Mom Empowerment — Money AND Peace
"""
import os
from pathlib import Path

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-...")

META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "EAA...")
INSTAGRAM_USER_ID = os.environ.get("INSTAGRAM_USER_ID", "")
FACEBOOK_PAGE_ID  = os.environ.get("FACEBOOK_PAGE_ID",  "")
META_API_VERSION  = "v19.0"

R2_ACCOUNT_ID  = os.environ.get("R2_ACCOUNT_ID",  "")
R2_ACCESS_KEY  = os.environ.get("R2_ACCESS_KEY",  "")
R2_SECRET_KEY  = os.environ.get("R2_SECRET_KEY",  "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "bossmomcode28")
R2_PUBLIC_URL  = os.environ.get("R2_PUBLIC_URL",  "https://pub-YOURPUBLICHASH.r2.dev")

_times_env    = os.environ.get("POSTING_TIMES", "07:00,12:00,19:00")
POSTING_TIMES = [t.strip() for t in _times_env.split(",")]
TIMEZONE      = os.environ.get("TIMEZONE", "America/Los_Angeles")

_platforms_env = os.environ.get("POST_PLATFORMS", "instagram")
POST_PLATFORMS = [p.strip() for p in _platforms_env.split(",")]

ACCOUNT_HANDLE   = "@bossmomcode28"
NICHE            = "Single Mom Empowerment"
SLIDE_W, SLIDE_H = 1080, 1350

BASE_DIR    = Path(__file__).parent
SLIDES_DIR  = BASE_DIR / "slides_output"
DB_PATH     = BASE_DIR / "bossmomcode28.db"
LOG_PATH    = BASE_DIR / "run.log"
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")

MAX_RETRIES   = 3
RETRY_DELAY_S = 900
