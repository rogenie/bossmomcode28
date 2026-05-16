"""
@bossmomcode28 — Slide Generator
6-slide empowerment carousels for wealthy single moms.
Ivory + sage green + champagne gold theme. Old money elegant.
Structure: Hook → The Truth → The Mindset Shift → The Money Move → Action Step → CTA

Requirements:
    pip install pillow anthropic numpy
"""

import os
import re
import json
import random
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime

try:
    import config as _cfg
    if _cfg.ANTHROPIC_API_KEY and not _cfg.ANTHROPIC_API_KEY.startswith("sk-ant-..."):
        os.environ["ANTHROPIC_API_KEY"] = _cfg.ANTHROPIC_API_KEY
except Exception:
    pass

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("pip install pillow numpy")

try:
    import anthropic
except ImportError:
    raise SystemExit("pip install anthropic")

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
ACCOUNT_HANDLE   = "@bossmomcode28"
SLIDE_W, SLIDE_H = 1080, 1350
OUTPUT_DIR       = Path("slides_output")
CX               = SLIDE_W // 2

# Palette — ivory + sage green + champagne gold
IVORY        = "#FAF7F0"
IVORY_BG     = "#F5F0E4"
SAGE         = "#7A9E7E"
SAGE_DIM     = "#4A6B4E"
SAGE_LIGHT   = "#B8D4BA"
CHAMPAGNE    = "#C9A84C"
CHAMPAGNE_DIM= "#8B6914"
WARM_BROWN   = "#5C4033"
CREAM_TEXT   = "#3D3228"

SERIF_BOLD = [
    "/Library/Fonts/Georgia Bold.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/app/fonts/DejaVuSerif-Bold.ttf",
]
SERIF_REG = [
    "/Library/Fonts/Georgia.ttf",
    "C:/Windows/Fonts/georgia.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/app/fonts/DejaVuSerif.ttf",
]

FONT_DIR = Path("/app/fonts")

def ensure_fonts():
    found = [p for p in SERIF_BOLD + SERIF_REG if Path(p).exists()]
    if found:
        print(f"  Using font: {found[0]}")
        return
    print("  No system fonts — attempting install...")
    import subprocess
    try:
        subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=60)
        subprocess.run(
            ["apt-get", "install", "-y", "--no-install-recommends",
             "fonts-dejavu-core", "fontconfig"],
            capture_output=True, timeout=120
        )
        subprocess.run(["fc-cache", "-fv"], capture_output=True, timeout=30)
        found = [p for p in SERIF_BOLD + SERIF_REG if Path(p).exists()]
        if found:
            print(f"  Fonts installed: {found[0]}")
            return
    except Exception as e:
        print(f"  apt-get failed: {e}")
    try:
        import urllib.request
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        base = "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/master/fonts"
        urllib.request.urlretrieve(f"{base}/DejaVuSerif.ttf", str(FONT_DIR / "DejaVuSerif.ttf"))
        urllib.request.urlretrieve(f"{base}/DejaVuSerif-Bold.ttf", str(FONT_DIR / "DejaVuSerif-Bold.ttf"))
        print("  Downloaded DejaVu fonts.")
    except Exception as e:
        print(f"  Font download failed: {e}")

