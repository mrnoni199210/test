import os
import requests
import telebot
from telebot import types
import base64
import time
import logging

# --- CONFIGURATION ---
# These keys will be injected via GitHub Secrets
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NSFW_API_KEY = os.getenv("NSFWROUTER_API_KEY")
# Adjust this base URL if your API docs say otherwise
BASE_URL = os.getenv("NSFW_BASE_URL", "https://nsfwrouter.xyz/api/v1")

# Enable logging
logging.basicConfig(level=logging.INFO)

# Initialize Bot
bot = telebot.TeleBot(BOT_TOKEN)

# In-memory storage for user state
user_data = {}

def get_api_headers():
    """Return headers with Authorization"""
    return {
        "Authorization": f"Bearer {NSFW_API_KEY}",
        "Content-Type": "application/json"
    }

def encode_image_to_base64(file_path):
    """Encode image file to base64 string"""
    try:
        with open(file_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        print(f"Error encoding image: {e}")
        return None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Welcome message"""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Start Generating"))
    bot.reply_to(message, "Welcome! Send me a reference image to start.", reply_markup=kb)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Handle incoming photo"""
    try:
        # Get file info
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save image temporarily
        # Use a unique name to avoid conflicts
        filename = f"{message.chat.id}_{int(time.time())}.jpg"
        with open(filename, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        # Store user data
        user_data[message.chat.id] = {
            "image_path": filename,
            "step": "prompt"
        }
        
        bot.reply_to(message, "✅ Image received! Now send me a prompt (e.g., 'undress, realistic, 8k') or type `/generate` for default.")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(func=lambda message: message.chat.id in user_data and user_data[message.chat.id]["step"] == "prompt")
def handle_prompt(message):
    """Handle user prompt"""
    chat_id = message.chat.id
    
    if message.text == '/generate':
        prompt = "undress, realistic, high quality, 8k, masterpiece, best quality"
    else:
        prompt = message.text
    
    user_data[chat_id]["prompt"] = prompt
    generate_and_send(chat_id)

def generate_and_send(chat_id):
    """Main generation logic"""
    bot.send_chat_action(chat_id, 'typing')
    bot.send_message(chat_id, "⏳ Generating... This might take a minute.")
    
    data = user_data[chat_id]
    img_path = data["image_path"]
    prompt = data.get("prompt", "undress, realistic")
    
    try:
        # Encode image to Base64 (More reliable than file objects)
        b64_image = encode_image_to_base64(img_path)
        
        if not b64_image:
            bot.send_message(chat_id, "❌ Error: Could not read image file.")
            return

        # Payload for Img2Img
        payload = {
            "image": b64_image,  # Sending as base64 string
            "prompt": prompt,
            "negative_prompt": "low quality, blurry, distorted, bad anatomy, extra limbs",
            "steps": 30,
            "cfg_scale": 7.5,
            "width": 1024,
            "height": 1024,
            "model": "sdxl" 
        }
        
        # Try Img2Img Endpoint first
        try:
            url = f"{BASE_URL}/img2img"
            response = requests.post(url, json=payload, headers=get_api_headers(), timeout=120)
        except Exception:
            # Fallback to simple generate if img2img fails
            url = f"{BASE_URL}/generate"
            response = requests.post(url, json=payload, headers=get_api_headers(), timeout=120)
            
        if response.status_code == 200:
            result = response.json()
            # Extract image URL from response (Key might vary)
            img_url = result.get("url") or result.get("image") or result.get("images")[0] if "images" in result else None
            
            if img_url:
                bot.send_photo(chat_id, img_url, caption=f"Generated:\n{prompt}")
            else:
                bot.send_message(chat_id, "✅ Success but no image URL found in response. Check API docs.")
        else:
            bot.send_message(chat_id, f"❌ API Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {str(e)}")
    finally:
        # Cleanup temp file
        if os.path.exists(img_path):
            os.remove(img_path)
        # Clear user data for this chat
        if chat_id in user_data:
            del user_data[chat_id]

# Run the bot
if __name__ == "__main__":
    print("🤖 Bot is running...")
    bot.infinity_polling()
