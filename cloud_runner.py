import os
import asyncio
import requests
from playwright.async_api import async_playwright

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TARGET_URL = os.getenv("TARGET_URL", "https://example.com")
INSTRUCTIONS = os.getenv("INSTRUCTIONS", "Open the page and capture a screenshot")

def notify_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print(text)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def send_screenshot_telegram(image_path, caption=""):
    if not BOT_TOKEN or not CHAT_ID or not os.path.exists(image_path):
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(image_path, "rb") as photo:
            requests.post(url, data={"chat_id": CHAT_ID, "caption": caption}, files={"photo": photo}, timeout=30)
    except Exception as e:
        print(f"Telegram photo error: {e}")

async def run_automation():
    notify_telegram(f"Cloud VM active (Ubuntu, 7GB RAM).\nTarget: {TARGET_URL}\nTask: {INSTRUCTIONS}")

    screenshot_path = "result.png"

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

        notify_telegram(f"Opening {TARGET_URL} in cloud Chromium...")

        try:
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        except Exception:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)

        page_title = await page.title()
        await asyncio.sleep(2)
        await page.screenshot(path=screenshot_path, full_page=True)

        body_text = await page.inner_text("body")
        lines = [line.strip() for line in body_text.split("\n") if len(line.strip()) > 30]
        preview = "\n".join(lines[:4]) if lines else "No text extracted."

        await browser.close()

    send_screenshot_telegram(screenshot_path, caption=f"Task complete\nPage: {page_title}\nURL: {TARGET_URL}")
    notify_telegram(f"Summary:\n{preview}\n\nTask finished successfully!")

if __name__ == "__main__":
    asyncio.run(run_automation())
