# -*- coding: utf-8 -*-
from datetime import datetime
import time
from playwright.async_api import Playwright, async_playwright, Page
import os
import asyncio

from conf import LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import douyin_logger


class doubao(object):
    def __init__(self, account_file, qingxi = False):
        self.account_file = account_file
        self.local_executable_path = LOCAL_CHROME_PATH
        self.qingxi = qingxi  # 是否开启清晰化功能

    async def download_image(self, page, n, savefolder, theme):
        async with page.expect_download() as download2_info:
            if n == 1:
                pic = page.get_by_role("img", name="image").first
            else:
                pic = page.get_by_role("img", name="image").nth(n - 1)

            # await pic.wait_for(state="enabled", timeout=10000)
            await pic.click()

            await page.wait_for_load_state('load')


            if self.qingxi:
                await page.get_by_text("变清晰").click()
                await page.wait_for_timeout(8000)
            await page.get_by_text("下载原图").click()
        download2 = await download2_info.value
        await download2.save_as(savefolder + '/' +  str(n) + '_' + theme + '_' + str(time.time())[:10] + '_' + download2.suggested_filename)
        await page.get_by_test_id("edit_image_close_button").click()


    async def upload(self, playwright: Playwright, dld_n, text, savefolder, theme, headless) -> None:
        # 使用 Chromium 浏览器启动一个浏览器实例
        if self.local_executable_path:
            browser = await playwright.chromium.launch(headless=headless, executable_path=self.local_executable_path)
        else:
            browser = await playwright.chromium.launch(headless=headless)
        # 创建一个浏览器上下文，使用指定的 cookie 文件
        context = await browser.new_context(storage_state=f"{self.account_file}")
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        site = "https://www.doubao.com/chat/?from_login=1"
        await page.goto(site)

        # 点击输入框，输入文字
        await asyncio.sleep(2)

        await page.locator(".container-kxxSU4").click()
        await asyncio.sleep(5)
        await page.get_by_test_id("chat_input_input").fill(text)
        await asyncio.sleep(2)

        # 点击发送按钮
        await page.get_by_test_id("chat_input_send_button").click()
        
        # 等待生成结果
        # await page.wait_for_load_state('networkidle', timeout = 60000)
        await asyncio.sleep(15)

        # 下载图片
        for i in range(dld_n):
            await self.download_image(page, i + 1, savefolder, theme)
            await asyncio.sleep(1)


        await context.close()
        await browser.close()


    async def upload_with_files(self, playwright: Playwright, dld_n, text, savefolder, theme, file_path) -> None:
        # 使用 Chromium 浏览器启动一个浏览器实例
        if self.local_executable_path:
            browser = await playwright.chromium.launch(headless=False, executable_path=self.local_executable_path)
        else:
            browser = await playwright.chromium.launch(headless=False)
        # 创建一个浏览器上下文，使用指定的 cookie 文件
        context = await browser.new_context(storage_state=f"{self.account_file}")
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        # site = "https://www.doubao.com/chat/?from_login=1"
        site = "https://www.doubao.com/chat/"

        await page.goto(site)

        # 点击 "图像生成" 按钮
        await page.get_by_test_id("skill_bar_button_3").click()
        await page.wait_for_timeout(2000)

        image_files = []
        for ext in ["*.jpeg", "*.jpg", "*.png", "*.gif", "*.webp"]:
            image_files.extend(file_path.glob(ext))

        async with page.expect_file_chooser() as fc_info:
            await page.get_by_text("参考图").click()  # 触发文件对话框的按钮
        file_chooser = await fc_info.value
        await file_chooser.set_files(image_files)
        await page.wait_for_timeout(1000)


        # 点击输入框，输入文字
        await page.get_by_test_id("chat_input_input").fill(text)
        await page.wait_for_timeout(1000)


        # 点击发送按钮
        await page.get_by_test_id("chat_input_send_button").click()
        
        # 等待生成结果
        await page.wait_for_load_state('networkidle', timeout = 60000)
        await page.wait_for_timeout(20000)




        # 下载图片
        for i in range(dld_n):
            await self.download_image(page, i + 1, savefolder, theme)
            await page.wait_for_timeout(1000)

        await context.storage_state(path=self.account_file)
        await context.close()
        await browser.close()


    async def main(self, dld_n, text, savefolder, theme, headless = False):
        async with async_playwright() as playwright:
            await self.upload(playwright, dld_n, text, savefolder, theme, headless)

    async def main_with_files(self, dld_n, text, savefolder, theme, file_path):
        async with async_playwright() as playwright:
            await self.upload_with_files(playwright, dld_n, text, savefolder, theme, file_path)

if __name__ == '__main__':
    account_file = Path("cookies" / "doubao" / "account.json")
    app = doubao(account_file)
 
    asyncio.run(app.main(dld_n, text, savefolder, theme, headless = doubao_headless), debug=False)
