"""环境配置。密钥只经 .env 注入（已 gitignore），字段见 .env.example。"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    database_url: str = os.getenv("DATABASE_URL", "")
    wecom_webhook_url: str = os.getenv("WECOM_WEBHOOK_URL", "")
    livekit_url: str = os.getenv("LIVEKIT_URL", "")
    livekit_api_key: str = os.getenv("LIVEKIT_API_KEY", "")
    livekit_api_secret: str = os.getenv("LIVEKIT_API_SECRET", "")
    stt_provider: str = os.getenv("STT_PROVIDER", "")
    stt_api_key: str = os.getenv("STT_API_KEY", "")
    tts_provider: str = os.getenv("TTS_PROVIDER", "")
    tts_api_key: str = os.getenv("TTS_API_KEY", "")


settings = Settings()
