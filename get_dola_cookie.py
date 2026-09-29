import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from conf import BASE_DIR, LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script


async def dola_cookie_gen(account_file: Path) -> None:
    """打开 Dola 登录页，并在用户确认后保存独立的登录状态。"""
    account_file.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        launch_options = {"headless": False}
        if LOCAL_CHROME_PATH:
            launch_options["executable_path"] = LOCAL_CHROME_PATH

        browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context()
        context = await set_init_script(context)
        try:
            page = await context.new_page()
            await page.goto("https://www.dola.com/chat/", timeout=600000)
            print("请在 Dola 页面完成登录，然后在 Playwright 调试窗口点击继续。")
            await page.pause()
            await context.storage_state(path=str(account_file))
            print(f"Dola 登录状态已保存到: {account_file}")
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    account_file = Path(BASE_DIR / "cookies" / "dola" / "account1.json")
    asyncio.run(dola_cookie_gen(account_file))
