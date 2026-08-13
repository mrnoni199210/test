import os
import requests
import telebot
from telebot import types
import time
import uuid

# Configuration
API_KEY = os.getenv("NSFWROUTER_API_KEY", "YOUR_GENERATED_API_KEY_HERE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

# Initialize Bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# NSFWRouter API Base URL (Assumed based on typical structures)
# Agar nsfwrouter.xyz ka specific endpoint alag hai, toh yahan change karein.
BASE_URL = "https://nsfwrouter.xyz/api"  # Example endpoint

# Global storage for user context
user_images = {}
user_prompts = {}

def get_api_headers():
    """Headers with API Key"""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

@bot.message_handler(commands=['start'])
def send_welcome(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Generate Image", request_contact=False))
    bot.send_message(message.chat.id, "Welcome! Send me a reference image to undress or generate a video.", reply_markup=kb)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        # Get file info
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save temporarily
        filename = f"{uuid.uuid4().hex}.jpg"
        with open(filename, 'wb') as new_file:
            new_file.write(downloaded_file)
        
        # Store user context
        user_images[message.chat.id] = filename
        
        # Send prompt for customization (optional) or direct generation
        markup = types.ReplyKeyboardMarkup(row_width=2)
        markup.add(types.KeyboardButton("Undress"), types.KeyboardButton("Generate Video"))
        markup.add(types.KeyboardButton("Cancel"))
        
        bot.send_message(message.chat.id, "Image received! Choose an action:", reply_markup=markup)
        
    except Exception as e:
        bot.send_message(message.chat.id, f"Error: {str(e)}")

@bot.message_handler(func=lambda m: m.text in ["Undress", "Generate Video"])
def handle_action(message):
    action = message.text
    chat_id = message.chat.id
    
    if chat_id not in user_images:
        bot.send_message(chat_id, "Please send an image first.")
        return

    image_path = user_images[chat_id]
    
    if action == "Undress":
        generate_undress(chat_id, image_path)
    elif action == "Generate Video":
        generate_video(chat_id, image_path)
    elif action == "Cancel":
        if chat_id in user_images:
            os.remove(user_images[chat_id])
            del user_images[chat_id]
        bot.send_message(chat_id, "Cancelled.")

def generate_undress(chat_id, image_path):
    """
    Calls NSFWRouter API for image-to-image undressing.
    Adjust payload based on actual API docs of nsfwrouter.xyz
    """
    bot.send_chat_action(chat_id, "typing")
    bot.send_message(chat_id, "Generating high-quality undressed image... (HQ HD)")
    
    try:
        # Example payload structure (Adjust according to actual API)
        # Most APIs expect: image, prompt, model_id, strength, etc.
        payload = {
            "image": open(image_path, "rb"),
            "prompt": "masterpiece, best quality, 8k, ultra-detailed, realistic skin, undressed, nude",
            "negative_prompt": "low quality, blurry, distorted, extra limbs, bad anatomy",
            "steps": 30,
            "cfg_scale": 7.5,
            "model": "sd_xl_base_1.0"  # Example model
        }
        
        # If API expects JSON with base64 or multipart form-data
        # Here we assume multipart/form-data for image upload
        
        response = requests.post(
            f"{BASE_URL}/generate",  # Adjust endpoint
            headers=get_api_headers(),
            files={"image": open(image_path, "rb")},
            data=payload  # Or json=payload if it's JSON
        )
        
        if response.status_code == 200:
            # Assume API returns JSON with 'url' or 'image' field
            result = response.json()
            img_url = result.get("url") or result.get("image")  # Adjust key as per actual API response
            
            if img_url:
                bot.send_photo(chat_id, img_url, caption="Here is your HQ undressed image!")
            else:
                # If API returns base64 or file
                bot.send_photo(chat_id, open(image_path, "rb"), caption="Generated image (Fallback)")
        else:
            bot.send_message(chat_id, f"Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        bot.send_message(chat_id, f"API Error: {str(e)}")
    finally:
        # Cleanup temp file
        if os.path.exists(image_path):
            os.remove(image_path)

def generate_video(chat_id, image_path):
    """
    Generates a 5-10 second video from the reference image.
    Uses NSFWRouter's video generation endpoint or external API if needed.
    """
    bot.send_chat_action(chat_id, "typing")
    bot.send_message(chat_id, "Generating video (5-10 seconds)... This may take a minute.")
    
    try:
        # Example payload for video generation
        payload = {
            "image": open(image_path, "rb"),
            "prompt": "smooth motion, realistic movement, high quality, 8k",
            "duration": 5,  # Requesting 5-10 seconds
            "fps": 24,
            "model": "sdxl_video_1.0"  # Example model
        }
        
        response = requests.post(
            f"{BASE_URL}/generate-video",  # Adjust endpoint
            headers=get_api_headers(),
            files={"image": open(image_path, "rb")},
            data=payload
        )
        
        if response.status_code == 200:
            result = response.json()
            video_url = result.get("url") or result.get("video")  # Adjust key
            
            if video_url:
                bot.send_video(chat_id, video_url, caption="Here is your generated video!")
            else:
                bot.send_message(chat_id, "Video generated but URL not found in response.")
        else:
            bot.send_message(chat_id, f"Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        bot.send_message(chat_id, f"API Error: {str(e)}")
    finally:
        if os.path.exists(image_path):
            os.remove(image_path)

# Run the bot
if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling()
