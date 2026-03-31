from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://infoke:infoke@localhost:5432/infoke"
    redis_url: str = "redis://localhost:6379/0"
    crawl_interval_hours: int = 24
    min_preparation_days: int = 7
    max_claude_calls_per_contest: int = 5
    roi_threshold: float = 3.0

    model_config = {"env_file": ".env", "env_prefix": "INFOKE_"}


settings = Settings()
