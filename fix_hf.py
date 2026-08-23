import os
from huggingface_hub import HfApi

token = "YOUR_HF_TOKEN_HERE"
api = HfApi(token=token)
username = api.whoami()["name"]
target_space = f"{username}/PixieDuster"

print("🔍 Scanning your Hugging Face account for running Spaces...")
spaces = api.list_spaces(author=username)

paused_count = 0
for space in spaces:
    if space.id != target_space:
        try:
            print(f"⏸️ Pausing {space.id} to free up quota...")
            api.pause_space(repo_id=space.id)
            paused_count += 1
            print(f"✅ Successfully paused {space.id}")
            break # We only need to pause one to free up cpu-basic
        except Exception as e:
            pass

print(f"🚀 Restarting {target_space}...")
try:
    api.restart_space(repo_id=target_space)
    print("✅ PixieDuster has been restarted!")
except Exception as e:
    print(f"⚠️ Could not restart: {e}")

