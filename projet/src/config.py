import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    DUNE_API_KEY = os.getenv("DUNE_API_KEY", "")
    CACHE_DIR = Path(os.getenv("CACHE_DIR", "./data/cache"))
    
    # Ensure cache directory exists
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

config = Config()
