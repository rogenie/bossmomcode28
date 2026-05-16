"""
@bossmomcode28 — Scheduler
Wealthy single mom empowerment pipeline. Posts 3x/day.
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
import random
from datetime import datetime
from pathlib import Path

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    raise SystemExit("pip install apscheduler")

import config as cfg
from slide_generator import generate_copy, render_slide, TOPIC_QUEUE, OUTPUT_DIR
from poster import post_to_all_platforms

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(cfg.LOG_PATH),
    ],
)
log = logging.getLogger("bossmom_scheduler")

DB_PATH = cfg.DB_PATH

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            topic       TEXT,
            pillar      TEXT,
            hook        TEXT,
            folder      TEXT,
            status      TEXT DEFAULT 'running',
            error       TEXT
        );
        CREATE TABLE IF NOT EXISTS posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER NOT NULL,
            platform    TEXT NOT NULL,
            status      TEXT DEFAULT 'queued',
            posted_at   TEXT,
            post_id     TEXT,
            attempts    INTEGER DEFAULT 0,
            error       TEXT
        );
        CREATE TABLE IF NOT EXISTS used_topics (
            topic   TEXT PRIMARY KEY,
            used_at TEXT NOT NULL
        );
    """)
    con.commit(); con.close()

def mark_topic_used(topic):
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT OR REPLACE INTO used_topics (topic, used_at) VALUES (?,?)",
                (topic, datetime.now().isoformat()))
    con.commit(); con.close()

def get_used_topics():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT topic FROM used_topics").fetchall()
    con.close()
    return {r[0] for r in rows}

def pick_next_topic():
    used = get_used_topics()
    available = [t for t in TOPIC_QUEUE if t["topic"] not in used]
    if not available:
        log.info("All topics used — resetting queue.")
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM used_topics")
        con.commit(); con.close()
        available = TOPIC_QUEUE[:]
    return random.choice(available)

def db_start_run(topic, pillar, hook, folder):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO runs (started_at, topic, pillar, hook, folder) VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(), topic, pillar, hook, folder)
    )
    run_id = cur.lastrowid
    for platform in cfg.POST_PLATFORMS:
        cur.execute("INSERT INTO posts (run_id, platform) VALUES (?,?)", (run_id, platform))
    con.commit(); con.close()
    return run_id

def db_update_post(run_id, platform, status, post_id=None, error=None):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """UPDATE posts SET status=?, posted_at=?, post_id=?, error=?,
           attempts=attempts+1 WHERE run_id=? AND platform=?""",
        (status, datetime.now().isoformat(), post_id, error, run_id, platform)
    )
    con.commit(); con.close()

def db_finish_run(run_id, status, error=None):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE runs SET finished_at=?, status=?, error=? WHERE id=?",
        (datetime.now().isoformat(), status, error, run_id)
    )
    con.commit(); con.close()

