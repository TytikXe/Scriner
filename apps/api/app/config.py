from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Crypto Screener API"
    api_base_path: str = "/api"
    database_url: str | None = None
    redis_url: str | None = None
    data_dir: str = "data"
    state_file: str = "data/state.json"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model_quick: str = "gpt-4o-mini"
    openai_model_deep: str = "gpt-4.1"
    ai_ttl_minutes: int = 15

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

