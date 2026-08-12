import os
import io
import sys
import numpy as np

from PIL import Image, ImageEnhance
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# --------------------------------------------------
# IMAGE PROCESSING
# --------------------------------------------------

def process_image(image_bytes):
    """
    Takes image bytes, applies basic safe image enhancement,
    and returns processed image bytes.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Basic image enhancement
        img = ImageEnhance.Sharpness(img).enhance(1.2)
        img = ImageEnhance.Contrast(img).enhance(1.05)

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=90)
        output.seek(0)

        return output

    except Exception as e:
        print(f"Error processing image: {e}")
        return None


# --------------------------------------------------
# TELEGRAM BOT HANDLERS
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me a photo and I will process it."
    )


async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        photo = update.message.photo[-1]

        file = await photo.get_file()

        image_bytes = await file.download_as_bytearray()

        await update.message.reply_text(
            "🔄 Processing... Please wait."
        )

        processed_bytes = process_image(image_bytes)

        if processed_bytes:
            await update.message.reply_photo(
                processed_bytes,
                caption="✨ Done!"
            )
        else:
            await update.message.reply_text(
                "❌ Error processing image. Try another photo."
            )

    except Exception as e:
        print(f"Photo handler error: {e}")

        await update.message.reply_text(
            "❌ Something went wrong while processing the image."
        )


# --------------------------------------------------
# RUN BOT
# --------------------------------------------------

def run_bot():

    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not found!")
        sys.exit(1)

    app = ApplicationBuilder().token(token).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )

    print("======================================")
    print("Telegram Bot Starting...")
    print("======================================")

    # Single polling instance.
    # No manual Conflict retry loop.
    app.run_polling(
        poll_interval=1,
        timeout=30,
        drop_pending_updates=True
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    run_bot()
