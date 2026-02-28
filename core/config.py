from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # Azure Speech (TTS)
    azure_speech_key: str
    azure_speech_region: str = "westeurope"

    # HuggingFace
    huggingface_api_key: str

    # App
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"


settings = Settings()
