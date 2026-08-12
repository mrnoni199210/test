import os
import io
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from PIL import (
    Image,
    ImageEnhance,
    ImageFilter,
    ImageOps,
    ImageStat,
)

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_FILE_SIZE_MB = 15
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

MAX_IMAGE_DIMENSION = 4096
OUTPUT_QUALITY = 94

# Maximum number of CPU-heavy image jobs at once.
# Useful on GitHub Actions / low-resource servers.
MAX_CONCURRENT_JOBS = 2

executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_JOBS
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("telegram-image-bot")


# ============================================================
# IMAGE UTILITIES
# ============================================================

def resize_image(img):
    """
    Resize extremely large images while preserving aspect ratio.
    """

    width, height = img.size

    if max(width, height) <= MAX_IMAGE_DIMENSION:
        return img

    scale = MAX_IMAGE_DIMENSION / max(width, height)

    new_width = int(width * scale)
    new_height = int(height * scale)

    logger.info(
        "Resizing image: %sx%s -> %sx%s",
        width,
        height,
        new_width,
        new_height,
    )

    return img.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )


def calculate_brightness(img):
    """
    Estimate average image brightness.
    Returns 0-255.
    """

    gray = img.convert("L")

    stat = ImageStat.Stat(gray)

    return stat.mean[0]


def auto_exposure(img):
    """
    Automatically improve exposure based on average brightness.
    """

    brightness = calculate_brightness(img)

    if brightness < 55:
        # Dark image
        factor = 1.18

    elif brightness < 85:
        factor = 1.10

    elif brightness > 205:
        # Very bright image
        factor = 0.94

    elif brightness > 225:
        factor = 0.90

    else:
        factor = 1.0

    if factor != 1.0:
        img = ImageEnhance.Brightness(img).enhance(factor)

    return img


def improve_color(img):
    """
    Improve color without making it excessively saturated.
    """

    # Slight contrast improvement
    img = ImageEnhance.Contrast(img).enhance(1.08)

    # Mild color enhancement
    img = ImageEnhance.Color(img).enhance(1.06)

    return img


def reduce_noise(img):
    """
    Mild noise reduction while preserving detail.
    """

    # Very small median filter.
    # Keeps the image relatively sharp.
    return img.filter(
        ImageFilter.MedianFilter(size=3)
    )


def enhance_details(img):
    """
    Recover fine details after resizing / denoising.
    """

    img = ImageEnhance.Sharpness(img).enhance(1.20)

    # Unsharp mask provides better local detail
    # than simply increasing Sharpness.
    img = img.filter(
        ImageFilter.UnsharpMask(
            radius=1.2,
            percent=110,
            threshold=3,
        )
    )

    return img


def smart_highlights_shadows(img):
    """
    Mild highlight/shadow balancing using numpy.

    This is intentionally conservative so that
    the image doesn't become artificial.
    """

    arr = np.asarray(img).astype(np.float32)

    # Normalize
    normalized = arr / 255.0

    # Gentle gamma correction.
    # Slightly lifts dark areas.
    gamma = 0.96

    adjusted = np.power(
        normalized,
        gamma
    )

    adjusted = np.clip(
        adjusted * 255.0,
        0,
        255,
    )

    return Image.fromarray(
        adjusted.astype(np.uint8),
        "RGB",
    )


# ============================================================
# MAIN IMAGE PROCESSOR
# ============================================================

def process_image(image_bytes):
    """
    Professional-style photo enhancement pipeline.

    Pipeline:
        1. Load image
        2. Fix EXIF orientation
        3. Convert RGB
        4. Resize huge images
        5. Exposure correction
        6. Shadow/highlight balancing
        7. Noise reduction
        8. Color enhancement
        9. Detail enhancement
        10. High-quality JPEG export
    """

    try:

        if not image_bytes:
            raise ValueError("Empty image received.")

        if len(image_bytes) > MAX_FILE_SIZE:
            raise ValueError(
                f"Image exceeds {MAX_FILE_SIZE_MB} MB."
            )

        # ----------------------------------------------------
        # LOAD
        # ----------------------------------------------------

        input_buffer = io.BytesIO(image_bytes)

        img = Image.open(input_buffer)

        logger.info(
            "Input image: format=%s size=%sx%s",
            img.format,
            img.width,
            img.height,
        )

        # ----------------------------------------------------
        # FIX CAMERA ORIENTATION
        # ----------------------------------------------------

        img = ImageOps.exif_transpose(img)

        # ----------------------------------------------------
        # RGB CONVERSION
        # ----------------------------------------------------

        if img.mode != "RGB":
            img = img.convert("RGB")

        # ----------------------------------------------------
        # RESIZE
        # ----------------------------------------------------

        img = resize_image(img)

        # ----------------------------------------------------
        # AUTO EXPOSURE
        # ----------------------------------------------------

        img = auto_exposure(img)

        # ----------------------------------------------------
        # SHADOW / HIGHLIGHT BALANCING
        # ----------------------------------------------------

        img = smart_highlights_shadows(img)

        # ----------------------------------------------------
        # NOISE REDUCTION
        # ----------------------------------------------------

        img = reduce_noise(img)

        # ----------------------------------------------------
        # COLOR
        # ----------------------------------------------------

        img = improve_color(img)

        # ----------------------------------------------------
        # DETAILS
        # ----------------------------------------------------

        img = enhance_details(img)

        # ----------------------------------------------------
        # FINAL CONTRAST
        # ----------------------------------------------------

        img = ImageEnhance.Contrast(
            img
        ).enhance(1.03)

        # ----------------------------------------------------
        # EXPORT
        # ----------------------------------------------------

        output = io.BytesIO()

        img.save(
            output,
            format="JPEG",
            quality=OUTPUT_QUALITY,
            optimize=True,
            progressive=True,
        )

        output.seek(0)

        logger.info(
            "Processing complete: %sx%s",
            img.width,
            img.height,
        )

        return output

    except Exception as exc:

        logger.exception(
            "Image processing failed: %s",
            exc,
        )

        return None


