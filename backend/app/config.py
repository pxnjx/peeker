"""Runtime configuration, all values overridable via environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PEEKER_", env_file=".env", extra="ignore")

    # --- core ---
    app_name: str = "Peeker"
    debug: bool = False
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"

    # --- auth ---
    # The dashboard signs its session cookie in frontend/lib/session.ts with
    # PEEKER_SESSION_SECRET; app/auth.py re-verifies that same HMAC here, so the two
    # values must match. dashboard_password is NOT a fallback signing key: the frontend
    # never signs with it, so honouring it here would accept cookies the app cannot
    # mint. (Set both to the same value for a legacy install, but the secret is the key.)
    session_secret: str | None = None
    dashboard_password: str | None = None
    session_cookie_name: str = "peeker_session"

    # --- db ---
    database_url: str = "sqlite+aiosqlite:///./data/peeker.db"
    db_echo: bool = False

    # --- crawler / anti-detect ---
    crawler_channel: str = "chrome"  # "chrome" (real browser) | "chromium" (playwright bundled)
    crawler_executable_path: str | None = None  # explicit browser path fallback
    crawler_headless: bool = True
    crawler_proxy_url: str | None = None
    crawler_max_reviews: int = 100  # cap per scrape; Google review counts here run 20-90
    crawler_new_headless: bool = True  # Chrome "--headless=new": legacy headless gets a reduced
    # Maps page (no Ulasan/Reviews tab), which capped every scrape at the ~6 inline preview cards.
    crawler_timeout_ms: int = 30_000
    crawler_navigation_timeout_ms: int = 25_000
    crawler_viewport_min_width: int = 1366
    crawler_viewport_max_width: int = 1920
    crawler_locale: str = "en-US"
    crawler_timezone: str = "Asia/Jakarta"
    # Keep off by default: aborting image/font/media requests prevents Google Maps
    # from ever hydrating the review feed (observed: 0 review nodes forever).
    # It is also fingerprintable via Resource Timing, so real browsers load them.
    crawler_block_images: bool = False

    # --- worker pool ---
    worker_concurrency: int = 3
    min_navigation_interval_s: float = 60.0
    block_backoff_minutes: list[int] = [5, 15, 60]
    max_consecutive_blocks: int = 3  # park business for 1h after this many blocked streaks
    park_minutes: int = 60

    # --- scheduler ---
    default_interval_min_own: int = 60
    default_interval_min_competitor: int = 240
    schedule_jitter_pct: float = 0.2

    # --- alerts ---
    alert_rating_drop_urgent_delta: float = 0.3
    alert_rating_drop_urgent_window_h: int = 24
    alert_rating_drop_delta: float = 0.1
    alert_rating_drop_window_h: int = 24 * 7
    alert_review_burst_count: int = 5
    alert_review_burst_window_h: int = 24
    alert_dedupe_window_h: int = 24

    # --- misc ---
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
