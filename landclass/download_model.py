"""Download GLiNER2.5-Decide into models/ so later runs work offline.

  python -m landclass.download_model
"""
from huggingface_hub import snapshot_download

from .config import LOCAL_MODEL_DIR, MODEL_HUB_ID


def download() -> None:
    if (LOCAL_MODEL_DIR / "config.json").exists():
        print(f"Model already in {LOCAL_MODEL_DIR}")
        return
    print(f"Downloading {MODEL_HUB_ID} to {LOCAL_MODEL_DIR} (about 2 GB)…")
    snapshot_download(MODEL_HUB_ID, local_dir=LOCAL_MODEL_DIR)
    print("Done.")


if __name__ == "__main__":
    download()
