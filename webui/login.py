from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from conf import LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script

from .storage import ACCOUNT_COOKIES_DIR, AccountStore


PLATFORM_URLS = {
    "doubao": "https://www.doubao.com/chat/",
    "dola": "https://www.dola.com/chat/",
}


@dataclass
class LoginSession:
    id: str
    name: str
    platform: str
    cookie_path: Path
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page


class LoginManager:
    """只负责打开扫码窗口，并在用户确认后保存 Cookie，不自动检测登录。"""

    def __init__(self, account_store: AccountStore) -> None:
        self.account_store = account_store
        self.sessions: dict[str, LoginSession] = {}

    async def start(self, name: str, platform: str = "doubao") -> dict[str, Any]:
        display_name = name.strip()
        if not display_name:
            raise ValueError("账号名称不能为空")
        platform = platform.strip().lower()
        if platform not in PLATFORM_URLS:
            raise ValueError("账号平台必须是豆包或 Dola")

        session_id = uuid.uuid4().hex
        # 保持现有账号池的唯一随机文件名，不使用 account1 之类的固定名称。
        cookie_path = (ACCOUNT_COOKIES_DIR / f"{session_id}.json").resolve()
        playwright = await async_playwright().start()
        try:
            launch_options: dict[str, Any] = {"headless": False}
            if LOCAL_CHROME_PATH:
                launch_options["executable_path"] = LOCAL_CHROME_PATH
            browser = await playwright.chromium.launch(**launch_options)
            context = await browser.new_context()
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto(PLATFORM_URLS[platform], timeout=60000)
        except Exception:
            await playwright.stop()
            raise

        self.sessions[session_id] = LoginSession(
            id=session_id,
            name=display_name,
            platform=platform,
            cookie_path=cookie_path,
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
        )
        return {
            "session_id": session_id,
            "name": display_name,
            "platform": platform,
        }

    async def save(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError("登录窗口不存在或已经关闭")
        try:
            session.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            await session.context.storage_state(path=str(session.cookie_path))
            account = self.account_store.create(
                name=session.name,
                cookie_path=session.cookie_path,
                enabled=True,
                managed_cookie=True,
                platform=session.platform,
            )
            return account
        finally:
            await self._close(session_id)

    async def cancel(self, session_id: str) -> None:
        if session_id not in self.sessions:
            raise KeyError("登录窗口不存在或已经关闭")
        await self._close(session_id)

    async def _close(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if not session:
            return
        try:
            await session.context.close()
        except Exception:
            pass
        try:
            await session.browser.close()
        except Exception:
            pass
        try:
            await session.playwright.stop()
        except Exception:
            pass

    async def close_all(self) -> None:
        for session_id in list(self.sessions):
            await self._close(session_id)
