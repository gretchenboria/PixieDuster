"""Push server/ to the PixieDuster Hugging Face Space.

    HF_TOKEN=hf_... .venv-cli/bin/python scripts/push_space.py [--dry-run]

Needs a token with *write* access to gretchenboria/PixieDuster.
The existing web app files are included in server/static/, so the public page
keeps working; the API is added alongside it at /api.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

REPO = "gretchenboria/PixieDuster"
ROOT = Path(__file__).resolve().parent.parent / "server"
UPLOAD = ["app.py", "Dockerfile", "requirements.txt", "README.md",
          "static/index.html", "static/style.css", "static/app.py", "static/logo.png"]


def main() -> int:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("No HF_TOKEN in the environment. Nothing was pushed.", file=sys.stderr)
        return 2

    missing = [f for f in UPLOAD if not (ROOT / f).is_file()]
    if missing:
        print(f"Missing files, refusing to push: {missing}", file=sys.stderr)
        return 1

    api = HfApi(token=token)
    who = api.whoami()
    print(f"authenticated as: {who['name']}")

    total = sum((ROOT / f).stat().st_size for f in UPLOAD)
    print(f"repo            : {REPO}")
    print(f"files           : {len(UPLOAD)}  ({total / 1024:.0f} KB)")
    for f in UPLOAD:
        print(f"  {f:24} {(ROOT / f).stat().st_size:>9,} bytes")

    if "--dry-run" in sys.argv:
        print("\n--dry-run: nothing uploaded.")
        return 0

    api.upload_folder(
        repo_id=REPO,
        repo_type="space",
        folder_path=str(ROOT),
        allow_patterns=UPLOAD,
        commit_message="Serve the stlite web app and add the metered API at /api",
    )
    print(f"\npushed. https://huggingface.co/spaces/{REPO}")
    print("Now set GEMINI_API_KEY as a *Secret* in the Space settings, and")
    print("enable persistent storage so /data survives restarts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
