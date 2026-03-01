"""Application settings — loaded from environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Sumble API (v3) ---
    sumble_api_key: str = ""
    sumble_base_url: str = "https://api.sumble.com/v3"

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # --- Hunter.io (email enrichment) ---
    hunter_api_key: str = ""

    # --- SMTP ---
    smtp_host: str = "smtp.sendgrid.net"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    from_email: str = ""
    from_name: str = "Joel Horwitz"

    # --- Slack (optional) ---
    slack_webhook_url: str = ""

    # --- LinkedIn Sales Navigator ---
    linkedin_session_dir: str = "data/linkedin-session"
    linkedin_headless: bool = False
    linkedin_min_delay: float = 30.0
    linkedin_max_delay: float = 90.0
    linkedin_daily_limit: int = 25
    linkedin_outreach_type: str = "inmail"  # "inmail" or "connection"

    # --- Behaviour ---
    dry_run: bool = True
    max_emails_per_run: int = 20
    outreach_channel: str = "linkedin"  # "email", "linkedin", or "both"
    job_query: str = "Head of Growth"
    job_technologies: str = "google-ads,facebook-ads,performance-marketing"
    job_countries: str = "US"
    job_since_days: int = 30
    log_level: str = "INFO"

    # --- Database ---
    database_path: str = "data/outreach.db"
