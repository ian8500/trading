from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    APP_ENV: str = "development"
    APP_NAME: str = "Trading Intelligence Platform"
    APP_TIMEZONE: str = "Europe/London"
    APP_BASE_CURRENCY: str = "GBP"
    DATABASE_URL: str = "sqlite:///./trading.sqlite3"
    BACKEND_PORT: int = 8000
    FRONTEND_PORT: int = 5173
    DASHBOARD_ADMIN_USERNAME: str = "admin"
    DASHBOARD_ADMIN_PASSWORD_HASH: str = ""
    IG_ENVIRONMENT: Literal["DEMO"] = "DEMO"
    IG_USERNAME: str = ""
    IG_PASSWORD: str = ""
    IG_API_KEY: str = ""
    IG_ACCOUNT_ID: str = ""
    AUTONOMOUS_DEMO_ENABLED: bool = False
    LIVE_EXECUTION_ENABLED: bool = False
    LIVE_BROKER_IMPLEMENTATION_ENABLED: bool = False
    INITIAL_MANAGED_CAPITAL_GBP: Decimal = Field(default=Decimal("500"), gt=0)
    TARGET_CAPITAL_GBP: Decimal = Field(default=Decimal("5000"), gt=0)
    OPENAI_API_KEY: str = ""
    AI_PROVIDER: Literal["disabled", "openai"] = "disabled"
    AI_MODEL: str = ""
    NEWS_PROVIDER: str = "disabled"
    MACRO_PROVIDER: str = "disabled"
    LOG_LEVEL: str = "INFO"

    @field_validator("IG_ENVIRONMENT")
    @classmethod
    def demo_only(cls, value: str) -> str:
        if value != "DEMO":
            raise ValueError("V1 permits IG Demo only")
        return value

    @field_validator("LIVE_EXECUTION_ENABLED", "LIVE_BROKER_IMPLEMENTATION_ENABLED")
    @classmethod
    def live_must_be_disabled(cls, value: bool) -> bool:
        if value:
            raise ValueError("Live execution is not implemented and cannot be enabled in V1")
        return value

    @property
    def ig_configured(self) -> bool:
        return all((self.IG_USERNAME, self.IG_PASSWORD, self.IG_API_KEY))


@lru_cache
def get_settings() -> Settings:
    return Settings()