def run_pipeline(topic_override=None, pillar_override=None):
    log.info("\n" + "="*50)
    log.info(f"  BOSSMOM PIPELINE START  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("="*50)

    if topic_override:
        topic_data = {"pillar": pillar_override or "peace", "topic": topic_override}
    else:
        topic_data = pick_next_topic()

    topic  = topic_data["topic"]
    pillar = topic_data["pillar"]
    log.info(f"  Topic: [{pillar}] {topic}")

    log.info("Phase 1: Generating copy...")
    slides = generate_copy(topic_data)
    if not slides or len(slides) != 6:
        raise RuntimeError(f"Copy generation returned {len(slides)} slides — expected 6.")

    hook = slides[0].get("headline", "")[:80]
    log.info(f"  Hook: {hook}")

    log.info("Phase 2: Rendering slides...")
    import re
    slug   = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:40]
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = OUTPUT_DIR / f"{ts}_{slug}"
    folder.mkdir(parents=True, exist_ok=True)

    slide_paths = []
    for i, slide_data in enumerate(slides, start=1):
        img  = render_slide(slide_data, slide_num=i, total=len(slides))
        path = folder / f"slide_{i:02d}.jpg"
        img.save(path, "JPEG", quality=95)
        slide_paths.append(path)
    (folder / "copy.json").write_text(json.dumps(slides, indent=2))
    log.info(f"  Saved {len(slide_paths)} slides → {folder}")

    if not topic_override:
        mark_topic_used(topic)

    run_id = db_start_run(topic, pillar, hook, str(folder))

    log.info("Phase 3: Posting to platforms...")
    body     = slides[4].get("body", []) if len(slides) > 4 else []
    points   = "\n".join(body[:3])
    hashtags = (
        "#SingleMom #SingleMother #MomLife #SingleMomMotivation #WealthyMom "
        "#SingleMomBoss #FinancialFreedom #MomEntrepreneur #SingleMomLife #BossMom"
    )
    caption = f"{hook}\n\n{points}\n\nThe full guide is in our bio.\nFollow @bossmomcode28 — for the money and the peace.\n\n{hashtags}"

    results = post_to_all_platforms(slide_paths, caption, cfg, platforms=cfg.POST_PLATFORMS)

    all_ok = True
    for platform, result in results.items():
        if result.get("success"):
            post_id = (result.get("id") or result.get("publish_id") or result.get("video_id") or "")
            db_update_post(run_id, platform, "posted", post_id=str(post_id))
            log.info(f"  ✓ {platform}")
            try:
                from sheets_logger import log_post
                log_post(account="@bossmomcode28", niche="Single Mom Empowerment", topic=topic,
                         hook=hook, pillar=pillar, platform=platform,
                         status="posted", post_id=str(post_id))
            except Exception as _e:
                log.warning(f"Sheets log failed: {_e}")
        else:
            db_update_post(run_id, platform, "failed", error=result.get("error", ""))
            log.error(f"  ✗ {platform}: {result.get('error')}")
            try:
                from sheets_logger import log_post
                log_post(account="@bossmomcode28", niche="Single Mom Empowerment", topic=topic,
                         hook=hook, pillar=pillar, platform=platform,
                         status="failed", error=result.get("error", ""))
            except Exception as _e:
                log.warning(f"Sheets log failed: {_e}")
            all_ok = False

    final_status = "success" if all_ok else "partial"
    db_finish_run(run_id, final_status)
    log.info(f"\n  RUN COMPLETE — status={final_status} run_id={run_id}")
    log.info("="*50 + "\n")
    return {"run_id": run_id, "status": final_status, "results": results}

def safe_pipeline(**kwargs):
    try:
        run_pipeline(**kwargs)
    except Exception as e:
        log.error(f"Pipeline error: {e}", exc_info=True)

def start_scheduler():
    init_db()
    scheduler = BlockingScheduler(timezone=cfg.TIMEZONE)
    for time_str in cfg.POSTING_TIMES:
        hour, minute = map(int, time_str.split(":"))
        scheduler.add_job(
            safe_pipeline,
            CronTrigger(hour=hour, minute=minute, timezone=cfg.TIMEZONE),
            id=f"bossmom_post_{time_str}",
            name=f"@bossmomcode28 post at {time_str}",
            max_instances=1,
            misfire_grace_time=300,
        )
        log.info(f"  Scheduled: {time_str} {cfg.TIMEZONE}")

    log.info(f"\n  BossMom Scheduler started — {len(cfg.POSTING_TIMES)} daily posts")
    log.info(f"  Platforms: {', '.join(cfg.POST_PLATFORMS)}")
    log.info(f"  Times: {', '.join(cfg.POSTING_TIMES)} ({cfg.TIMEZONE})")
    log.info("  Press Ctrl+C to stop.\n")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler stopped.")

if __name__ == "__main__":
    os.environ.setdefault("ANTHROPIC_API_KEY", cfg.ANTHROPIC_API_KEY)
    parser = argparse.ArgumentParser(description="@bossmomcode28 scheduler")
    parser.add_argument("--run-now", action="store_true")
    parser.add_argument("--status",  action="store_true")
    parser.add_argument("--topic",   type=str)
    parser.add_argument("--pillar",  type=str, default="peace")
    args = parser.parse_args()

    init_db()
    if args.run_now:
        run_pipeline(topic_override=args.topic, pillar_override=args.pillar)
    else:
        start_scheduler()
