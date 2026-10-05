import os
import sys
import glob
import json
import time
import asyncio
import subprocess
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TARGET_URL = os.getenv("TARGET_URL", "https://news.ycombinator.com")
INSTRUCTIONS = os.getenv("INSTRUCTIONS", "Capture screenshot")
TASK_TYPE = os.getenv("TASK_TYPE", "browser")
COMPOSIO_KEY = os.getenv("COMPOSIO_API_KEY", "")
EXTRA_PARAMS_RAW = os.getenv("EXTRA_PARAMS", "{}")

try:
    EXTRA_PARAMS = json.loads(EXTRA_PARAMS_RAW) if EXTRA_PARAMS_RAW else {}
except Exception:
    EXTRA_PARAMS = {}

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM DISPATCH UTILITIES (Split text, send photo, document, video, audio)
# ─────────────────────────────────────────────────────────────────────────────
def notify_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print(text)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # Split text into chunks <= 4000 characters
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i + max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def send_file_telegram(file_path, caption="", file_type="photo"):
    if not BOT_TOKEN or not CHAT_ID or not os.path.exists(file_path):
        return
    endpoints = {
        "photo": "sendPhoto",
        "video": "sendVideo",
        "audio": "sendAudio",
        "document": "sendDocument"
    }
    fields = {
        "photo": "photo",
        "video": "video",
        "audio": "audio",
        "document": "document"
    }
    ep = endpoints.get(file_type, "sendDocument")
    field = fields.get(file_type, "document")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{ep}"
    
    # Trim caption to 1024 chars max (Telegram API constraint)
    clean_caption = caption[:1000] if caption else ""
    try:
        with open(file_path, "rb") as f:
            requests.post(url, data={"chat_id": CHAT_ID, "caption": clean_caption}, files={field: f}, timeout=120)
    except Exception as e:
        print(f"Telegram upload error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# POWER 1: BROWSER AUTOMATION & WEB RESEARCH (Playwright + Chromium)
# ─────────────────────────────────────────────────────────────────────────────
async def run_browser_task():
    from playwright.async_api import async_playwright
    notify_telegram(f"🌐 Cloud Browser Active (Headless Chromium)\nURL: {TARGET_URL}\nTask: {INSTRUCTIONS}")
    screenshot_path = "page_screenshot.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        try:
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=45000)
        except Exception:
            try:
                await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                notify_telegram(f"❌ Failed to reach URL: {e}")
                await browser.close()
                return

        title = await page.title()
        await asyncio.sleep(2)

        # Full page screenshot
        await page.screenshot(path=screenshot_path, full_page=True)

        # Extract textual headings and paragraphs
        body_text = await page.inner_text("body")
        lines = [l.strip() for l in body_text.split("\n") if len(l.strip()) > 35]
        extracted_summary = "\n".join(lines[:6]) if lines else "No text extracted."

        await browser.close()

    send_file_telegram(screenshot_path, caption=f"📸 Page: {title}\nURL: {TARGET_URL}", file_type="photo")
    notify_telegram(f"📝 Extracted Content:\n{extracted_summary}\n\n✅ Browser automation finished successfully!")

