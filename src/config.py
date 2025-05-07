import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings # For Pydantic V2 settings management

load_dotenv() # Loads variables from .env into environment

class Settings(BaseSettings):
    WEATHERAPI_KEY: str | None = None
    DATABASE_URL: str = "sqlite:///./building_management.db"
    # Add other global configurations here if needed in the future
    # e.g., LOG_LEVEL: str = "INFO"

    # Pydantic settings configuration
    class Config:
        env_file = ".env" # Specifies .env file for Pydantic to load (complements load_dotenv)
        env_file_encoding = 'utf-8'
        extra = 'ignore' # Ignore extra fields from .env if any

settings = Settings()

# Optional: You can still have a warning if the key isn't loaded, 
# though Pydantic will also handle this if the type is just `str` (not `str | None`)
if settings.WEATHERAPI_KEY is None:
    print("Warning: WEATHERAPI_KEY was not loaded into settings. Check .env file and its content.")

# To verify what Pydantic loaded (optional, for debugging):
# print(f"Loaded settings: WEATHERAPI_KEY='{settings.WEATHERAPI_KEY}', DATABASE_URL='{settings.DATABASE_URL}')