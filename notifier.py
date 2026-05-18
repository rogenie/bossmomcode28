"""
notifier.py — 9nth Dimension LLC
Discord + Pushover real-time notification system for Instagram posting pipeline.
Drop into any of the 14 account repos unchanged.

Notification failures NEVER break the posting flow — all wrapped in try/except.

Env vars per Railway project:
  DISCORD_WEBHOOK_URL      — Master #posting-feed channel webhook
  DISCORD_WEBHOOK_ACCOUNT  — (optional) Per-account channel webhook
  PRIORITY_ACCOUNT         — Set "true" for top 3 revenue accounts
  PUSHOVER_APP_TOKEN       — Pushover app token (priority accounts only)
  PUSHOVER_USER_KEY        — Pushover user key (priority accounts only)
"""

import os
import sqlite3
import logging
import traceback
import requests
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

log = logging.getLogger("notifier")

# ── Brand colors ──────────────────────────────────────────────────────────────
COLOR_SUCCESS = 0x2ECC71   # Green
COLOR_FAILURE = 0xE74C3C   # Red
COLOR_WARNING = 0xF39C12   # Orange
COLOR_SKIP    = 0x95A5A6   # Grey

PACIFIC            = ZoneInfo("America/Los_Angeles")
UTC                = timezone.utc
THROTTLE_THRESHOLD = 3   # consecutive retried posts before warning alert

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(UTC)


def _timestamps() -> tuple[str, str]:
    now = _now_utc()
    return (
        now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        now.astimezone(PACIFIC).strftime("%Y-%m-%d %H:%M:%S PT"),
    )


# ── Throttle tracking (local SQLite) ─────────────────────────────────────────

def _db_path() -> Path:
    return Path(__file__).parent / "notifier_state.db"


def _init_db():
    con = sqlite3.connect(_db_path())
    con.execute("""
        CREATE TABLE IF NOT EXISTS retry_history (
            account      TEXT PRIMARY KEY,
            consecutive  INTEGER DEFAULT 0,
            last_updated TEXT
        )
    """)
    con.commit()
    con.close()


def _update_retry_count(account: str, had_retries: bool) -> int:
    """Update consecutive retry count. Returns new count."""
    _init_db()
    con = sqlite3.connect(_db_path())
    row = con.execute(
        "SELECT consecutive FROM retry_history WHERE account=?", (account,)
    ).fetchone()
    current   = row[0] if row else 0
    new_count = current + 1 if had_retries else 0
    ts        = _now_utc().isoformat()
    con.execute("""
        INSERT INTO retry_history (account, consecutive, last_updated)
        VALUES (?, ?, ?)
        ON CONFLICT(account) DO UPDATE SET consecutive=?, last_updated=?
    """, (account, new_count, ts, new_count, ts))
    con.commit()
    con.close()
    return new_count


# ── Discord ───────────────────────────────────────────────────────────────────

def _webhook_url() -> str:
    # Per-account channel takes priority; falls back to master feed
    return (
        os.environ.get("DISCORD_WEBHOOK_ACCOUNT", "").strip() or
        os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    )


def _send_embed(embed: dict) -> bool:
    url = _webhook_url()
    if not url:
        log.debug("No Discord webhook configured — skipping")
        return False
    try:
        r = requests.post(url, json={"embeds": [embed]}, timeout=10)
        return r.status_code in (200, 204)
    except Exception as e:
        log.debug(f"Discord send failed: {e}")
        return False


# ── Pushover ──────────────────────────────────────────────────────────────────

def _send_pushover(title: str, message: str, priority: int = 1) -> bool:
    """
    priority 0 = normal
    priority 1 = high — bypasses quiet hours / Do Not Disturb
    priority 2 = emergency — requires acknowledgment, retries every 60s
    """
    token    = os.environ.get("PUSHOVER_APP_TOKEN", "")
    user_key = os.environ.get("PUSHOVER_USER_KEY", "")
    if not token or not user_key:
        return False
    try:
        payload = {
            "token":    token,
            "user":     user_key,
            "title":    title[:250],
            "message":  message[:1024],
            "priority": priority,
        }
        if priority == 2:
            payload["retry"]  = 60
            payload["expire"] = 3600
        r = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=payload,
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        log.debug(f"Pushover send failed: {e}")
        return False


def _is_priority_account() -> bool:
    return os.environ.get("PRIORITY_ACCOUNT", "").lower() == "true"


# ── Public API ────────────────────────────────────────────────────────────────

def notify_success(
    account:     str,
    post_id:     str,
    caption:     str,
    image_url:   str,
    retry_count: int = 0,
    platform:    str = "instagram",
) -> None:
    """
    Call after a successful post publish.

    account:     "@computatio28"
    post_id:     Instagram media ID returned by Graph API
    caption:     Full caption text
    image_url:   Cloudflare R2 URL of the first slide
    retry_count: Number of retries needed (0 = succeeded first time)
    platform:    "instagram" or "facebook"
    """
    try:
        utc_str, pt_str = _timestamps()
        caption_preview = caption[:200] + "…" if len(caption) > 200 else caption
        ig_url          = f"https://www.instagram.com/p/{post_id}/" if post_id else "N/A"
        retry_note      = f" _(after {retry_count} {'retry' if retry_count == 1 else 'retries'})_" if retry_count > 0 else ""

        embed = {
            "color":       COLOR_SUCCESS,
            "title":       f"✅  Posted Successfully{retry_note}",
            "description": f"**{account}**  ·  {platform.title()}",
            "fields": [
                {"name": "🕐  Time",           "value": f"{pt_str}\n{utc_str}",              "inline": True},
                {"name": "🔗  Post",           "value": f"[View on Instagram]({ig_url})",    "inline": True},
                {"name": "🖼️  First Slide",    "value": f"[View on R2]({image_url})",        "inline": True},
                {"name": "📝  Caption Preview","value": f"```{caption_preview}```",           "inline": False},
            ],
            "footer":    {"text": "9nth Dimension LLC · Posting Engine"},
            "timestamp": _now_utc().isoformat(),
        }
        _send_embed(embed)

        # Throttle tracking
        consecutive = _update_retry_count(account, had_retries=retry_count > 0)
        if retry_count > 0 and consecutive >= THROTTLE_THRESHOLD:
            notify_throttle_warning(account, consecutive)

    except Exception as e:
        log.debug(f"notify_success swallowed: {e}")