# ============================================================
# COMMANDS
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Send me a photo and I'll enhance it automatically.\n\n"
        "✨ Auto lighting\n"
        "🎨 Color enhancement\n"
        "🔍 Detail enhancement\n"
        "🧹 Noise reduction\n"
        "📐 Smart resizing\n"
        "📷 EXIF orientation correction\n\n"
        "Use /help for more information."
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "📸 PHOTO ENHANCER\n\n"
        "Send a normal photo or a high-resolution image.\n\n"
        "The bot automatically performs:\n"
        "• Exposure correction\n"
        "• Shadow/highlight balancing\n"
        "• Noise reduction\n"
        "• Color enhancement\n"
        "• Sharpness/detail enhancement\n"
        "• Automatic orientation correction\n"
        "• Large-image resizing\n\n"
        f"Maximum file size: {MAX_FILE_SIZE_MB} MB\n"
        f"Maximum output dimension: {MAX_IMAGE_DIMENSION}px"
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🟢 Bot is online and ready.\n\n"
        "Send a photo to begin processing."
    )


# ============================================================
# PHOTO HANDLER
# ============================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    try:

        photo = update.message.photo[-1]

        # ----------------------------------------------------
        # FILE SIZE CHECK
        # ----------------------------------------------------

        if photo.file_size:

            if photo.file_size > MAX_FILE_SIZE:

                await update.message.reply_text(
                    f"❌ Image is too large.\n\n"
                    f"Maximum allowed size: "
                    f"{MAX_FILE_SIZE_MB} MB."
                )

                return

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        await update.message.chat.send_action(
            action=ChatAction.UPLOAD_PHOTO
        )

        status_message = await update.message.reply_text(
            "🔄 Processing your photo..."
        )

        # ----------------------------------------------------
        # DOWNLOAD
        # ----------------------------------------------------

        telegram_file = await photo.get_file()

        image_bytes = await telegram_file.download_as_bytearray()

        # ----------------------------------------------------
        # CPU-HEAVY PROCESSING
        # Run outside async event loop.
        # ----------------------------------------------------

        loop = context.application.loop

        processed_bytes = await loop.run_in_executor(
            executor,
            process_image,
            bytes(image_bytes),
        )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        if processed_bytes:

            await status_message.edit_text(
                "✅ Processing complete. Sending image..."
            )

            await update.message.reply_photo(
                photo=processed_bytes,
                caption="✨ Enhanced successfully."
            )

            try:
                await status_message.delete()
            except Exception:
                pass

        else:

            await status_message.edit_text(
                "❌ I couldn't process this image.\n"
                "Please try another photo."
            )

    except Exception as exc:

        logger.exception(
            "Photo handler failed: %s",
            exc,
        )

        try:

            await update.message.reply_text(
                "❌ Something went wrong while processing "
                "your photo.\n\n"
                "Please try again with another image."
            )

        except Exception:
            pass


# ============================================================
# DOCUMENT HANDLER
# ============================================================

async def handle_document(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message or not update.message.document:
        return

    document = update.message.document

    # Only allow common image files.
    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    if document.mime_type not in allowed_types:

        await update.message.reply_text(
            "❌ Please send a JPG, PNG or WEBP image."
        )

        return

    if (
        document.file_size
        and document.file_size > MAX_FILE_SIZE
    ):

        await update.message.reply_text(
            f"❌ File is too large.\n\n"
            f"Maximum allowed size: "
            f"{MAX_FILE_SIZE_MB} MB."
        )

        return

    try:

        await update.message.chat.send_action(
            action=ChatAction.UPLOAD_PHOTO
        )

        status_message = await update.message.reply_text(
            "🔄 Processing image..."
        )

        telegram_file = await document.get_file()

        image_bytes = await telegram_file.download_as_bytearray()

        loop = context.application.loop

        processed_bytes = await loop.run_in_executor(
            executor,
            process_image,
            bytes(image_bytes),
        )

        if processed_bytes:

            await status_message.edit_text(
                "✅ Processing complete. Sending image..."
            )

            await update.message.reply_photo(
                photo=processed_bytes,
                caption="✨ Enhanced successfully."
            )

            try:
                await status_message.delete()
            except Exception:
                pass

        else:

            await status_message.edit_text(
                "❌ Unable to process this image."
            )

    except Exception as exc:

        logger.exception(
            "Document handler failed: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ Error processing the image."
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.exception(
        "Telegram error:",
        exc_info=context.error,
    )


# ============================================================
# BOT
# ============================================================

def run_bot():

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    if not token:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN "
            "environment variable is missing."
        )

        sys.exit(1)

    logger.info(
        "======================================"
    )

    logger.info(
        "Telegram Photo Bot Starting..."
    )

    logger.info(
        "======================================"
    )

    # --------------------------------------------------------
    # APPLICATION
    # --------------------------------------------------------

    app = (
        ApplicationBuilder()
        .token(token)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    # --------------------------------------------------------
    # PHOTO
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo,
        )
    )

    # --------------------------------------------------------
    # IMAGE DOCUMENT
    # --------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.Document.IMAGE,
            handle_document,
        )
    )

    # --------------------------------------------------------
    # ERROR HANDLER
    # --------------------------------------------------------

    app.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # START POLLING
    # --------------------------------------------------------

    logger.info(
        "Bot is now polling Telegram..."
    )

    app.run_polling(
        poll_interval=1,
        timeout=30,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    run_bot()