# ─────────────────────────────────────────────
#  TOPIC QUEUE
# ─────────────────────────────────────────────
TOPIC_QUEUE = [
    # Peace & independence
    {"pillar": "peace",   "topic": "You don't need child support. You need peace."},
    {"pillar": "peace",   "topic": "Why leaving is the most financially intelligent decision you can make"},
    {"pillar": "peace",   "topic": "What co-parenting with a difficult ex is actually costing your mental health"},
    {"pillar": "peace",   "topic": "How to stop waiting for him to step up and start stepping up yourself"},
    {"pillar": "peace",   "topic": "The moment you stop depending on a man your life changes"},
    {"pillar": "peace",   "topic": "Why single moms who chose peace are winning quietly"},
    # Money & wealth
    {"pillar": "money",   "topic": "How to build a 6 figure income as a single mom from scratch"},
    {"pillar": "money",   "topic": "The money moves every single mom needs to make before age 40"},
    {"pillar": "money",   "topic": "How to buy a house as a single mom with one income"},
    {"pillar": "money",   "topic": "Building generational wealth for your children without a partner"},
    {"pillar": "money",   "topic": "The financial accounts every single mom needs open right now"},
    {"pillar": "money",   "topic": "How to negotiate a salary that actually supports your family"},
    # Business & income
    {"pillar": "business","topic": "How to start a business while raising kids alone"},
    {"pillar": "business","topic": "The best businesses for single moms that work around school schedules"},
    {"pillar": "business","topic": "How to turn your skills into income streams that work while you sleep"},
    {"pillar": "business","topic": "Why your story as a single mom is your greatest business asset"},
    {"pillar": "business","topic": "How to hire help before you think you can afford it"},
    # Mindset & power
    {"pillar": "mindset", "topic": "Why you are not a struggling single mom. You are a CEO of your home."},
    {"pillar": "mindset", "topic": "The identity shift that changes everything for single moms"},
    {"pillar": "mindset", "topic": "How to stop apologizing for choosing yourself and your children"},
    {"pillar": "mindset", "topic": "What old money single moms understand that others don't"},
    {"pillar": "mindset", "topic": "Why your children watching you build is the best thing you can give them"},
    # Lifestyle & boundaries
    {"pillar": "lifestyle","topic": "How to create a life so good he becomes irrelevant"},
    {"pillar": "lifestyle","topic": "The boundaries that protect your peace and your coins"},
    {"pillar": "lifestyle","topic": "How to date again without losing yourself or your standards"},
]

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def load_font(candidates, size):
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def add_grain(img, intensity=8):
    arr   = np.array(img).astype(np.int16)
    noise = np.random.randint(-intensity, intensity, arr.shape, dtype=np.int16)
    arr   = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)

def wrap(text, font, max_w):
    words, lines, cur = text.split(), [], []
    for w in words:
        test = " ".join(cur + [w])
        if font.getbbox(test)[2] > max_w and cur:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(" ".join(cur))
    return lines

def text_height(lines, font, line_gap=12):
    if not lines: return 0
    return len(lines) * font.size + (len(lines) - 1) * line_gap

def draw_centered(draw, lines, font, color, start_y, line_gap=12):
    y = start_y
    for line in lines:
        draw.text((CX, y), line, font=font, fill=color, anchor="mt")
        y += font.size + line_gap
    return y

def rule(draw, y, color=None):
    color = color or hex_rgb(CHAMPAGNE_DIM)
    draw.line([(100, y), (SLIDE_W - 100, y)], fill=color, width=1)

def sage_bar(draw, y):
    draw.rectangle([(80, y), (86, y + 36)], fill=hex_rgb(SAGE))

# ─────────────────────────────────────────────
#  SLIDE LABELS & COLORS
# ─────────────────────────────────────────────
SLIDE_LABELS = {
    "hook":    "",
    "truth":   "THE TRUTH",
    "shift":   "THE SHIFT",
    "money":   "THE MONEY MOVE",
    "action":  "YOUR NEXT STEP",
    "cta":     "",
}

SLIDE_HL_COLORS = {
    "hook":   hex_rgb(WARM_BROWN),
    "truth":  hex_rgb(WARM_BROWN),
    "shift":  hex_rgb(SAGE_DIM),
    "money":  hex_rgb(CHAMPAGNE_DIM),
    "action": hex_rgb(WARM_BROWN),
    "cta":    hex_rgb(CHAMPAGNE),
}

