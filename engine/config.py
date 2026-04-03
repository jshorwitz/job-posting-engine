"""Application settings — loaded from environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Sumble API (v3) ---
    sumble_api_key: str = ""
    sumble_base_url: str = "https://api.sumble.com/v5"

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # --- Hunter.io (email enrichment) ---
    hunter_api_key: str = ""

    # --- Apollo.io (contact enrichment + job change signals) ---
    apollo_api_key: str = ""

    # --- Loops.so (email sending) ---
    loops_api_key: str = ""
    loops_transactional_id: str = ""  # deprecated — kept for backwards compat
    loops_mailing_list_id: str = ""

    # --- Sender identity (used in AI-generated messages) ---
    sender_name: str = ""
    company_name: str = ""
    company_pitch: str = ""

    # --- SMTP (fallback — used only if Loops not configured) ---
    smtp_host: str = "smtp.sendgrid.net"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    from_email: str = ""
    from_name: str = ""

    # --- Slack (optional) ---
    slack_webhook_url: str = ""
    slack_leads_webhook_url: str = ""  # Doppler uses this name

    @property
    def effective_slack_webhook(self) -> str:
        """Use SLACK_LEADS_WEBHOOK_URL from Doppler, fall back to SLACK_WEBHOOK_URL."""
        return self.slack_leads_webhook_url or self.slack_webhook_url

    # --- LinkedIn Sales Navigator ---
    linkedin_session_dir: str = "data/linkedin-session"
    linkedin_headless: bool = False
    linkedin_min_delay: float = 30.0
    linkedin_max_delay: float = 90.0
    linkedin_daily_limit: int = 25
    linkedin_outreach_type: str = "inmail"  # "inmail" or "connection"

    # --- SpyFu (competitive PPC/SEO intelligence) ---
    spyfu_api_id: str = ""
    spyfu_secret_key: str = ""
    spyfu_enrich_after_days: int = 1  # enrich contacts N days after initial send

    # --- BuiltWith (tech stack / ad pixel detection) ---
    builtwith_api_key: str = ""

    # --- Firecrawl (homepage scraping for headline extraction) ---
    firecrawl_api_key: str = ""

    # --- Follow-up CTA ---
    calendly_url: str = ""  # e.g. https://calendly.com/yourname/15min

    # --- Behaviour ---
    dry_run: bool = True
    max_emails_per_run: int = 20
    outreach_channel: str = "linkedin"  # "email", "linkedin", or "both"
    job_query: str = "Head of Growth"
    job_technologies: str = "google-ads,facebook-ads,performance-marketing"
    job_countries: str = "US"
    job_since_days: int = 30
    log_level: str = "INFO"

    # --- X (Twitter) Growth Engine ---
    joel_x_consumer_key: str = ""
    joel_x_consumer_secret: str = ""
    joel_x_access_token: str = ""
    joel_x_access_token_secret: str = ""
    x_api_bearer_token: str = ""
    x_content_poster_enabled: bool = True
    x_engagement_scanner_enabled: bool = True
    x_linkedin_crosspost_enabled: bool = True
    x_mcp_reply_scanner_enabled: bool = True
    x_mcp_reply_max_per_run: int = 5

    # --- LinkedIn Org Posting (cross-post from X) ---
    linkedin_access_token: str = ""
    linkedin_refresh_token: str = ""
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_org_urn: str = "urn:li:organization:4803356"

    # --- LinkedIn Native Content Engine ---
    linkedin_content_poster_enabled: bool = True

    # --- Google Gemini / Imagen ---
    gemini_api_key: str = ""

    # --- Adzuna (job search aggregator — fallback/alternative to Sumble) ---
    adzuna_app_id: str = ""
    adzuna_api_key: str = ""

    # --- Resend (transactional email) ---
    resend_api_key: str = ""
    resend_from_email: str = "joel@syntermedia.ai"

    # --- Listicle Discovery ---
    serper_api_key: str = ""
    google_cse_api_key: str = ""
    google_cse_id: str = ""

    # --- Synter MCP (SimilarWeb domain analysis) ---
    synter_api_key: str = ""
    synter_enrich_enabled: bool = True

    # --- Smartlead.ai (cold email sending) ---
    smartlead_api_key: str = ""
    smartlead_campaign_id: str = ""
    smartlead_listicle_campaign_id: str = ""  # separate campaign for listicle/podcast outreach

    # --- EmailBison (isolated cold email sequencing) ---
    emailbison_api_key: str = ""
    emailbison_base_url: str = "https://dedi.emailbison.com"
    emailbison_campaign_id: str = ""  # default campaign
    emailbison_listicle_campaign_id: str = ""  # listicle/podcast outreach campaign

    # --- RB2B.com (website visitor identification) ---
    rb2b_api_key: str = ""
    rb2b_webhook_secret: str = ""  # for verifying webhook signatures
    rb2b_auto_enrich: bool = True  # auto-enrich + outreach on visitor detection
    rb2b_poll_days: int = 7  # days of visitor history to fetch when polling

    # --- Database ---
    database_path: str = "data/outreach.db"
