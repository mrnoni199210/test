import os
import io
import sys
import time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.error import Conflict

# --- ROBUST IMAGE PROCESSING ---

def get_skin_color_safe(img_np, face_x, face_y, h, w):
    """Safely samples skin color from the neck area below the face."""
    # Define neck region: Just below the face center
    neck_top = min(face_y + 20, h - 50)
    neck_bottom = min(neck_top + 40, h)
    neck_left = max(int(w * 0.3), 0)
    neck_right = min(int(w * 0.7), w)
    
    # Extract region
    if neck_top >= neck_bottom or neck_left >= neck_right:
        # Fallback to general upper torso if neck is out of bounds
        neck_top = int(h * 0.1)
        neck_bottom = int(h * 0.3)
        neck_left = int(w * 0.2)
        neck_right = int(w * 0.8)

    # Ensure indices are within bounds
    y1, y2 = max(0, neck_top), min(h, neck_bottom)
    x1, x2 = max(0, neck_left), min(w, neck_right)
    
    region = img_np[y1:y2, x1:x2]
    
    if region.size == 0:
        return (200, 160, 140)  # Fallback beige

    # Calculate mean RGB
    r = np.mean(region[:, :, 0])
    g = np.mean(region[:, :, 1])
    b = np.mean(region[:, :, 2])
    
    return (int(r), int(g), int(b))

def detect_face_robust(img_np):
    """
    Detects face using luminance variance and edge density in the top 40%.
    Returns (center_x, center_y).
    """
    h, w, _ = img_np.shape
    search_h = int(h * 0.5)
    search_area = img_np[0:search_h, :, :]
    
    sh, sw, _ = search_area.shape
    
    # Convert to grayscale for faster processing
    gray = np.dot(search_area[..., :3], [0.2989, 0.5870, 0.1141])
    
    best_score = 0
    best_x, best_y = int(w * 0.5), int(h * 0.2)
    
    # Grid search with step size
    step = max(10, sw // 15)
    patch_h, patch_w = 60, 60
    
    for y in range(0, sh - patch_h, step):
        for x in range(0, sw - patch_w, step):
            patch = gray[y:y+patch_h, x:x+patch_w]
            
            # Metric: Variance (texture) + Mean Brightness (not too dark)
            var = np.var(patch)
            mean_brightness = np.mean(patch)
            
            # Face usually has high texture and medium brightness
            score = var * (mean_brightness / 100.0)
            
            if score > best_score:
                best_score = score
                best_x = x + patch_w // 2
                best_y = y + patch_h // 2
                
    return best_x, best_y

def process_image_robust(image_bytes):
    """
    Processes image with vectorized NumPy ops for speed and accuracy.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img_np = np.array(img, dtype=np.float32)  # Use float32 for precision
        h, w, _ = img_np.shape
        
        # 1. Detect Face
        face_x, face_y = detect_face_robust(img_np)
        
        # 2. Define Torso Geometry
        # Neck starts below face
        neck_y = face_y + 30
        torso_top = neck_y
        torso_bottom = int(h * 0.75)  # End at hips
        
        # Widths
        neck_width = int(w * 0.15)
        hip_width = int(w * 0.4)
        
        # 3. Create Mask (Vectorized)
        # Create a grid of coordinates
        y_coords, x_coords = np.meshgrid(np.arange(h), np.arange(w), indexing='ij')
        
        # Define polygon bounds for the mask
        # We'll create a mask where value = 1 inside the hourglass, 0 outside
        mask = np.zeros((h, w), dtype=np.float32)
        
        # Calculate left and right boundaries at each Y
        # Linear interpolation for width
        y_range = torso_bottom - torso_top
        for y in range(torso_top, torso_bottom):
            if y_range == 0: break
            t = (y - torso_top) / y_range  # 0 at top, 1 at bottom
            
            # Width at this Y
            current_width = neck_width + (hip_width - neck_width) * t
            
            # Center X (slightly adjust based on face X)
            center_x = face_x
            
            left_x = center_x - current_width / 2
            right_x = center_x + current_width / 2
            
            # Set mask to 1 in this row
            # Clip to image bounds
            col_start = max(0, int(left_x))
            col_end = min(w, int(right_x))
            
            if col_end > col_start:
                mask[y, col_start:col_end] = 1.0
        
        # Feather the mask using a Gaussian Blur (via PIL for speed)
        mask_img = Image.fromarray((mask * 255).astype(np.uint8), mode='L')
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=10))
        mask = np.array(mask_img, dtype=np.float32) / 255.0
        
        # 4. Generate Realistic Skin Layer
        # Get base skin color
        skin_rgb = get_skin_color_safe(img_np, face_x, face_y, h, w)
        r, g, b = skin_rgb
        
        # Create base skin layer (same color everywhere)
        skin_layer = np.zeros_like(img_np)
        skin_layer[:, :, 0] = r
        skin_layer[:, :, 1] = g
        skin_layer[:, :, 2] = b
        
        # Add 3D Shading (Vectorized)
        # Create a radial gradient centered on the torso center
        torso_center_y = (torso_top + torso_bottom) / 2
        torso_center_x = face_x
        
        # Distance from center
        dist_y = np.abs(y_coords - torso_center_y)
        dist_x = np.abs(x_coords - torso_center_x)
        
        # Normalize distances
        max_dy = (torso_bottom - torso_top) / 2
        max_dx = w / 2
        
        # Combine distances for a "cylinder" effect
        # We want the center to be brighter (highlight) and edges darker (shadow)
        # Use a combination of vertical and horizontal distance
        norm_dy = np.clip(dist_y / max_dy, 0, 1)
        norm_dx = np.clip(dist_x / max_dx, 0, 1)
        
        # Shading factor: 1.0 at center, 0.7 at edges
        # Using a Gaussian-like falloff for smoothness
        shade = np.exp(-((norm_dy ** 2) + (norm_dx ** 2)) * 0.5)
        shade = np.clip(shade, 0.6, 1.1)  # Clamp between 60% and 110% brightness
        
        # Apply shading to skin layer
        skin_layer[:, :, 0] *= shade
        skin_layer[:, :, 1] *= shade
        skin_layer[:, :, 2] *= shade
        
        # Add Noise (Texture)
        noise = np.random.rand(h, w, 3) * 15  # 15% intensity
        skin_layer += noise
        skin_layer = np.clip(skin_layer, 0, 255)
        
        # 5. Composite
        # Blend: (Original * (1-Mask)) + (Skin * Mask)
        mask_3d = np.stack([mask, mask, mask], axis=-1)
        result = (img_np * (1 - mask_3d)) + (skin_layer * mask_3d)
        
        # Convert back to uint8
        result = result.astype(np.uint8)
        
        # Save
        output = io.BytesIO()
        Image.fromarray(result).save(output, format='JPEG', quality=90)
        output.seek(0)
        return output

    except Exception as e:
        print(f"Error processing image: {e}")
        import traceback
        traceback.print_exc()
        return None

# --- TELEGRAM BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a photo! I will undress it using pure Python math.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1] # Get highest resolution
    file = await photo.get_file()
    image_bytes = await file.download_as_bytearray()
    
    await update.message.reply_text("🔄 Processing... (This takes a few seconds)")
    
    processed_bytes = process_image_robust(image_bytes)
    
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