def notify_failure(
    account:     str,
    error:       Exception,
    platform:    str = "instagram",
    retry_count: int = 0,
    context:     str = "",
) -> None:
    """
    Call in the except block when a post fails.
    Sends Discord embed + Pushover alert for priority accounts.

    account:     "@computatio28"
    error:       The caught exception
    platform:    "instagram" or "facebook"
    retry_count: Retries attempted before giving up
    context:     Optional stage e.g. "carousel creation", "R2 upload"
    """
    try:
        utc_str, pt_str = _timestamps()
        tb          = traceback.format_exc()
        tb_preview  = ("…" + tb[-880:]) if len(tb) > 880 else tb
        error_str   = str(error)[:400]
        context_txt = f"\n**Stage:** {context}" if context else ""
        retry_txt   = f"\n**Retries attempted:** {retry_count}" if retry_count > 0 else ""

        embed = {
            "color":       COLOR_FAILURE,
            "title":       f"❌  Post Failed — {account}",
            "description": f"**{account}**  ·  {platform.title()}{context_txt}{retry_txt}",
            "fields": [
                {"name": "🕐  Time",        "value": f"{pt_str}\n{utc_str}", "inline": True},
                {"name": "💥  Error",       "value": f"```{error_str}```",  "inline": False},
                {"name": "🔍  Stack Trace", "value": f"```{tb_preview}```", "inline": False},
            ],
            "footer":    {"text": "9nth Dimension LLC · Posting Engine"},
            "timestamp": _now_utc().isoformat(),
        }
        _send_embed(embed)

        # Pushover for priority accounts — high priority bypasses Do Not Disturb
        if _is_priority_account():
            _send_pushover(
                title=f"🚨 Post Failed: {account}",
                message=f"{platform.title()} post failed\n\n{error_str}\n\n{pt_str}",
                priority=1,
            )

        _update_retry_count(account, had_retries=retry_count > 0)

    except Exception as e:
        log.debug(f"notify_failure swallowed: {e}")


def notify_skip(
    account:  str,
    reason:   str,
    platform: str = "instagram",
) -> None:
    """
    Call when the scheduler intentionally skips a posting slot.

    account:  "@computatio28"
    reason:   Why it was skipped e.g. "token expired", "rate limited"
    platform: Platform that was skipped
    """
    try:
        utc_str, pt_str = _timestamps()
        embed = {
            "color":       COLOR_SKIP,
            "title":       f"⏭️  Post Skipped — {account}",
            "description": f"**{account}**  ·  {platform.title()}",
            "fields": [
                {"name": "🕐  Time",   "value": f"{pt_str}\n{utc_str}", "inline": True},
                {"name": "📋  Reason", "value": reason,                 "inline": False},
            ],
            "footer":    {"text": "9nth Dimension LLC · Posting Engine"},
            "timestamp": _now_utc().isoformat(),
        }
        _send_embed(embed)
    except Exception as e:
        log.debug(f"notify_skip swallowed: {e}")


def notify_throttle_warning(account: str, consecutive_count: int) -> None:
    """
    Triggered automatically when an account retries 3+ consecutive posts.
    Always sends Pushover regardless of PRIORITY_ACCOUNT setting.
    """
    try:
        utc_str, pt_str = _timestamps()
        embed = {
            "color": COLOR_WARNING,
            "title": f"⚠️  Throttle Warning — {account}",
            "description": (
                f"**{account}** has required retries on "
                f"**{consecutive_count} consecutive posts**.\n"
                f"Meta may be throttling this account."
            ),
            "fields": [
                {"name": "🕐  Detected",                  "value": f"{pt_str}\n{utc_str}", "inline": True},
                {"name": "📊  Consecutive Retried Posts", "value": str(consecutive_count), "inline": True},
                {
                    "name":   "🔧  Recommended Actions",
                    "value":  "• Check Railway deploy logs\n• Reduce POST_TIMES frequency\n• Run token health check\n• Consider 24hr posting pause",
                    "inline": False,
                },
            ],
            "footer":    {"text": "9nth Dimension LLC · Posting Engine"},
            "timestamp": _now_utc().isoformat(),
        }
        _send_embed(embed)

        # Always push throttle warnings — this is a real issue
        _send_pushover(
            title=f"⚠️ Throttle Warning: {account}",
            message=(
                f"{consecutive_count} consecutive retried posts.\n"
                f"Meta may be throttling this account.\n\n{pt_str}"
            ),
            priority=1,
        )
    except Exception as e:
        log.debug(f"notify_throttle_warning swallowed: {e}")