# ─────────────────────────────────────────────
#  RENDERER
# ─────────────────────────────────────────────
def render_slide(slide_data, slide_num, total=6):
    ensure_fonts()
    img  = Image.new("RGB", (SLIDE_W, SLIDE_H), hex_rgb(IVORY_BG))
    draw = ImageDraw.Draw(img)
    max_w = SLIDE_W - 160

    fEB  = load_font(SERIF_REG,  30)
    fHL  = load_font(SERIF_BOLD, 76)
    fHLS = load_font(SERIF_BOLD, 58)
    fBOD = load_font(SERIF_REG,  40)
    fWM  = load_font(SERIF_REG,  28)
    fCNT = load_font(SERIF_REG,  28)
    fCTA = load_font(SERIF_BOLD, 56)

    brown    = hex_rgb(WARM_BROWN)
    sage     = hex_rgb(SAGE)
    sagedim  = hex_rgb(SAGE_DIM)
    champ    = hex_rgb(CHAMPAGNE)
    champdim = hex_rgb(CHAMPAGNE_DIM)

    stype    = slide_data.get("type", "truth")
    hl_color = SLIDE_HL_COLORS.get(stype, brown)

    # Champagne top border
    draw.rectangle([(0, 0), (SLIDE_W, 5)], fill=hex_rgb(CHAMPAGNE))

    # Subtle sage left accent bar
    draw.rectangle([(0, 0), (8, SLIDE_H)], fill=hex_rgb(SAGE_LIGHT))

    # Top bar
    draw.text((90, 62), f"{slide_num:02d} / {total:02d}", font=fCNT, fill=hex_rgb(CHAMPAGNE_DIM))
    wm_w = fWM.getbbox(ACCOUNT_HANDLE)[2]
    draw.text((SLIDE_W - 80 - wm_w, 62), ACCOUNT_HANDLE, font=fWM, fill=hex_rgb(SAGE_DIM))

    rule(draw, 148)

    # Slide label
    label = SLIDE_LABELS.get(stype, "")
    if label:
        sage_bar(draw, 165)
        draw.text((100, 168), label, font=fEB, fill=sage)

    # Content
    eyebrow  = (slide_data.get("eyebrow") or "").upper()
    headline = slide_data.get("headline", "")
    body     = slide_data.get("body", [])

    eyebrow_lines = wrap(eyebrow, fEB, max_w) if eyebrow else []

    if stype == "cta":
        hl_lines = []
        for line in headline.split("\n"):
            hl_lines += wrap(line, fCTA, max_w)
        hl_font = fCTA
    else:
        hl_font  = fHL if len(headline) <= 38 else fHLS
        hl_lines = wrap(headline, hl_font, max_w)

    body_wrapped = []
    for para in body:
        body_wrapped += wrap(para, fBOD, max_w)

    GAP    = 22
    RULE_H = 20
    content_h = 0
    if eyebrow_lines:
        content_h += text_height(eyebrow_lines, fEB) + GAP
    content_h += RULE_H + GAP
    content_h += text_height(hl_lines, hl_font, 18) + GAP
    content_h += RULE_H + GAP
    content_h += text_height(body_wrapped, fBOD, 16)

    usable_top    = 220
    usable_bottom = SLIDE_H - 140
    usable_h      = usable_bottom - usable_top
    y = usable_top + (usable_h - content_h) // 2
    y = max(y, usable_top)

    if eyebrow_lines:
        y = draw_centered(draw, eyebrow_lines, fEB, champdim, y, 8)
        y += GAP

    rule(draw, y); y += RULE_H + GAP
    y = draw_centered(draw, hl_lines, hl_font, hl_color, y, 18)
    y += GAP
    rule(draw, y); y += RULE_H + GAP

    body_color = sagedim if stype == "shift" else champdim if stype == "money" else brown
    draw_centered(draw, body_wrapped, fBOD, body_color, y, 16)

    # Champagne bottom border
    draw.rectangle([(0, SLIDE_H - 5), (SLIDE_W, SLIDE_H)], fill=hex_rgb(CHAMPAGNE))

    img = add_grain(img, intensity=8)
    return img

