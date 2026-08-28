import os
import shutil
from huggingface_hub import HfApi
from dotenv import load_dotenv

def deploy():
    load_dotenv()
    token = os.environ.get("HF_TOKEN")
    
    api = HfApi(token=token) if token else HfApi()
    
    # Get username
    try:
        username = api.whoami()["name"]
    except Exception as e:
        print("Please log in with `huggingface-cli login` or set HF_TOKEN in your environment.")
        return
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
    readme_content = """---
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
    # Create a staging directory to avoid messing up the repo root
    staging_dir = "/Users/dr.gretchenboria/PersonaPromptGenerator/hf_staging"
    os.makedirs(staging_dir, exist_ok=True)
    
    with open(f"{staging_dir}/README.md", "w") as f:
        f.write(readme_content)
        
    shutil.copy("web/app.py", f"{staging_dir}/app.py")
    shutil.copy("web/index.html", f"{staging_dir}/index.html")
    shutil.copy("logo.png", f"{staging_dir}/logo.png")
    
    print("📁 Uploading files from staging (app.py, logo.png, index.html, README.md)...")
    # Upload folder contents
    api.upload_folder(
        folder_path=staging_dir,
        repo_id=repo_id,
        repo_type="space"
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
    
    # Cleanup
    shutil.rmtree(staging_dir)

if __name__ == "__main__":
    deploy()
