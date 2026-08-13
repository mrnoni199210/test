import os
import requests
import telebot
from telebot import types
import base64

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NSFW_API_KEY = os.getenv("NSFWROUTER_API_KEY")
# Base URL: Usually just the domain without /console
BASE_URL = "https://nsfwrouter.xyz/api/v1" 

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Store user state: {chat_id: {"image_path": "...", "step": "wait_prompt"}}
user_data = {}

def get_headers():
    return {
        "Authorization": f"Bearer {NSFW_API_KEY}",
        "Content-Type": "application/json"
    }

def encode_image_to_base64(file_path):
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Send me a reference image to start undressing or video generation.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save image temporarily
        filename = f"{message.chat.id}.jpg"
        with open(filename, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        user_data[message.chat.id] = {
            "image_path": filename,
            "step": "prompt"
        }
        
        bot.reply_to(message, "Image received! Now send me a prompt (e.g., 'undress, realistic, 8k') or type '/generate' for default.")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(func=lambda message: message.chat.id in user_data and user_data[message.chat.id]["step"] == "prompt")
def handle_prompt(message):
    chat_id = message.chat.id
    if message.text == '/generate':
        prompt = "undress, realistic, high quality, 8k, masterpiece"
    else:
        prompt = message.text
    
    user_data[chat_id]["prompt"] = prompt
    generate_and_send(chat_id)

def generate_and_send(chat_id):
    bot.send_chat_action(chat_id, 'typing')
    bot.send_message(chat_id, "Generating... this might take a minute.")
    
    data = user_data[chat_id]
    img_path = data["image_path"]
    prompt = data.get("prompt", "undress, realistic")
    
    try:
        # Encode image
        b64_image = encode_image_to_base64(img_path)
        
        # Payload for Img2Img (Most likely endpoint for NSFW Router)
        payload = {
            "image": b64_image,
            "prompt": prompt,
            "negative_prompt": "low quality, blurry, distorted, bad anatomy, extra limbs",
            "steps": 30,
            "cfg_scale": 7.5,
            "width": 1024,
            "height": 1024,
            "model": "sdxl" # Try "flux" or "sdxl" if this fails
        }
        
        # Try Img2Img Endpoint first
        try:
            url = f"{BASE_URL}/img2img"
            response = requests.post(url, json=payload, headers=get_headers(), timeout=120)
        except:
            # Fallback to simple generate if img2img fails
            url = f"{BASE_URL}/generate"
            response = requests.post(url, json=payload, headers=get_headers(), timeout=120)
            
        if response.status_code == 200:
            result = response.json()
            # Extract image URL from response (Key might vary)
            img_url = result.get("url") or result.get("image") or result.get("images")[0] if "images" in result else None
            
            if img_url:
                bot.send_photo(chat_id, img_url, caption=f"Generated:\n{prompt}")
            else:
                bot.send_message(chat_id, "Success but no image URL found in response. Check API docs.")
        else:
            bot.send_message(chat_id, f"API Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        bot.send_message(chat_id, f"Error: {str(e)}")
    finally:
        # Cleanup
        if os.path.exists(img_path):
            os.remove(img_path)

# Run
if __name__ == "__main__":
    bot.infinity_polling()
