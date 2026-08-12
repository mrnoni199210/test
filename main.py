import os
import io
import sys
import time
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.error import Conflict

# --- CORE IMAGE PROCESSING LOGIC ---

def generate_perlin_noise(w, h, scale=20):
    """Generates a basic noise texture for skin realism"""
    noise = np.random.rand(w, h)
    noise = noise * 255
    noise = noise.astype(np.uint8)
    return noise

def get_skin_color(face_roi):
    """Samples the center of the face to find the base skin tone"""
    h, w, _ = face_roi.shape
    # Avoid edges, sample center
    center_crop = face_roi[h//3:h//3+h//3, w//3:w//3+w//3]
    if center_crop.size == 0:
        return (200, 150, 120) # Fallback beige
    r = np.mean(center_crop[:,:,0])
    g = np.mean(center_crop[:,:,1])
    b = np.mean(center_crop[:,:,2])
    return (int(r), int(g), int(b))

def create_3d_skin_layer(shape, skin_color, center_x, top_y, bottom_y):
    """
    Creates a realistic skin layer using math (Gradients + Noise)
    """
    h, w, _ = shape
    skin_layer = np.zeros(shape, dtype=np.uint8)
    noise = generate_perlin_noise(w, h)
    
    r, g, b = skin_color
    
    # Pre-calculate vertical center
    vert_center = (top_y + bottom_y) / 2
    
    # Only process the torso area to save CPU
    start_y = max(0, int(top_y))
    end_y = min(h, int(bottom_y))
    
    for y in range(start_y, end_y):
        dist_from_center = abs(y - vert_center)
        max_dist = (bottom_y - top_y) / 2
        
        # Normalize 0 to 1
        if max_dist == 0: max_dist = 1
        norm = dist_from_center / max_dist
        
        # Create a gentle curve for volume (Cubed)
        shade_factor = 1 - (norm ** 2)
        
        # Horizontal gradient for chest curve
        for x in range(w):
            x_dist = abs(x - center_x) / max(w/2, 1)
            # Blend vertical and horizontal depth
            depth = shade_factor * (1 - (x_dist * 0.5))
            
            # Clamp depth
            if depth < 0.7: depth = 0.7
            if depth > 1.0: depth = 1.0
            
            # Mix base color with noise
            noise_val = (noise[y, x] / 255.0) * 15 # 15% noise intensity
            
            skin_layer[y, x, 0] = np.clip((r * depth) + noise_val, 0, 255)
            skin_layer[y, x, 1] = np.clip((g * depth) + noise_val, 0, 255)
            skin_layer[y, x, 2] = np.clip((b * depth) + noise_val, 0, 255)
            
    return skin_layer

def process_image(image_bytes):
    """
    Takes image bytes, processes them, and returns processed image bytes.
    """
    try:
        # Load image
        img = Image.open(io.BytesIO(image_bytes))
        img_np = np.array(img)
        h, w, _ = img_np.shape
        
        # 1. DETECT FACE (Simple luminance variance)
        face_y, face_x = int(h * 0.2), int(w * 0.5)
        best_var = 0
        
        # Scan top 40% of image
        search_area = img_np[0:int(h*0.5), :, :]
        sh, sw, _ = search_area.shape
        
        # Step size depends on image width for speed
        step = max(10, int(sw / 20))
        
        for y in range(0, sh - 60, step): 
            for x in range(0, sw - 60, step):
                patch = search_area[y:y+60, x:x+60]
                if patch.size > 0:
                    var = np.var(patch)
                    if var > best_var:
                        best_var = var
                        face_y = y
                        face_x = x

        # Define Torso Boundaries
        neck_y = face_y + 40
        neck_x = face_x + 30 
        center_x = int(w * 0.5)
        
        top_y = neck_y
        bottom_y = int(h * 0.75) 
        
        neck_width = int(w * 0.2)
        hip_width = int(w * 0.45)
        
        # Create Mask
        mask = Image.new('L', (w, h), 0)
        draw = ImageDraw.Draw(mask)
        
        # Draw hourglass polygon
        pts = [
            (center_x - neck_width/2, top_y),
            (center_x + neck_width/2, top_y),
            (center_x + hip_width/2, bottom_y),
            (center_x - neck_width/2, bottom_y)
        ]
        draw.polygon(pts, fill=255)
        
        # Feather edges
        mask = mask.filter(ImageFilter.GaussianBlur(radius=15))
        
        # 2. GENERATE SKIN
        # Calculate skin color from the face/neck area
        neck_patch = img_np[neck_y-10:neck_y+10, center_x-10:center_x+10]
        skin_rgb = get_skin_color(neck_patch)
        
        # Generate the textured skin layer
        skin_layer = create_3d_skin_layer(img_np.shape, skin_rgb, center_x, top_y, bottom_y)
        
        # 3. COMPOSITE
        # Convert mask to numpy for alpha blending
        mask_np = np.array(mask) / 255.0
        mask_np = np.stack([mask_np, mask_np, mask_np], axis=-1)
        
        # Blend: (Original * (1-Mask)) + (Skin * Mask)
        result = (img_np * (1 - mask_np)) + (skin_layer * mask_np)
        result = result.astype(np.uint8)
        
        # Save to BytesIO
        output = io.BytesIO()
        Image.fromarray(result).save(output, format='JPEG', quality=90)
        output.seek(0)
        return output

    except Exception as e:
        print(f"Error processing image: {e}")
        return None

# --- TELEGRAM BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a photo! I will undress it using pure Python math.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1] # Get highest resolution
    file = await photo.get_file()
    image_bytes = await file.download_as_bytearray()
    
    await update.message.reply_text("🔄 Processing... (This takes a few seconds)")
    
    processed_bytes = process_image(image_bytes)
    
    if processed_bytes:
        await update.message.reply_photo(processed_bytes, caption="✨ Done! (Pure Python, No AI)")
    else:
        await update.message.reply_text("❌ Error processing image. Try a clearer photo.")

def run_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found!")
        sys.exit(1)

    app = ApplicationBuilder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Bot starting...")
    
    # Retry logic to handle "Conflict" errors from GitHub Actions restarts
    max_retries = 5
    for i in range(max_retries):
        try:
            print(f"Attempting to connect (Try {i+1})...")
            app.run_polling(timeout=30)
            print("Bot stopped gracefully.")
            break
        except Conflict:
            print("Conflict detected! Waiting 10 seconds for previous instance to die...")
            time.sleep(10)
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    run_bot()
