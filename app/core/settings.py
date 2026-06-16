
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "fingurdain123"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:29092"

    # Security — API Keys (comma-separated list of valid keys)
    # In production, set FG_API_KEYS in environment variables
    FG_API_KEYS: str = "dev-key-local-only"

    # Security — Allowed CORS Origins
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://localhost:3000"

    # AI Agent — OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Rate limiting
    RATE_LIMIT_EVALUATE: str = "100/minute"
    RATE_LIMIT_GLOBAL: str = "300/minute"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

    @property
    def api_keys_list(self) -> List[str]:
        """Parse comma-separated API keys into a list."""
        return [k.strip() for k in self.FG_API_KEYS.split(",") if k.strip()]

    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse comma-separated origins into a list."""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


settings = Settings()