import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory for proof-of-face
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file if present
dotenv_path = BASE_DIR / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
else:
    load_dotenv()

# Environment variables
BLUESKY_ACTOR = os.getenv("BLUESKY_ACTOR", "your-handle.bsky.social")
INPUT_FACE_PATH = os.getenv("INPUT_FACE_PATH", str(BASE_DIR / "assets" / "selfie.jpg"))
WEB3_PROVIDER_URI = os.getenv("WEB3_PROVIDER_URI", "https://rpc-amoy.polygon.technology/")
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "")
NETWORK = os.getenv("NETWORK", "local").lower()

def get_config():
    """Returns the current runtime configuration as a dictionary."""
    return {
        "BLUESKY_ACTOR": BLUESKY_ACTOR,
        "INPUT_FACE_PATH": INPUT_FACE_PATH,
        "WEB3_PROVIDER_URI": WEB3_PROVIDER_URI,
        "PRIVATE_KEY": "***" if PRIVATE_KEY else "",
        "CONTRACT_ADDRESS": CONTRACT_ADDRESS,
        "NETWORK": NETWORK,
    }

# Fallback local network defaults added

