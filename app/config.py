from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    # Twelve Data
    twelvedata_api_key: str

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    # Tracking
    pairs: List[str] = ["EUR/USD", "GBP/USD", "USD/JPY"]
    timeframes: List[str] = ["1min", "5min"]
    poll_seconds: int = 60

    # Database
    database_url: str = "sqlite:///./data/alerts.db"

    # Strategy
    strategy_version: int = 1

    @field_validator("pairs", "timeframes", mode="before")
    @classmethod
    def parse_csv(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",")]
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