# ─────────────────────────────────────────────────────────────────────────────
# POWER 2: YOUTUBE RESEARCH & TRANSCRIPTION (yt-dlp + ffmpeg)
# ─────────────────────────────────────────────────────────────────────────────
def run_youtube_task():
    notify_telegram(f"🎬 YouTube Research Engine Triggered\nURL: {TARGET_URL}\nTask: {INSTRUCTIONS}")
    
    # 1. Fetch metadata (Title, description, channel, duration)
    meta_cmd = ["yt-dlp", "--dump-json", "--no-playlist", TARGET_URL]
    res = subprocess.run(meta_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        notify_telegram(f"❌ yt-dlp error: {res.stderr[:400]}")
        return
        
    try:
        meta = json.loads(res.stdout)
        title = meta.get("title", "Unknown Title")
        uploader = meta.get("uploader", "Unknown Channel")
        duration = meta.get("duration", 0)
        view_count = meta.get("view_count", 0)
        notify_telegram(f"📺 Channel: {uploader}\n🎯 Title: {title}\n⏱️ Duration: {duration}s | Views: {view_count:,}")
    except Exception as e:
        notify_telegram(f"⚠️ Metadata parse warning: {e}")

    # 2. Download 60-second opening clip for visual frame extraction
    clip_file = "intro_60s.mp4"
    dl_cmd = [
        "yt-dlp",
        "--download-sections", "*0-60",
        "--format", "best[ext=mp4]/best",
        "-o", clip_file,
        "--force-overwrites",
        TARGET_URL
    ]
    subprocess.run(dl_cmd, capture_output=True)

    # 3. Extract 3 frames at 0:10, 0:30, 0:50 for visual proof
    if os.path.exists(clip_file):
        for sec in [10, 30, 50]:
            frame_path = f"frame_{sec}s.jpg"
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(sec), "-i", clip_file,
                "-vframes", "1", "-q:v", "2", frame_path
            ], capture_output=True)
            if os.path.exists(frame_path):
                send_file_telegram(frame_path, caption=f"Visual frame proof at 00:{sec:02d}", file_type="photo")
        
        # Send clip if small enough
        if os.path.getsize(clip_file) < 45 * 1024 * 1024:
            send_file_telegram(clip_file, caption=f"60s intro clip: {title}", file_type="video")

    # 4. Fetch Subtitles/Transcript
    sub_cmd = [
        "yt-dlp", "--write-auto-sub", "--sub-lang", "en", "--skip-download",
        "-o", "transcript.%(ext)s", TARGET_URL
    ]
    subprocess.run(sub_cmd, capture_output=True)
    
    # Check for vtt or srt
    vtt_files = glob.glob("transcript*.vtt") + glob.glob("transcript*.srt")
    if vtt_files:
        with open(vtt_files[0], "r", encoding="utf-8", errors="ignore") as f:
            sub_text = f.read()
        # Clean timestamps and tags
        clean_lines = [l for l in sub_text.split("\n") if "-->" not in l and not l.strip().isdigit() and len(l.strip()) > 10]
        preview_transcript = " ".join(clean_lines[:15])[:1500]
        notify_telegram(f"📜 Spoken Transcript Hook (0:00 - 1:00):\n\n\"{preview_transcript}\"")
        send_file_telegram(vtt_files[0], caption="Full raw transcript file", file_type="document")
    else:
        notify_telegram("ℹ️ No auto-captions available for this video.")

    notify_telegram("✅ YouTube research complete!")

# ─────────────────────────────────────────────────────────────────────────────
# POWER 3: ARBITRARY PYTHON RUNNER & CHART/FILE DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────
def run_python_task():
    code = EXTRA_PARAMS.get("code", INSTRUCTIONS)
    notify_telegram(f"🐍 Executing Python Script in Cloud Ubuntu Environment...")
    
    script_file = "user_script.py"
    with open(script_file, "w", encoding="utf-8") as f:
        f.write(code)

    start_time = time.time()
    res = subprocess.run([sys.executable, script_file], capture_output=True, text=True, timeout=300)
    elapsed = round(time.time() - start_time, 2)

    output = res.stdout.strip()
    errors = res.stderr.strip()

    if output:
        notify_telegram(f"📤 Output ({elapsed}s):\n{output[:3500]}")
    if errors:
        notify_telegram(f"⚠️ Stderr / Warning:\n{errors[:2000]}")
    if not output and not errors:
        notify_telegram(f"✅ Script executed with exit code 0 ({elapsed}s).")

    # Automatically detect and send any generated images, documents, or charts
    for ext, ft in [("*.png", "photo"), ("*.jpg", "photo"), ("*.pdf", "document"), ("*.csv", "document"), ("*.mp4", "video")]:
        for fpath in glob.glob(ext):
            if fpath not in ["page_screenshot.png", "frame_10s.jpg", "frame_30s.jpg", "frame_50s.jpg"]:
                send_file_telegram(fpath, caption=f"Generated artifact: {os.path.basename(fpath)}", file_type=ft)

