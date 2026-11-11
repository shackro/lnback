from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./repo_fier.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,https://apluinvet.vercel.app"
    secret_key: str = ""
    admin_token_expire_minutes: int = Field(default=1440, ge=1)
    portfolio_admin_emails: str = ""
    cron_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def authorized_portfolio_admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.portfolio_admin_emails.split(",")
            if email.strip()
        }


settings = Settings()
