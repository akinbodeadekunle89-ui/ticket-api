from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str
    database_url: str
    webhook_url: str
    webhook_secret: str
    api_key_secret: str

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()