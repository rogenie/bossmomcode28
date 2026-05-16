"""
@pixielandmedia — Platform Poster
Handles image hosting and posting to all 4 platforms.

Posting flow:
  Instagram  → upload each slide to R2/S3 → create IG media containers
               → create carousel container → publish
  Facebook   → upload each slide to R2/S3 → post_images + create post
  TikTok     → stitch slides into .mp4 with ffmpeg → upload via Content Posting API
  YouTube    → stitch slides into .mp4 with ffmpeg → upload as Short

Requirements:
    pip install requests boto3 google-auth google-auth-httplib2 google-api-python-client
    brew install ffmpeg   (or apt install ffmpeg)
"""

import os
import io
import time
import json
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("poster")


# ─────────────────────────────────────────────
#  IMAGE HOSTING  (Meta API needs public URLs)
# ─────────────────────────────────────────────

def upload_to_r2(local_path: Path, cfg) -> str:
    """Upload image to Cloudflare R2, return public URL."""
    import boto3
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{cfg.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=cfg.R2_ACCESS_KEY,
        aws_secret_access_key=cfg.R2_SECRET_KEY,
    )
    key = f"slides/{local_path.parent.name}/{local_path.name}"
    s3.upload_file(
        str(local_path), cfg.R2_BUCKET_NAME, key,
        ExtraArgs={"ContentType": "image/jpeg"}
    )
    return f"{cfg.R2_PUBLIC_URL}/{key}"


def upload_to_s3(local_path: Path, cfg) -> str:
    """Upload image to AWS S3, return public URL."""
    import boto3
    s3 = boto3.client(
        "s3",
        aws_access_key_id=cfg.S3_ACCESS_KEY,
        aws_secret_access_key=cfg.S3_SECRET_KEY,
        region_name=cfg.S3_REGION,
    )
    key = f"slides/{local_path.parent.name}/{local_path.name}"
    s3.upload_file(
        str(local_path), cfg.S3_BUCKET_NAME, key,
        ExtraArgs={"ACL": "public-read", "ContentType": "image/jpeg"}
    )
    return f"{cfg.S3_PUBLIC_URL}/{key}"


def host_images(slide_paths: list[Path], cfg) -> list[str]:
    """Upload all slides and return list of public URLs."""
    urls = []
    for path in slide_paths:
        try:
            url = upload_to_r2(path, cfg)
        except Exception:
            url = upload_to_s3(path, cfg)  # fallback to S3
        urls.append(url)
        log.info(f"  Hosted: {url}")
    return urls


# ─────────────────────────────────────────────
#  VIDEO STITCHING  (TikTok + YouTube need mp4)
# ─────────────────────────────────────────────

