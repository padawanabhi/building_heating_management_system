import os
from dotenv import load_dotenv

load_dotenv()

WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./building_management.db")

if not WEATHERAPI_KEY:
    print("Warning: WEATHERAPI_KEY not found in .env file or environment variables.") 