# ─────────────────────────────────────────────────────────────────────────────
# POWER 4: ARBITRARY BASH / SYSTEM COMMAND EXECUTION
# ─────────────────────────────────────────────────────────────────────────────
def run_bash_task():
    cmd = EXTRA_PARAMS.get("command", INSTRUCTIONS)
    notify_telegram(f"💻 Running Bash Command:\n$ {cmd}")
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
    
    out = res.stdout.strip()
    err = res.stderr.strip()
    
    if out:
        notify_telegram(f"📤 Stdout:\n{out[:3500]}")
    if err:
        notify_telegram(f"⚠️ Stderr:\n{err[:2000]}")
    notify_telegram(f"Exit code: {res.returncode}")

# ─────────────────────────────────────────────────────────────────────────────
# POWER 5: COMPOSIO TOOL EXECUTION (Gmail, LinkedIn, etc.)
# ─────────────────────────────────────────────────────────────────────────────
def run_composio_task():
    if not COMPOSIO_KEY:
        notify_telegram("❌ COMPOSIO_API_KEY secret is missing in GitHub repository settings.")
        return

    action = EXTRA_PARAMS.get("action", "GMAIL_FETCH_EMAILS")
    inputs = EXTRA_PARAMS.get("inputs", {})
    account = EXTRA_PARAMS.get("account", None)

    notify_telegram(f"⚡ Executing Composio Action: {action}\nInputs: {json.dumps(inputs, indent=2)}")

    try:
        from composio import ComposioToolSet
        toolset = ComposioToolSet(api_key=COMPOSIO_KEY)
        
        exec_kwargs = {"action": action, "params": inputs}
        if account:
            exec_kwargs["entity_id"] = account
            
        result = toolset.execute_action(**exec_kwargs)
        result_str = json.dumps(result, indent=2)
        notify_telegram(f"✅ Composio Result:\n{result_str[:3500]}")
    except Exception as e:
        notify_telegram(f"❌ Composio execution error: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
# POWER 6: REMOTION & FFMPEG VIDEO RENDERING
# ─────────────────────────────────────────────────────────────────────────────
def run_video_task():
    composition = EXTRA_PARAMS.get("composition", "IntroPreview")
    output_file = EXTRA_PARAMS.get("output", "preview.mp4")
    
    notify_telegram(f"🎬 Remotion / FFmpeg Video Task Active\nComposition: {composition}")

    # If remotion project exists, render it
    if os.path.exists("package.json"):
        res = subprocess.run(["npx", "remotion", "render", composition, output_file], capture_output=True, text=True, timeout=300)
        if res.returncode == 0 and os.path.exists(output_file):
            send_file_telegram(output_file, caption=f"Rendered video: {output_file}", file_type="video")
            notify_telegram("✅ Remotion video successfully rendered and sent!")
            return
        else:
            notify_telegram(f"⚠️ Remotion warning: {res.stderr[:500]}")

    # Fallback to FFmpeg test animation/clip creation
    test_video = "output_motion.mp4"
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "color=c=black:s=1280x720:d=5",
        "-vf", "drawtext=text='Sangam Video Systems':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", test_video
    ]
    subprocess.run(ffmpeg_cmd, capture_output=True)
    if os.path.exists(test_video):
        send_file_telegram(test_video, caption="Generated motion preview", file_type="video")
        notify_telegram("✅ Video rendered via FFmpeg!")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN DISPATCH ROUTER
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Executing cloud task: {TASK_TYPE}")
    
    # Auto-detect YouTube tasks
    if "youtube.com" in TARGET_URL or "youtu.be" in TARGET_URL or TASK_TYPE == "youtube":
        run_youtube_task()
    elif TASK_TYPE == "composio":
        run_composio_task()
    elif TASK_TYPE == "script" or TASK_TYPE == "python":
        run_python_task()
    elif TASK_TYPE == "bash" or TASK_TYPE == "shell":
        run_bash_task()
    elif TASK_TYPE == "remotion" or TASK_TYPE == "video":
        run_video_task()
    else:
        # Default: Browser automation
        asyncio.run(run_browser_task())
