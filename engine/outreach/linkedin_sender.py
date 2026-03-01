"""LinkedIn Sales Navigator automation via Playwright.

Handles:
  - Session management (login once, reuse cookies)
  - InMail sending via Sales Navigator
  - Connection requests with personalized notes
  - Rate limiting and human-like delays
  - Daily send limits
  - Error screenshots for debugging

Usage:
  # First-time setup: opens browser for manual login
  python -m engine.outreach.linkedin_sender --setup

  # Then the pipeline uses the saved session automatically.

⚠️ LinkedIn automation is against LinkedIn's Terms of Service.
   Use at your own risk. Keep daily volumes low (<25/day).
"""

from __future__ import annotations

import logging
import random
import time
from datetime import date, datetime, timezone
from pathlib import Path

from engine.config import Settings

logger = logging.getLogger(__name__)

# --- Selector constants (update if LinkedIn changes their DOM) -----------

# Sales Navigator profile page
_SEL_SN_MESSAGE_BTN = (
    "button[data-anchor-id='message-button'],"
    "button.message-anywhere-button,"
    "button[aria-label*='Message']"
)

# InMail compose dialog
_SEL_INMAIL_SUBJECT = (
    "input[name='subject'],"
    "input[placeholder*='Subject'],"
    "input[aria-label*='Subject']"
)
_SEL_INMAIL_BODY = (
    "div[role='textbox'][aria-label*='message'],"
    "textarea[name='body'],"
    "div.msg-form__contenteditable,"
    "div[contenteditable='true'][aria-label*='Write a message']"
)
_SEL_INMAIL_SEND = (
    "button[aria-label='Send'],"
    "button.msg-form__send-button,"
    "button[type='submit']:has-text('Send')"
)

# Regular LinkedIn profile - connection request
_SEL_CONNECT_BTN = (
    "button[aria-label*='Connect'],"
    "button:has-text('Connect'):not([aria-label*='Disconnect'])"
)
_SEL_ADD_NOTE_BTN = (
    "button[aria-label*='Add a note'],"
    "button:has-text('Add a note')"
)
_SEL_NOTE_TEXTAREA = (
    "textarea[name='message'],"
    "textarea#custom-message,"
    "textarea[placeholder*='personal note']"
)
_SEL_SEND_NOTE_BTN = (
    "button[aria-label*='Send'],"
    "button:has-text('Send')"
)

# Close modal / dismiss
_SEL_CLOSE_MODAL = (
    "button[aria-label='Dismiss'],"
    "button[aria-label='Close'],"
    "button.artdeco-modal__dismiss"
)


