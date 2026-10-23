import os
from pathlib import Path

# Load local development settings from .env when python-dotenv is installed.
# Existing process environment variables retain precedence over .env values.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ct200.db")
GENERATIONS_DIR = Path(os.getenv("GENERATIONS_DIR", "./generated"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock").lower()
