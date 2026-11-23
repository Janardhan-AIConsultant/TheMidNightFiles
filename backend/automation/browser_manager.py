"""Browser abstraction over Playwright with persistent, git-ignored profiles.

Login and MFA are always done by a human (``manual_login``). Automation never solves
CAPTCHA/MFA; publishers raise AutomationBlocked and the job stops.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_profile_root() -> Path:
    env = os.environ.get("BROWSER_PROFILE_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "MidnightFiles" / "browser_profiles"


class BrowserManagerError(RuntimeError):
    pass


class BrowserManager:
    """``launcher(profile_dir, headless)`` returns a context exposing ``.new_page()`` and ``.close()``.

    Tests inject a fake launcher; the default uses Playwright's persistent context.
    """

    def __init__(self, profile_root: Optional[Path] = None, headless: bool = False,
                 launcher: Optional[Callable[[Path, bool], Any]] = None):
        self.profile_root = Path(profile_root) if profile_root else default_profile_root()
        self._assert_outside_source_control(self.profile_root)
        self.headless = headless
        self._launcher = launcher or self._playwright_launcher

    @staticmethod
    def _assert_outside_source_control(path: Path) -> None:
        resolved = path.resolve()
        if PROJECT_ROOT in resolved.parents or resolved == PROJECT_ROOT:
            tmp = Path(os.environ.get("TEMP", "")).resolve() if os.environ.get("TEMP") else None
            if not (tmp and tmp in resolved.parents):
                raise BrowserManagerError(f"browser profile dir must be outside the repository: {resolved}")

    def profile_dir(self, platform: str) -> Path:
        if not platform.isalnum():
            raise BrowserManagerError("invalid platform name")
        d = self.profile_root / platform
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _playwright_launcher(profile_dir: Path, headless: bool):
        from playwright.sync_api import sync_playwright  # lazy: only real runs need it

        pw = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(str(profile_dir), headless=headless)
        original_close = ctx.close

        def _close():
            try:
                original_close()
            finally:
                pw.stop()

        ctx.close = _close  # type: ignore[method-assign]
        return ctx

    @contextmanager
    def session(self, platform: str) -> Iterator[Any]:
        """Yield a page using the platform's persistent profile (cookies from a manual login)."""
        ctx = self._launcher(self.profile_dir(platform), self.headless)
        try:
            yield ctx.new_page()
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    def manual_login(self, platform: str, login_url: str) -> None:
        """Open a HEADED browser so a human can log in (incl. MFA), then close it to save the session."""
        ctx = self._launcher(self.profile_dir(platform), False)
        page = ctx.new_page()
        page.goto(login_url)
        input(f"Log in to {platform} in the opened browser (complete any MFA), then press Enter here...")
        ctx.close()