class LinkedInAutomation:
    """Browser-based LinkedIn Sales Navigator outreach."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session_dir = Path(settings.linkedin_session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._sends_today = 0
        self._today = date.today()
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def setup_session(self) -> None:
        """Open a headed browser for manual LinkedIn login.

        The user logs in manually, and the browser state (cookies, local
        storage) is saved to disk. Subsequent runs reuse this session.
        """
        from playwright.sync_api import sync_playwright

        logger.info("Opening browser for LinkedIn login...")
        logger.info("Log in to LinkedIn (and Sales Navigator if applicable).")
        logger.info("Close the browser when done — session will be saved.")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                storage_state=self._state_path() if self._state_path().exists() else None,
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto("https://www.linkedin.com/login")

            # Wait for the user to log in and close the browser
            try:
                page.wait_for_event("close", timeout=300_000)  # 5 min
            except Exception:
                pass

            # Save session state
            context.storage_state(path=str(self._state_path()))
            context.close()
            browser.close()

        logger.info(f"Session saved to {self._state_path()}")

    def _start_browser(self) -> None:
        """Launch browser with saved session state."""
        from playwright.sync_api import sync_playwright

        if not self._state_path().exists():
            raise RuntimeError(
                "No LinkedIn session found. Run setup first:\n"
                "  python -m engine.outreach.linkedin_sender --setup"
            )

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.settings.linkedin_headless
        )
        self._context = self._browser.new_context(
            storage_state=str(self._state_path()),
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self._page = self._context.new_page()
        logger.info("Browser started with saved LinkedIn session.")

    def close(self) -> None:
        """Save state and close browser."""
        if self._context:
            try:
                self._context.storage_state(path=str(self._state_path()))
            except Exception:
                pass
            self._context.close()
        if self._browser:
            self._browser.close()
        if hasattr(self, "_playwright") and self._playwright:
            self._playwright.stop()
        logger.info("Browser closed, session saved.")

    def _state_path(self) -> Path:
        return self.session_dir / "state.json"

    # ------------------------------------------------------------------
    # Daily limit tracking
    # ------------------------------------------------------------------

    def _check_daily_limit(self) -> bool:
        """Returns True if we're under the daily limit."""
        today = date.today()
        if today != self._today:
            self._sends_today = 0
            self._today = today
        return self._sends_today < self.settings.linkedin_daily_limit

    def _record_send(self) -> None:
        self._sends_today += 1

    # ------------------------------------------------------------------
    # Human-like delays
    # ------------------------------------------------------------------

    def _human_delay(self, multiplier: float = 1.0) -> None:
        """Sleep for a random human-like interval."""
        base = random.uniform(
            self.settings.linkedin_min_delay,
            self.settings.linkedin_max_delay,
        )
        delay = base * multiplier
        logger.debug(f"Sleeping {delay:.1f}s (human delay)")
        time.sleep(delay)

    def _typing_delay(self, text: str) -> None:
        """Simulate human typing speed (~150ms per char with variance)."""
        for char in text:
            self._page.keyboard.type(char, delay=random.randint(50, 200))
            if random.random() < 0.05:  # 5% chance of micro-pause
                time.sleep(random.uniform(0.3, 0.8))

    # ------------------------------------------------------------------
    # InMail (Sales Navigator)
    # ------------------------------------------------------------------

    def send_inmail(
        self,
        linkedin_url: str,
        subject: str,
        body: str,
    ) -> tuple[bool, str]:
        """Send an InMail via Sales Navigator.

        Args:
            linkedin_url: Target's LinkedIn profile URL.
            subject:      InMail subject line.
            body:         InMail message body.

        Returns:
            Tuple of (success: bool, error_or_info: str).
        """
        if not self._check_daily_limit():
            return False, f"Daily limit reached ({self.settings.linkedin_daily_limit})"

        if not self._page:
            self._start_browser()

        page = self._page
        sn_url = self._to_sales_nav_url(linkedin_url)

        try:
            # Navigate to Sales Nav profile
            logger.info(f"Navigating to {sn_url}")
            page.goto(sn_url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(random.uniform(2, 4))

            # Check for login redirect
            if "login" in page.url.lower() or "checkpoint" in page.url.lower():
                self._screenshot("login_required")
                return False, "Session expired — re-run setup"

            # Click "Message" button
            msg_btn = page.locator(_SEL_SN_MESSAGE_BTN).first
            msg_btn.wait_for(state="visible", timeout=10_000)
            time.sleep(random.uniform(0.5, 1.5))
            msg_btn.click()
            time.sleep(random.uniform(1.5, 3))

            # Fill subject
            subject_input = page.locator(_SEL_INMAIL_SUBJECT).first
            subject_input.wait_for(state="visible", timeout=8_000)
            subject_input.click()
            self._typing_delay(subject)

            time.sleep(random.uniform(0.5, 1))

            # Fill body
            body_input = page.locator(_SEL_INMAIL_BODY).first
            body_input.wait_for(state="visible", timeout=8_000)
            body_input.click()
            self._typing_delay(body)

            time.sleep(random.uniform(1, 2))

            # Click Send
            send_btn = page.locator(_SEL_INMAIL_SEND).first
            send_btn.wait_for(state="visible", timeout=5_000)
            send_btn.click()

            time.sleep(random.uniform(2, 4))

            self._record_send()
            logger.info(f"InMail sent to {linkedin_url} | Subject: {subject}")
            return True, "InMail sent"

        except Exception as exc:
            self._screenshot("inmail_error")
            error_msg = f"InMail failed: {exc}"
            logger.error(error_msg)
            return False, error_msg

    # ------------------------------------------------------------------
    # Connection request
    # ------------------------------------------------------------------

    def send_connection_request(
        self,
        linkedin_url: str,
        note: str,
    ) -> tuple[bool, str]:
        """Send a connection request with a personalized note.

        Args:
            linkedin_url: Target's LinkedIn profile URL.
            note:         Connection note (max 300 chars).

        Returns:
            Tuple of (success: bool, error_or_info: str).
        """
        if not self._check_daily_limit():
            return False, f"Daily limit reached ({self.settings.linkedin_daily_limit})"

        if not self._page:
            self._start_browser()

        page = self._page
        note = note[:300]  # enforce limit

        try:
            logger.info(f"Navigating to {linkedin_url}")
            page.goto(linkedin_url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(random.uniform(2, 4))

            if "login" in page.url.lower() or "checkpoint" in page.url.lower():
                self._screenshot("login_required")
                return False, "Session expired — re-run setup"

            # Click "Connect"
            connect_btn = page.locator(_SEL_CONNECT_BTN).first
            connect_btn.wait_for(state="visible", timeout=10_000)
            time.sleep(random.uniform(0.5, 1.5))
            connect_btn.click()
            time.sleep(random.uniform(1, 2))

            # Click "Add a note"
            add_note_btn = page.locator(_SEL_ADD_NOTE_BTN).first
            add_note_btn.wait_for(state="visible", timeout=5_000)
            add_note_btn.click()
            time.sleep(random.uniform(0.5, 1))

            # Type the note
            note_textarea = page.locator(_SEL_NOTE_TEXTAREA).first
            note_textarea.wait_for(state="visible", timeout=5_000)
            note_textarea.click()
            self._typing_delay(note)

            time.sleep(random.uniform(0.5, 1))

            # Click Send
            send_btn = page.locator(_SEL_SEND_NOTE_BTN).first
            send_btn.click()

            time.sleep(random.uniform(2, 4))

            self._record_send()
            logger.info(f"Connection request sent to {linkedin_url}")
            return True, "Connection request sent"

        except Exception as exc:
            self._screenshot("connection_error")
            error_msg = f"Connection request failed: {exc}"
            logger.error(error_msg)
            # Try to close any open modal
            try:
                page.locator(_SEL_CLOSE_MODAL).first.click(timeout=2_000)
            except Exception:
                pass
            return False, error_msg

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_sales_nav_url(self, linkedin_url: str) -> str:
        """Convert a regular LinkedIn profile URL to Sales Navigator URL.

        linkedin.com/in/username → linkedin.com/sales/people/username
        """
        url = linkedin_url.rstrip("/")

        # Already a Sales Nav URL
        if "/sales/" in url:
            return url

        # Extract the profile identifier
        if "/in/" in url:
            slug = url.split("/in/")[-1].split("?")[0].split("/")[0]
            return f"https://www.linkedin.com/sales/people/{slug}"

        # Fallback: use as-is
        return url

    def _screenshot(self, name: str) -> None:
        """Save a debug screenshot."""
        if not self._page:
            return
        screenshots_dir = self.session_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = screenshots_dir / f"{name}_{ts}.png"
        try:
            self._page.screenshot(path=str(path))
            logger.info(f"Screenshot saved: {path}")
        except Exception:
            pass


# ------------------------------------------------------------------
# CLI entry point for session setup
# ------------------------------------------------------------------

def main() -> None:
    """CLI for LinkedIn session setup."""
    import argparse

    parser = argparse.ArgumentParser(description="LinkedIn Sales Navigator Setup")
    parser.add_argument(
        "--setup", action="store_true",
        help="Open browser for LinkedIn login (saves session for automation)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    settings = Settings()
    automation = LinkedInAutomation(settings)

    if args.setup:
        automation.setup_session()
    else:
        print("Usage: python -m engine.outreach.linkedin_sender --setup")


if __name__ == "__main__":
    main()