def stitch_slides_to_video(slide_paths: list[Path], output_path: Path, cfg) -> Path:
    """
    Uses ffmpeg to stitch JPEG slides into an mp4 video.
    Each slide is shown for VIDEO_FPS seconds with a cross-fade transition.
    Output is 1080x1920 (vertical) at 30fps.
    """
    fps         = getattr(cfg, "VIDEO_FPS", 3)
    fade_ms     = getattr(cfg, "VIDEO_FADE_MS", 300)
    fade_s      = fade_ms / 1000

    # Write concat demuxer file
    concat_lines = []
    for path in slide_paths:
        concat_lines.append(f"file '{path.resolve()}'")
        concat_lines.append(f"duration {fps}")
    # Repeat last slide so ffmpeg doesn't drop it
    concat_lines.append(f"file '{slide_paths[-1].resolve()}'")
    concat_lines.append(f"duration {fps}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                    delete=False) as f:
        f.write("\n".join(concat_lines))
        concat_path = f.name

    cmd = [
        cfg.FFMPEG_PATH, "-y",
        "-f", "concat", "-safe", "0", "-i", concat_path,
        "-vf", (
            f"scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps=30"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",                     # no audio
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")

    os.unlink(concat_path)
    log.info(f"  Video: {output_path} ({output_path.stat().st_size // 1024}KB)")
    return output_path


# ─────────────────────────────────────────────
#  INSTAGRAM  (Meta Graph API — Carousel)
# ─────────────────────────────────────────────

def post_instagram(slide_paths: list[Path], caption: str, cfg) -> dict:
    """
    Posts a carousel to Instagram via Meta Graph API.
    Steps: host images → create item containers → create carousel → publish
    """
    base = f"https://graph.facebook.com/{cfg.META_API_VERSION}"
    token = cfg.META_ACCESS_TOKEN
    uid   = cfg.INSTAGRAM_USER_ID

    log.info("Instagram: hosting images...")
    urls = host_images(slide_paths[:10], cfg)  # IG max 10 slides

    log.info("Instagram: creating media containers...")
    item_ids = []
    for url in urls:
        r = requests.post(
            f"{base}/{uid}/media",
            data={
                "image_url":       url,
                "is_carousel_item": "true",   # FIX: must be lowercase string not bool
                "access_token":    token,
            },
            timeout=30,
        )
        if not r.ok:
            log.error(f"Instagram media container failed {r.status_code}: {r.text}")
        r.raise_for_status()
        item_ids.append(r.json()["id"])
        time.sleep(1)

    log.info("Instagram: creating carousel container...")
    r = requests.post(
        f"{base}/{uid}/media",
        data={
            "media_type":   "CAROUSEL",
            "children":     ",".join(item_ids),
            "caption":      caption,
            "access_token": token,
        },
        timeout=30,
    )
    if not r.ok:
        log.error(f"Instagram carousel container failed {r.status_code}: {r.text}")
    r.raise_for_status()
    carousel_id = r.json()["id"]

    # Wait for IG to process
    time.sleep(5)

    log.info("Instagram: publishing...")
    r = requests.post(
        f"{base}/{uid}/media_publish",
        data={"creation_id": carousel_id, "access_token": token},
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()
    log.info(f"Instagram: posted ✓ id={result.get('id')}")
    return result


# ─────────────────────────────────────────────
#  FACEBOOK  (Meta Graph API — Multi-photo post)
# ─────────────────────────────────────────────

def post_facebook(slide_paths: list[Path], caption: str, cfg) -> dict:
    """Posts a multi-image post to a Facebook Page."""
    base  = f"https://graph.facebook.com/{cfg.META_API_VERSION}"
    token = cfg.META_ACCESS_TOKEN
    pid   = cfg.FACEBOOK_PAGE_ID

    log.info("Facebook: hosting images...")
    urls = host_images(slide_paths[:10], cfg)

    log.info("Facebook: uploading photos (unpublished)...")
    photo_ids = []
    for url in urls:
        r = requests.post(
            f"{base}/{pid}/photos",
            data={
                "url":          url,
                "published":    False,
                "access_token": token,
            },
            timeout=30,
        )
        r.raise_for_status()
        photo_ids.append({"media_fbid": r.json()["id"]})
        time.sleep(0.5)

    log.info("Facebook: creating feed post...")
    r = requests.post(
        f"{base}/{pid}/feed",
        data={
            "message":         caption,
            "attached_media":  json.dumps(photo_ids),
            "access_token":    token,
        },
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()
    log.info(f"Facebook: posted ✓ id={result.get('id')}")
    return result


# ─────────────────────────────────────────────
#  TIKTOK  (Content Posting API — Video upload)
# ─────────────────────────────────────────────

TIKTOK_INIT_URL    = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_STATUS_URL  = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

def post_tiktok(slide_paths: list[Path], caption: str, cfg) -> dict:
    """
    Posts slides as a video to TikTok via the Content Posting API.
    Slides are stitched into an mp4 first using ffmpeg.
    """
    token = cfg.TIKTOK_ACCESS_TOKEN

    # Stitch into video
    video_path = slide_paths[0].parent / "tiktok_video.mp4"
    log.info("TikTok: stitching video...")
    stitch_slides_to_video(slide_paths, video_path, cfg)

    video_size = video_path.stat().st_size

    # Step 1: Initialise upload
    log.info("TikTok: initialising upload...")
    r = requests.post(
        TIKTOK_INIT_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json; charset=UTF-8",
        },
        json={
            "post_info": {
                "title":          caption[:2200],
                "privacy_level":  "PUBLIC_TO_EVERYONE",
                "disable_duet":   False,
                "disable_stitch": False,
                "disable_comment":False,
            },
            "source_info": {
                "source":     "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": video_size,   # single chunk
                "total_chunk_count": 1,
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    data       = r.json()["data"]
    publish_id = data["publish_id"]
    upload_url = data["upload_url"]

    # Step 2: Upload video bytes
    log.info(f"TikTok: uploading {video_size // 1024}KB...")
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    r = requests.put(
        upload_url,
        headers={
            "Content-Range": f"bytes 0-{video_size-1}/{video_size}",
            "Content-Type":  "video/mp4",
        },
        data=video_bytes,
        timeout=120,
    )
    r.raise_for_status()

    # Step 3: Poll status until published
    log.info("TikTok: waiting for processing...")
    for _ in range(20):
        time.sleep(10)
        r = requests.post(
            TIKTOK_STATUS_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
            timeout=15,
        )
        status = r.json().get("data", {}).get("status", "")
        log.info(f"  TikTok status: {status}")
        if status == "PUBLISH_COMPLETE":
            break
        if status in ("FAILED", "SPAM_RISK_CREATOR_BANNED"):
            raise RuntimeError(f"TikTok publish failed: {status}")

    log.info(f"TikTok: posted ✓ publish_id={publish_id}")
    return {"publish_id": publish_id, "status": status}


# ─────────────────────────────────────────────
#  YOUTUBE  (Data API v3 — Shorts upload)
# ─────────────────────────────────────────────

def _get_youtube_service(cfg):
    """Returns an authenticated YouTube API service object."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=cfg.YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg.YOUTUBE_CLIENT_ID,
        client_secret=cfg.YOUTUBE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds)


def post_youtube(slide_paths: list[Path], caption: str, cfg) -> dict:
    """
    Uploads slides as a YouTube Short (vertical video).
    Adds #Shorts to the description so YouTube treats it as a Short.
    """
    from googleapiclient.http import MediaFileUpload

    # Stitch into video
    video_path = slide_paths[0].parent / "youtube_short.mp4"
    log.info("YouTube: stitching video...")
    stitch_slides_to_video(slide_paths, video_path, cfg)

    log.info("YouTube: uploading...")
    youtube = _get_youtube_service(cfg)

    body = {
        "snippet": {
            "title":       caption[:100],
            "description": f"{caption}\n\n#Shorts #AI #ArtificialIntelligence #AIEducation #TechTips",
            "tags":        ["AI", "artificial intelligence", "ChatGPT", "tech", "Shorts"],
            "categoryId":  "28",  # Science & Technology
        },
        "status": {
            "privacyStatus":         "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                            resumable=True, chunksize=10 * 1024 * 1024)
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info(f"  YouTube upload: {int(status.progress() * 100)}%")

    vid_id = response.get("id")
    log.info(f"YouTube: posted ✓ https://youtube.com/shorts/{vid_id}")
    return {"video_id": vid_id}


# ─────────────────────────────────────────────
#  MASTER POSTER
# ─────────────────────────────────────────────

def post_to_all_platforms(
    slide_paths: list[Path],
    caption: str,
    cfg,
    platforms: Optional[list[str]] = None,
) -> dict[str, dict]:
    """
    Posts to all enabled platforms. Returns results dict per platform.
    Failures on one platform don't abort the others.
    """
    if platforms is None:
        platforms = getattr(cfg, "POST_PLATFORMS",
                            ["instagram", "facebook", "tiktok", "youtube"])

    handlers = {
        "instagram": post_instagram,
        "facebook":  post_facebook,
        "tiktok":    post_tiktok,
        "youtube":   post_youtube,
    }

    results = {}
    for platform in platforms:
        handler = handlers.get(platform)
        if not handler:
            log.warning(f"Unknown platform: {platform}")
            continue
        try:
            log.info(f"\n── Posting to {platform.upper()} ──")
            results[platform] = handler(slide_paths, caption, cfg)
            results[platform]["success"] = True
        except Exception as e:
            log.error(f"{platform} failed: {e}")
            results[platform] = {"success": False, "error": str(e)}

    return results


# ─────────────────────────────────────────────
#  CAPTION BUILDER
# ─────────────────────────────────────────────

def build_caption(slides: list[dict], handle: str = "@pixielandmedia") -> str:
    """
    Builds the post caption from slide copy.
    Hook + 3 bullet points + CTA hashtags.
    """
    hook     = slides[0].get("headline", "")
    how_body = slides[3].get("body", []) if len(slides) > 3 else []
    points   = "\n".join(how_body[:3])
    hashtags = (
        "#AI #ArtificialIntelligence #ChatGPT #AITools #TechTips "
        "#FutureOfWork #AIEducation #LearnAI #DigitalSkills #AIRevolution"
    )
    return f"{hook}\n\n{points}\n\nFollow {handle} for daily AI insights.\n\n{hashtags}"
