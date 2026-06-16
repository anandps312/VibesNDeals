"""
VibesNDeals - Telegram Affiliate Bot
=====================================
Reads deals from Google Sheets and posts to Telegram channel automatically.

Requirements:
    pip install gspread google-auth python-telegram-bot apscheduler

Setup:
    1. Place your credentials.json in the same folder as this script
    2. Fill in the CONFIG section below
    3. Run: python vibesndeal_bot.py
"""
import os
import gspread
import asyncio
import logging
from datetime import datetime
from google.oauth2.service_account import Credentials
from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from pathlib import Path

# ============================================================
# CONFIG — Fill these in before running
# ============================================================

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

# print("TOKEN:", os.environ.get("TELEGRAM_BOT_TOKEN"))
# print("CHANNEL:", os.environ.get("TELEGRAM_CHANNEL_ID"))
# print("SHEET:", os.environ.get("GOOGLE_SHEET_NAME"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
GOOGLE_SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME")
CREDENTIALS_FILE = "credentials.json"                # Downloaded from Google Cloud
POST_INTERVAL_HOURS = 3                              # How often to post (in hours)
PEAK_HOURS_ONLY = False                              # Only post between 8AM - 11PM IST
MAX_POSTS_PER_RUN = 2                                # Max deals to post per run

# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

# def connect_to_sheet():
#     """Connect to Google Sheets using service account credentials."""
#     scopes = [
#         "https://www.googleapis.com/auth/spreadsheets",
#         "https://www.googleapis.com/auth/drive"
#     ]
#     creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
#     client = gspread.authorize(creds)
#     sheet = client.open(GOOGLE_SHEET_NAME).sheet1
#     return sheet
def connect_to_sheet():
    import os
    import json
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    
    client = gspread.authorize(creds)
    
    # Open by name and access first sheet
    spreadsheet = client.open(GOOGLE_SHEET_NAME)
    sheet = spreadsheet.sheet1
    return sheet

def get_pending_deals(sheet):
    """Fetch all rows where Posted = No."""
    all_rows = sheet.get_all_records()
    pending = []

    for i, row in enumerate(all_rows, start=2):  # Row 2 onwards (row 1 = headers)
        if str(row.get("Posted", "")).strip().lower() == "no":
            row["_row_number"] = i
            pending.append(row)

    return pending


def mark_as_posted(sheet, row_number):
    """Mark a deal as posted in the sheet."""
    # Column H = Posted, Column I = Posted On
    sheet.update_cell(row_number, 8, "Yes")
    sheet.update_cell(row_number, 9, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(f"Marked row {row_number} as Posted.")

# ============================================================
# MESSAGE FORMATTER
# ============================================================

def format_deal_message(deal):
    """Format a deal row into a Telegram message."""

    name = deal.get("Product Name", "").strip()
    category = deal.get("Category", "").strip()
    original = deal.get("Original Price", "").strip()
    discounted = deal.get("Deal Price", "").strip()
    discount = deal.get("Discount %", "").strip()
    link = deal.get("Affiliate Link", "").strip()

    # Emoji map by category
    category_emoji = {
        "electronics": "📱",
        "fashion": "👗",
        "home": "🏠",
        "kitchen": "🍳",
        "books": "📚",
        "sports": "⚽",
        "beauty": "💄",
        "toys": "🧸",
        "gaming": "🎮",
        "baby products": "👶",
        "health": "💊",
        "pet": "🐶",
        "automotive": "🚗",
        "grocery": "🛒",
        "others": "🛍️",
        "computers": "💻"
    }
    emoji = category_emoji.get(category.lower(), "🛒")

#     message = f"""🚨 AMAZON PRICE DROP 🚨

# 🛍️ {emoji} *{name}*

# 💰 Now: *₹{discounted}*
# ❌ MRP: ~~₹{original}~~
# 🔥 *{discount} OFF*

# 👉 [⚡ GRAB DEAL]({link})

# 📢 *Share @VibesNDeals with friends!*
# """
    discount_num = int(discount.replace('%', '').strip())

    if discount_num >= 50:
        message = f"""
    🚨 *MEGA PRICE DROP* 🔥 *{discount} OFF*

    {emoji} *{name}* @*{discounted}* MRP: ~~{original}~~

    👉 {link}

    """
    else:
        message = f"""
    🔥 *DEAL ALERT* 🔥*{discount} OFF*

    🛍️ *{name}* @*{discounted}*

    👉 {link}

    # 📢 *Share @VibesNDeals with friends!*
    """
    return message.strip()

# ============================================================
# PEAK HOURS CHECK
# ============================================================

def is_peak_hour():
    """Check if current IST time is within peak hours (8 AM - 11 PM)."""
    now_hour = datetime.now().hour  # Assumes server is in IST
    return 8 <= now_hour <= 23

# ============================================================
# MAIN POSTING LOGIC
# ============================================================

async def post_deals():
    """Main function: fetch pending deals and post to Telegram."""

    # Peak hours check
    if PEAK_HOURS_ONLY and not is_peak_hour():
        logger.info("Outside peak hours. Skipping this run.")
        return

    logger.info("Starting deal posting run...")

    try:
        sheet = connect_to_sheet()
        pending_deals = get_pending_deals(sheet)

        if not pending_deals:
            logger.info("No pending deals found in sheet.")
            return

        logger.info(f"Found {len(pending_deals)} pending deals. Posting up to {MAX_POSTS_PER_RUN}.")

        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        posted_count = 0

        for deal in pending_deals[:MAX_POSTS_PER_RUN]:
            try:
                message = format_deal_message(deal)
                image_url = deal.get("Image URL", "").strip()

                if image_url:
                    # Post with image
                    await bot.send_photo(
                        chat_id=TELEGRAM_CHANNEL_ID,
                        photo=image_url,
                        caption=message,
                        parse_mode="Markdown"
                    )
                else:
                    # Post text only
                    await bot.send_message(
                        chat_id=TELEGRAM_CHANNEL_ID,
                        text=message,
                        parse_mode="Markdown",
                        disable_web_page_preview=False
                    )

                # Mark as posted in sheet
                mark_as_posted(sheet, deal["_row_number"])
                posted_count += 1
                logger.info(f"Posted: {deal.get('Product Name')}")

                # Small delay between posts to avoid spam
                await asyncio.sleep(5)

            except TelegramError as e:
                logger.error(f"Telegram error for {deal.get('Product Name')}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")

        logger.info(f"Run complete. Posted {posted_count} deals.")

    except Exception as e:
        logger.error(f"Sheet connection error: {e}")

# ============================================================
# SCHEDULER — Runs every X hours automatically
# ============================================================

async def main():
    logger.info("VibesNDeals Bot starting up... 🔥")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        post_deals,
        trigger="interval",
        hours=POST_INTERVAL_HOURS,
        next_run_time=datetime.now()  # Run immediately on startup too
    )
    scheduler.start()

    logger.info(f"Scheduler running. Posting every {POST_INTERVAL_HOURS} hours.")

    # Keep the bot alive
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
        scheduler.shutdown()

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
