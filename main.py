import os
import io
import sys
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

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
    
    for y in range(h):
        if y < top_y or y > bottom_y:
            continue
            
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
        (center_x - hip_width/2, bottom_y)
    ]
    draw.polygon(pts, fill=255)
    
    # Feather edges
    mask = mask.filter(ImageFilter.GaussianBlur(radius=15))
    
    # 2. GENERATE SKIN
    # Sample neck area for color
    try:
        neck_patch = img_np[neck_y-10:neck_y+10, center_x-10:center_x+10]
        skin_rgb = get_skin_color(neck_patch)
    except:
        skin_rgb = (200, 150, 120)
        
    skin_layer = create_3d_skin_layer(img_np.shape, skin_rgb, center_x, top_y, bottom_y)
    
    # 3. COMPOSITE
    mask_np = np.array(mask) / 255.0
    mask_np = np.stack([mask_np, mask_np, mask_np], axis=-1)
    
    result = (img_np * (1 - mask_np)) + (skin_layer * mask_np)
    result = result.astype(np.uint8)
    
    # Save to BytesIO
    result_img = Image.fromarray(result)
    output_bytes = io.BytesIO()
    result_img.save(output_bytes, format='JPEG', quality=90)
    output_bytes.seek(0)
    
    return output_bytes

# --- TELEGRAM BOT LOGIC ---

def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    update.message.reply_html(
        f"Hi {user.mention_html()}! 👋\n"
        f"Upload a photo, and I'll digitally 'undress' it using pure Python math.\n"
        f"No AI, just pixels and geometry."
    )

def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        # Get the image file
        photo = update.message.photo[-1] if update.message.photo else None
        doc = update.message.document if update.message.document else None
        
        image_file = photo or doc
        
        if not image_file:
            update.message.reply_text("That looked like a text message. Please upload an image!")
            return

        update.message.reply_text("🔄 Processing... (Scanning pixels & generating skin texture)")
        
        # Download the file from Telegram
        file = context.bot.get_file(image_file.file_id)
        image_bytes = file.download_as_bytearray()
        
        # Process the image
        processed_bytes = process_image(image_bytes)
        
        # Send the result
        update.message.reply_photo(
            photo=processed_bytes,
            caption="✨ Done. Generated using pure NumPy/PIL math."
        )
        
    except Exception as e:
        print(f"Error: {e}")
        update.message.reply_text(f"Oops! Something went wrong: {str(e)}")

def main() -> None:
    # Get token from environment variable
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not found!")
        sys.exit(1)

    # Build the bot
    application = ApplicationBuilder().token(token).build()
    
    # Handlers
    start_handler = CommandHandler('start', start)
    image_handler = MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image)
    
    application.add_handler(start_handler)
    application.add_handler(image_handler)
    
    print("Bot started successfully! Waiting for messages...")
    # Run the bot
    application.run_polling()
    
    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
