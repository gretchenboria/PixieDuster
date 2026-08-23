import os
from huggingface_hub import HfApi
from dotenv import load_dotenv

def deploy():
    token = "YOUR_HF_TOKEN_HERE"
    api = HfApi(token=token)
    
    # Get username
    username = api.whoami()["name"]
    repo_id = f"{username}/PixieDuster"
    
    print(f"🚀 Preparing to deploy to Space: {repo_id}")
    
    # Create the Space
    api.create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="static",
        exist_ok=True,
        private=False
    )
    
    print("📝 Generating Space configuration (README.md)...")
    readme_content = f"""---
title: PixieDuster
emoji: ✨
colorFrom: yellow
colorTo: purple
sdk: static
pinned: false
---
# PixieDuster - AI Persona Cloning
Upload your writing samples and clone your persona!
"""
    with open("/Users/dr.gretchenboria/PersonaPromptGenerator/README.md", "w") as f:
        f.write(readme_content)
    
    print("📁 Uploading files (app.py, logo.png, index.html, README.md)...")
    # Upload folder contents
    api.upload_folder(
        folder_path="/Users/dr.gretchenboria/PersonaPromptGenerator",
        repo_id=repo_id,
        repo_type="space",
        allow_patterns=["app.py", "logo.png", "index.html", "README.md"]
    )
    
    print("🔐 Setting up secure secrets...")
    # Add Gemini API key as a secret
    load_dotenv("/Users/dr.gretchenboria/PersonaPromptGenerator/.env")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if gemini_key:
        api.add_space_secret(
            repo_id=repo_id,
            key="GEMINI_API_KEY",
            value=gemini_key
        )
        print("✅ Gemini API Key securely injected!")
    else:
        print("⚠️ Warning: GEMINI_API_KEY not found in .env")

    print(f"\n🎉 Deployment Complete! Your app is live at:")
    print(f"👉 https://huggingface.co/spaces/{repo_id}")

if __name__ == "__main__":
    deploy()
