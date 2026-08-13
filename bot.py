import requests
import base64
import os

# 1. PASTE YOUR API KEY HERE
API_KEY = "sk-b6a8c4d7fe883e27726a83099867ae220d02828df04354b0"  # Replace with the key from your screenshot

# 2. SET THE BASE URL
# Usually it's just the domain + /api/v1
BASE_URL = "https://nothrotting.xyz/api/v1" # Adjust if the domain is different

# 3. Prepare the Image
image_path = "reference.jpg" # Make sure you have a 'reference.jpg' in the same folder
image_path = "reference.png" # Make sure you have a 'reference.jpg' in the same folder


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def generate_image():
    if not os.path.exists(image_path):
        print("❌ Error: reference.jpg not found!")
        return

    try:
        # Encode image to Base64
        b64_image = encode_image(image_path)

        # Payload for NSFW Router API
        # Most APIs accept 'image' as base64 and 'prompt' as text
        payload = {
            "image": b64_image,
            "prompt": "masterpiece, best quality, 8k, ultra-detailed, undress, realistic",
            "negative_prompt": "low quality, blurry, distorted",
            "steps": 30,
            "cfg_scale": 7.5,
            "width": 1024,
            "height": 1024,
            "model": "sdxl" # Try "sdxl", "flux", or "sd15" if this fails
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }

        # Try the most common endpoint
        url = f"{BASE_URL}/generate"
        
        print(f"🚀 Sending request to: {url}")
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            result = response.json()
            
            # Extract image URL or Base64 from response
            # This depends on the API response structure
            if "url" in result:
                img_url = result["url"]
                print(f"✅ Success! Image URL: {img_url}")
                # Download image
                with open("generated_result.jpg", "wb") as f:
                    f.write(requests.get(img_url).content)
                print("💾 Image saved as generated_result.jpg")
            elif "image" in result:
                img_data = result["image"]
                with open("generated_result.jpg", "wb") as f:
                    f.write(base64.b64decode(img_data))
                print("✅ Success! Image saved as generated_result.jpg")
            else:
                print("⚠️ Success but unknown response structure:", result)
        else:
            print(f"❌ Error {response.status_code}: {response.text}")

    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    generate_image()