# ─────────────────────────────────────────────
#  COPY GENERATOR
# ─────────────────────────────────────────────
SYSTEM = f"""
You are the voice of {ACCOUNT_HANDLE} — the most elegant, no-nonsense empowerment account for single moms who are done settling.
Audience: Single mothers aged 28-45. Some are recently single, some have been doing it alone for years. All of them are tired, capable, and ready to WIN. They want both financial freedom AND emotional peace.
Tone: Like a wealthy older sister who has been through it, built her empire, and now wants to pull you up. Warm but direct. Elegant but real. Never preachy. Never victim-language. Always powerful.
This account does not bash men. It elevates women. The focus is always on HER power, HER money, HER peace.
No emojis — old money does not need them.
Forbidden: "toxic", "narcissist", "girl boss" (cringe), "boss babe", "queen" (overused), victimhood language

SLIDE STRUCTURE:
Slide 1 (HOOK)   → One sharp line that names exactly what she is feeling but hasn't said out loud. Should stop her mid-scroll. Elegant but cuts deep.
Slide 2 (TRUTH)  → The real truth she needs to hear. Not sugar-coated. Not mean. Just honest and freeing.
Slide 3 (SHIFT)  → The mindset shift that changes everything. The reframe. What wealthy, peaceful single moms think differently.
Slide 4 (MONEY)  → The specific money move that creates independence. Real. Actionable. With numbers where possible.
Slide 5 (ACTION) → Three specific steps she can take this week. Practical. Doable. No vague advice.
Slide 6 (CTA)    → Warm, elegant close. She deserves this. The full guide is in the link in bio. Follow for more.

WRITING RULES:
- headline: elegant and direct, max 12 words, sounds like something a wealthy woman would say
- body: 2-4 short lines, each line can stand alone, never fluffy
- eyebrow: short refined label or leave empty
- no emojis at all
- write like you respect her intelligence and her time

Return ONLY a valid JSON array of 6 slides. No markdown fences.
[
  {{"type":"hook","eyebrow":"","headline":"you don't need child support. you need peace.","body":["and peace, it turns out, is something you build yourself."]}},
  {{"type":"truth","eyebrow":"the truth","headline":"depending on someone who let you down is still depending","body":["every month you wait for his check is a month you delayed your freedom.","your income is the only income you can control."]}},
  {{"type":"shift","eyebrow":"the shift","headline":"wealthy single moms stopped counting on others early","body":["they built income streams. they automated savings.","they made themselves untouchable financially.","that is the goal."]}},
  {{"type":"money","eyebrow":"the money move","headline":"one income can absolutely build wealth","body":["specific financial action with numbers","what it looks like in 12 months","the account or tool to use"]}},
  {{"type":"action","eyebrow":"this week","headline":"three things to do before Sunday","body":["specific action one","specific action two","specific action three"]}},
  {{"type":"cta","eyebrow":"you are closer than you think","headline":"the life you are building\\nis already more than\\nthey expected of you.","body":["the full financial playbook for single moms is in our bio.","follow {ACCOUNT_HANDLE} — for the money and the peace."]}}
]
"""

def generate_copy(topic_data):
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    pillar = topic_data.get("pillar", "peace")
    topic  = topic_data.get("topic", "")
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1200,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Pillar: {pillar}\nTopic: {topic}"}],
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    slides = json.loads(raw)
    if len(slides) != 6:
        raise ValueError(f"Expected 6 slides, got {len(slides)}")
    return slides

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def generate_carousel(topic_data):
    topic = topic_data.get("topic", "")
    print(f"\n  Topic: {topic}")
    slug   = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:50]
    folder = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}"
    folder.mkdir(parents=True, exist_ok=True)

    print("  Writing copy...")
    slides = generate_copy(topic_data)

    print("  Rendering slides...")
    for i, s in enumerate(slides, 1):
        img = render_slide(s, i, len(slides))
        img.save(folder / f"slide_{i:02d}.jpg", "JPEG", quality=95)
        print(f"    slide_{i:02d}.jpg done")

    (folder / "copy.json").write_text(json.dumps(slides, indent=2))
    print(f"\n  Done → {folder.resolve()}\n")
    return folder

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic",  type=str)
    parser.add_argument("--pillar", type=str, default="peace")
    parser.add_argument("--batch",  action="store_true")
    parser.add_argument("--list",   action="store_true")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY first.")

    if args.list:
        for i, t in enumerate(TOPIC_QUEUE, 1):
            print(f"  {i:02d}. [{t['pillar']:10s}] {t['topic']}")
    elif args.batch:
        for t in TOPIC_QUEUE:
            try: generate_carousel(t)
            except Exception as e: print(f"  Error: {e}")
    elif args.topic:
        generate_carousel({"pillar": args.pillar, "topic": args.topic})
    else:
        generate_carousel(random.choice(TOPIC_QUEUE))
