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
    stt_provider: str = os.getenv("STT_PROVIDER", "")
    stt_api_key: str = os.getenv("STT_API_KEY", "")
    tts_provider: str = os.getenv("TTS_PROVIDER", "")
    tts_api_key: str = os.getenv("TTS_API_KEY", "")
    # Admin Console 认证（访客含 PII，必须设密码）
    admin_user: str = os.getenv("ADMIN_USER", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    # Vapi 回调密钥（URL 内嵌，保护公网暴露的 /vapi 端点）
    vapi_server_secret: str = os.getenv("VAPI_SERVER_SECRET", "")
    # Vapi 管理 API key（查当前绑定的来电号码等；只在服务端用）
    vapi_api_key: str = os.getenv("VAPI_API_KEY", "")


settings = Settings()
