# -*- coding: utf-8 -*-
# 导入datetime模块，用于处理日期时间
from datetime import datetime
from tkinter import Tk, messagebox
# 导入playwright的异步API相关组件，用于浏览器自动化操作
import playwright
from playwright.async_api import Playwright, async_playwright, Page
# 导入os模块，用于文件路径操作
import os
# 导入asyncio模块，用于异步编程
import asyncio

# 从配置文件导入本地Chrome浏览器路径
from conf import LOCAL_CHROME_PATH
# 导入设置初始化脚本的工具函数
from utils.base_social_media import set_init_script
# 导入抖音日志工具
from utils.log import douyin_logger
from pathlib import Path

async def cookie_auth(account_file):
    """
    验证cookie文件是否有效
    :param account_file: cookie文件路径
    :return: 布尔值，True表示cookie有效，False表示无效
    """
    # 启动playwright上下文
    async with async_playwright() as playwright:
        # 启动无头模式的Chromium浏览器（无头模式即无界面运行）
        browser = await playwright.chromium.launch(headless=True)
        # browser = await playwright.chromium.launch(headless=False)

        # 使用指定的cookie文件创建浏览器上下文
        context = await browser.new_context(storage_state=account_file)
        # 设置初始化脚本（可能是一些浏览器环境配置）
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问抖音创作者中心的内容上传页面
        await page.goto("https://creator.douyin.com/creator-micro/content/upload")
        try:
            # 等待页面跳转至上传页面，超时时间5秒
            await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload", timeout=5000)
        except:
            # 超时说明cookie可能失效
            douyin_logger.info("[+] 等待5秒 cookie 失效")
            # 关闭上下文和浏览器
            await context.close()
            await browser.close()
            return False
        # 2024.06.17 抖音创作者中心改版 - 检查是否出现登录相关按钮
        if await page.get_by_text('手机号登录').count() or await page.get_by_text('扫码登录').count():
            douyin_logger.info("[+] 等待5秒 cookie 失效")
            return False
        else:
            douyin_logger.info("[+] cookie 有效")
            return True


async def douyin_setup(account_file, handle=False):
    """
    抖音初始化设置，检查cookie有效性，无效则生成新cookie
    :param account_file: cookie文件路径
    :param handle: 是否自动处理cookie失效（True则自动打开浏览器让用户登录）
    :return: 布尔值，True表示设置成功，False表示失败
    """
    # 检查cookie文件是否存在或是否有效
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            # Todo: 这里应该添加提示信息，暂时返回False
            return False
        # 日志记录：cookie无效，将打开浏览器让用户登录
        douyin_logger.info('[+] cookie文件不存在或已失效，即将自动打开浏览器，请扫码登录，登陆后会自动生成cookie文件')
        # 生成新的cookie文件
        await douyin_cookie_gen(account_file)
    return True


async def douyin_cookie_gen(account_file):
    """
    生成抖音登录cookie文件（通过用户手动扫码登录）
    :param account_file: 要保存的cookie文件路径
    """
    async with async_playwright() as playwright:
        # 浏览器配置：非无头模式（显示界面）
        options = {
            'headless': False
        }
        # 启动带界面的Chromium浏览器
        browser = await playwright.chromium.launch(**options)
        # 创建浏览器上下文
        context = await browser.new_context()  # 可传入其他配置选项
        # 设置初始化脚本
        context = await set_init_script(context)
        # 创建新页面
        page = await context.new_page()
        # 访问抖音创作者中心首页
        await page.goto("https://creator.douyin.com/")
        # 暂停页面（此时用户需要在打开的浏览器中手动扫码登录）
        await page.pause()
        # 登录完成后，保存cookie到指定文件
        await context.storage_state(path=account_file)




class DouYinImage(object):
    """抖音图片发布类，用于处理图片上传、发布等操作"""
    def __init__(self, graphic_title, hottags, graphic_content, file_path, publish_date: datetime, account_file,product_url=None, product_title=None, thumbnail_path=None,product_url_backup=None, music_id = False, check = True):
        """
        初始化DouYinImage类的实例属性
        :param graphic_title: 图文标题
        :param hottags: 图文标签
        :param graphic_content: 图文内容
        :param file_path: 图片文件路径
        :param publish_date: 发布时间（datetime对象）
        :param account_file: cookie文件路径
        ：param product_url: 商品链接（可选）
        :param product_title: 商品短标题（可选）
        :param thumbnail_path: 缩略图路径（可选）
        ：param product_url_backup: 备用商品链接（可选）
        """
        self.graphic_title = graphic_title  # 图文标题
        self.hottags = hottags  # 图文标签
        self.graphic_content = graphic_content  # 图文内容
        self.product_url = product_url  # 商品链接
        self.product_title = product_title  # 商品标题
        self.file_path = file_path  # 图片文件路径
        self.publish_date = publish_date  # 发布时间
        self.account_file = account_file  # cookie文件路径
        self.date_format = '%Y年%m月%d日 %H:%M'  # 日期时间格式
        self.local_executable_path = LOCAL_CHROME_PATH  # 本地Chrome浏览器路径
        
        self.thumbnail_path = thumbnail_path  # 缩略图路径
        self.product_url_backup = product_url_backup  # 备用商品链接
        self.music_id = music_id  # 音乐ID
        self.check = check  # 是否检查发布前信息

    async def set_schedule_time_douyin(self, page, publish_date):
        """
        设置定时发布时间
        :param page: 浏览器页面对象
        :param publish_date: 发布时间（datetime对象）
        """
        # 选择"定时发布"的单选按钮
        label_element = page.locator("[class^='radio']:has-text('定时发布')")
        # 点击选中该选项
        await label_element.click()
        await asyncio.sleep(1)  # 等待1秒，确保页面加载完成
        # 格式化发布时间为"年-月-日 时:分"格式
        publish_date_hour = publish_date.strftime("%Y-%m-%d %H:%M")

        await asyncio.sleep(1)
        # 点击日期时间输入框
        await page.locator('.semi-input[placeholder="日期和时间"]').click()
        # 全选输入框内容（Ctrl+A）
        await page.keyboard.press("Control+KeyA")
        # 输入格式化后的时间
        await page.keyboard.type(str(publish_date_hour))
        # 按Enter确认
        await page.keyboard.press("Enter")
        await page.keyboard.press("Enter")

        await asyncio.sleep(1)

    async def handle_upload_error(self, page):
        """
        处理图片上传错误，重新上传
        :param page: 浏览器页面对象
        """
        douyin_logger.info('图片出错了，重新上传中')
        # 重新选择文件上传
        await page.locator('div.progress-div [class^="upload-btn-input"]').set_input_files(self.file_path)
    async def click_disallow_permission(self,page: Page):
        try:
            douyin_logger.info("[-]设置保存权限为'不允许'")
            # 等待"保存权限"标签出现（确保区域加载完成）
            await page.wait_for_selector('span:has-text("保存权限")', timeout=5000)
            
            # 方案1：通过"保存权限"标签找到父级，再定位"不允许"选项（最稳定）
            disallow_label = page.get_by_text("保存权限").locator("..").locator("..").locator("..").locator("label:has-text('不允许')")
            
            if await disallow_label.count() == 0:
                # 方案2：通过input属性+相邻文本定位
                disallow_label = page.locator('input[value="0"]').locator("..").locator(":scope:has-text('不允许')")
            
            if await disallow_label.count() == 0:
                # 方案3：直接通过文本+标签类型定位
                disallow_label = page.locator('label:has-text("不允许")').filter(has=page.locator('input[type="checkbox"]'))
            
            # 检查元素是否存在
            if await disallow_label.count() == 0:
                douyin_logger.error("未找到'不允许'选项元素")
                return
            
            # 检查是否已选中
            is_checked = await disallow_label.locator('input[type="checkbox"]').is_checked()
            if not is_checked:
                # 优先点击label（更稳定，避免直接点击input被遮挡）
                await disallow_label.click()
                douyin_logger.success("已点击'不允许'选项")
            else:
                douyin_logger.info("'不允许'选项已处于选中状态")
                
        except Exception as e:
            douyin_logger.error(f"点击'不允许'选项失败: {str(e)}")
            await page.screenshot(path="disallow_permission_error.png")
    async def add_ai_declaration(self, page: Page):
        """
        添加AI声明：点击"添加声明" → 选择"内容由AI生成" → 点击"确定"
        :param page: 浏览器页面对象
        """
        try:
            # 步骤1：点击新版“自主声明”选择框
            douyin_logger.info("[-]开始添加AI声明：点击'请选择自主声明'")
            declaration_trigger = page.get_by_text("请选择自主声明", exact=True)
            if await declaration_trigger.count() == 0:
                # 已经选择过时无需重复打开弹窗
                if await page.get_by_text("内容由AI生成", exact=True).count() > 0:
                    douyin_logger.info("已存在'内容由AI生成'声明，跳过重复设置")
                    return
                raise RuntimeError("未找到'请选择自主声明'入口")
            await declaration_trigger.first.wait_for(state="visible", timeout=10000)
            await declaration_trigger.first.click()
            await asyncio.sleep(1)  # 等待弹窗加载

            # 步骤2：选择"内容由AI生成"选项
            douyin_logger.info("选择'内容由AI生成'选项")
            # 等待单选框加载，支持已选中和未选中两种状态
            ai_generated_label = page.locator('label.semi-radio:has-text("内容由AI生成")')
            await ai_generated_label.wait_for(timeout=5000)
            
            # 检查是否已选中，未选中则点击
            is_checked = 'semi-radio-checked' in await ai_generated_label.get_attribute('class')
            if not is_checked:
                await ai_generated_label.click()
            douyin_logger.info("已选择'内容由AI生成'")
            await asyncio.sleep(0.5)

            # 步骤3：点击"确定"按钮
            douyin_logger.info("点击'确定'按钮确认声明")
            confirm_btn = page.get_by_role("button", name="确定", exact=True)
            await confirm_btn.wait_for(state="visible", timeout=5000)
            await confirm_btn.click()
            await asyncio.sleep(1)  # 等待弹窗关闭

            douyin_logger.success("AI声明添加完成")

        except Exception as e:
            douyin_logger.error(f"添加AI声明失败: {str(e)}")
            # 截图保存错误状态
            await page.screenshot(path="ai_declaration_error.png")
            raise
    
    # 添加小黄车的方法（放入DouYinImage类中）
    async def add_shopping_cart(self, page: Page):
            """
            添加小黄车功能（整合到类方法中，使用实例属性）
            """
            # 检查是否提供了商品链接和短标题
            if not self.product_url or not self.product_title:
                douyin_logger.warning("未提供商品链接或短标题，跳过添加小黄车")
                return

            try:
                douyin_logger.info("[-]开始添加小黄车")
                
                
                # 2. 输入商品链接
                douyin_logger.info("步骤1/6：点击添加小黄车按钮")
                try:
                    # 1. 定位核心元素
                    # 外层semi-select容器
                    select_container = page.locator('div.semi-select.select-GDaqAd.semi-select-single:has(div[data-code="-11"].select-dropdown-option-img)')
                    # 右侧箭头图标
                    arrow_icon = select_container.locator('div.semi-select-arrow')
                    # 位置文本区域
                    location_text = select_container.locator('div[data-code="-11"].select-dropdown-option-img')
                    # try:
                    #     # 定位"我知道了"按钮（组合class+文本定位，确保准确）
                    #     know_btn = page.locator('button.douyin-creator-pc-master__button.douyin-creator-pc-master__button-next.shepherd-button:has-text("我知道了")')
                        
                    #     # 等待按钮可见且可交互
                    #     await know_btn.wait_for(state="visible", timeout=5000)
                        
                    #     # 执行点击（force=True处理可能的层级遮挡）
                    #     await know_btn.click(force=True)
                    #     await asyncio.sleep(1)  # 等待弹窗关闭动画

                    #     douyin_logger.info("步骤2/6：关闭'我知道了'提示框")
                    # except Exception as e:
                    #     douyin_logger.error(f"关闭提示框失败: {str(e)}")
                    #     await page.screenshot(path="close_know_btn_error.png")
                    
                    # 2. 前置准备：滚动到元素+聚焦组件
                    await select_container.scroll_into_view_if_needed()
                    await select_container.focus()  # 让组件获得焦点（模拟用户tab聚焦）
                    await asyncio.sleep(0.5)

                    # 3. 第一步：点击箭头图标（组件原生触发点）
                    await arrow_icon.click(button='left', force=True)
                    await asyncio.sleep(0.5)

                    # 4. 第二步：键盘触发（按向下箭头键，部分组件响应键盘事件）
                    # await page.keyboard.press('ArrowDown')
                    await page.get_by_role("option", name="购物车").click()
                    await asyncio.sleep(0.5)


                except Exception as e:
                    douyin_logger.error(f"触发位置下拉框失败: {str(e)}")
                    await page.screenshot(path="location_final_error.png")
                
                # 模拟按下下箭头键（ArrowDown）
                await page.keyboard.press('ArrowDown')
                await asyncio.sleep(0.3)

                # 模拟按下回车键（Enter）
                await page.keyboard.press('Enter')
                await asyncio.sleep(0.3)    
                
                # 2. 输入商品链接
                douyin_logger.info("步骤3/6：输入商品链接")
                # 修正state参数为支持的"visible"，并确保选择器准确
                link_selector = 'input[placeholder="粘贴商品链接"].input-inner-fAjWnh.form-NudgZa'
                link_locator = page.locator(link_selector)
                # 等待元素可见（正确的state参数）
                await link_locator.wait_for(state="visible", timeout=10000)
                # 可选：先聚焦输入框，确保可输入
                await link_locator.focus()
                # 填充商品链接
                await link_locator.fill(self.product_url)
                await asyncio.sleep(1)
                # 3. 点击确认添加按钮
                douyin_logger.info("步骤4/6：点击确认添加按钮")
                try:
                    # 定位添加链接的span元素
                    add_link_selector = 'span.cart-mybtn-ROaNYY:has-text("添加链接")'
                    add_link_locator = page.locator(add_link_selector)
                    
                    # 等待元素可见且可交互
                    await add_link_locator.wait_for(state="visible", timeout=10000)
                    
                    # 执行点击（force=True处理可能的遮挡）
                    await add_link_locator.click(force=True)
                    await asyncio.sleep(2)  # 等待链接添加后的响应
                except Exception as e:
                    douyin_logger.error(f"点击添加链接失败: {str(e)}")
                    await page.screenshot(path="add_link_error.png")
                # 4. 输入商品短标题（最多10个汉字）
                douyin_logger.info("步骤5/6：输入商品短标题")
                short_title = self.product_title[:10]  # 截取10字以内
                # 修正：添加await，且优化选择器匹配
                short_title_input = await page.wait_for_selector(
                    'input.semi-input.semi-input-default[placeholder="请输入商品短标题"]',
                    state="visible",  # 等待元素可见
                    timeout=10000
                )
                await short_title_input.fill(short_title)
                await asyncio.sleep(1)
                
                
                # 5. 点击完成编辑按钮
                douyin_logger.info("步骤6/6：点击完成编辑")
                finish_btn_selector = 'button.button-dhlUZE.modal-btn-VTrk8w.primary-cECiOJ'
                finish_btn = page.locator(finish_btn_selector).filter(has_text="完成编辑")

                try:
                    # 1. 前置准备：滚动到按钮+等待完全可见
                    await finish_btn.scroll_into_view_if_needed()  # 确保按钮在视口内
                    await finish_btn.wait_for(state="visible", timeout=10000)
                    await asyncio.sleep(0.5)

                    # 2. 方式1：Playwright强制点击（忽略遮挡/层级）
                    await finish_btn.click(force=True, no_wait_after=True)
                    await asyncio.sleep(1)

                    

                except Exception as e:
                    douyin_logger.error(f"点击完成编辑按钮失败: {str(e)}")
                    await page.screenshot(path="finish_edit_final_error.png")
                
                douyin_logger.success("小黄车添加成功")
                
            except Exception as e:
                douyin_logger.error(f"添加小黄车失败: {str(e)}")
                await page.screenshot(path="shopping_cart_error.png")
                # 尝试关闭弹窗
                try:
                    close_btns = page.locator('button[class*="close-btn"], button.semi-modal-close')
                    if await close_btns.count() > 0:
                        await close_btns.first.click()
                except:
                    pass

    # 其他已有方法（set_schedule_time_douyin、handle_upload_error等）保持不变...    


    async def add_shopping_cart2(self, page: Page):
            """
            添加小黄车功能（整合到类方法中，使用实例属性）
            """
            # 检查是否提供了商品链接和短标题
            if not self.product_url or not self.product_title:
                douyin_logger.warning("未提供商品链接或短标题，跳过添加小黄车")
                return

            try:
                douyin_logger.info("[-]开始添加小黄车")
                
                
                # 2. 输入商品链接
                # douyin_logger.info("步骤1/6：点击添加小黄车按钮")
                # try:
                #     # 1. 定位核心元素
                #     # 外层semi-select容器
                #     select_container = page.locator('div.semi-select.select-GDaqAd.semi-select-single:has(div[data-code="-11"].select-dropdown-option-img)')
                #     # 右侧箭头图标
                #     arrow_icon = select_container.locator('div.semi-select-arrow')
                #     # 位置文本区域
                #     location_text = select_container.locator('div[data-code="-11"].select-dropdown-option-img')
                #     # 2. 前置准备：滚动到元素+聚焦组件
                #     await select_container.scroll_into_view_if_needed()
                #     await select_container.focus()  # 让组件获得焦点（模拟用户tab聚焦）
                #     await asyncio.sleep(0.5)
                #     # 3. 第一步：点击箭头图标（组件原生触发点）
                #     await arrow_icon.click(button='left', force=True)
                #     await asyncio.sleep(0.5)
                #     # 4. 第二步：键盘触发（按向下箭头键，部分组件响应键盘事件）
                #     # await page.keyboard.press('ArrowDown')
                #     await page.get_by_role("option", name="购物车").click()
                #     await asyncio.sleep(0.5)
                # except Exception as e:
                #     douyin_logger.error(f"触发位置下拉框失败: {str(e)}")
                #     await page.screenshot(path="location_final_error.png")
                # # 模拟按下下箭头键（ArrowDown）
                # await page.keyboard.press('ArrowDown')
                # await asyncio.sleep(0.3)
                # # 模拟按下回车键（Enter）
                # await page.keyboard.press('Enter')
                # await asyncio.sleep(0.3)    
                

                await page.locator(".semi-select.select-GDaqAd > .semi-select-arrow").click()
                await asyncio.sleep(1)

                await page.get_by_role("option", name="购物车").click()
                await asyncio.sleep(1)

                # 2. 输入商品链接
                douyin_logger.info("步骤3/6：输入商品链接")
                # 修正state参数为支持的"visible"，并确保选择器准确
                link_selector = 'input[placeholder="粘贴商品链接"].input-inner-fAjWnh.form-NudgZa'
                link_locator = page.locator(link_selector)
                # 等待元素可见（正确的state参数）
                await link_locator.wait_for(state="visible", timeout=10000)
                # 可选：先聚焦输入框，确保可输入
                await link_locator.focus()
                # 填充商品链接
                await link_locator.fill(self.product_url)
                await asyncio.sleep(1)
                # 3. 点击确认添加按钮
                douyin_logger.info("步骤4/6：点击确认添加按钮")
                try:
                    # 定位添加链接的span元素
                    add_link_selector = 'span.cart-mybtn-ROaNYY:has-text("添加链接")'
                    add_link_locator = page.locator(add_link_selector)
                    
                    # 等待元素可见且可交互
                    await add_link_locator.wait_for(state="visible", timeout=10000)
                    
                    # 执行点击（force=True处理可能的遮挡）
                    await add_link_locator.click(force=True)
                    await asyncio.sleep(2)  # 等待链接添加后的响应
                except Exception as e:
                    douyin_logger.error(f"点击添加链接失败: {str(e)}")
                    await page.screenshot(path="add_link_error.png")
                # 4. 输入商品短标题（最多10个汉字）
                douyin_logger.info("步骤5/6：输入商品短标题")
                short_title = self.product_title[:10]  # 截取10字以内
                # 修正：添加await，且优化选择器匹配
                short_title_input = await page.wait_for_selector(
                    'input.semi-input.semi-input-default[placeholder="请输入商品短标题"]',
                    state="visible",  # 等待元素可见
                    timeout=10000
                )
                await short_title_input.fill(short_title)
                await asyncio.sleep(1)
                
                
                # 5. 点击完成编辑按钮
                douyin_logger.info("步骤6/6：点击完成编辑")
                finish_btn_selector = 'button.button-dhlUZE.modal-btn-VTrk8w.primary-cECiOJ'
                finish_btn = page.locator(finish_btn_selector).filter(has_text="完成编辑")

                try:
                    # 1. 前置准备：滚动到按钮+等待完全可见
                    await finish_btn.scroll_into_view_if_needed()  # 确保按钮在视口内
                    await finish_btn.wait_for(state="visible", timeout=10000)
                    await asyncio.sleep(0.5)

                    # 2. 方式1：Playwright强制点击（忽略遮挡/层级）
                    await finish_btn.click(force=True, no_wait_after=True)
                    await asyncio.sleep(1)

                    

                except Exception as e:
                    douyin_logger.error(f"点击完成编辑按钮失败: {str(e)}")
                    await page.screenshot(path="finish_edit_final_error.png")
                
                douyin_logger.success("小黄车添加成功")
                
            except Exception as e:
                douyin_logger.error(f"添加小黄车失败: {str(e)}")
                await page.screenshot(path="shopping_cart_error.png")
                # 尝试关闭弹窗
                try:
                    close_btns = page.locator('button[class*="close-btn"], button.semi-modal-close')
                    if await close_btns.count() > 0:
                        await close_btns.first.click()
                except:
                    pass
    async def add_specified_music(self, page: Page):
        """
        精准添加指定音乐（修复多元素匹配问题）：
        选择音乐 → 点击收藏 → 悬停目标音乐 → 点击使用 → 结果校验
        """
        try:
            # 步骤1：精准点击"选择音乐"（第二个按钮）
            douyin_logger.info("步骤1/4：点击'选择音乐'按钮")
            select_music_btns = page.get_by_text("选择音乐", exact=True)
            if await select_music_btns.count() >= 2:
                await select_music_btns.nth(1).click()  # 选择第二个（音乐区域的）
            else:
                await select_music_btns.first.click()
            await asyncio.sleep(3)

            # 步骤2：点击"收藏"标签
            douyin_logger.info("步骤2/4：点击'收藏'标签")
            collect_tab = page.locator('[role="tab"][data-scrollkey="fav-1-bar"]:has-text("收藏")')
            if await collect_tab.count() == 0:
                collect_tab = page.get_by_role("tab", name="收藏", exact=True)
            await collect_tab.click(force=True)
            await asyncio.sleep(3)  # 等待收藏列表加载完成

            if self.music_id:
                if self.music_id == 1:
                    btn = page.locator(".cover-DeFe3B").first
                else:
                    btn = page.locator("div:nth-child(" + str(self.music_id) + ") > .card-wrapper-JTleG1 > .card-container-left-Sww1pX > .cover-container-et1npT > .cover-DeFe3B")
                
                await btn.click()   
                await asyncio.sleep(1)  # 每3秒检查一次

                # await btn.click()   

                await page.get_by_role("button", name="使用").click()


            else:
                # 步骤3：悬停目标音乐并点击"使用"
                douyin_logger.info("步骤3/4：悬停目标音乐并点击'使用'按钮")
                root = Tk()
                root.attributes("-topmost", True)  # 窗口置顶
                root.withdraw()  # 隐藏主窗口

                # 此时弹出的messagebox会继承置顶属性，显示在最上层
                messagebox.showinfo("提示", "请确保目标音乐已收藏并准备好，按回车继续...")





            # 步骤4：校验结果
            douyin_logger.info("步骤4/4：校验音乐添加结果")
            default_text = page.locator('div:has-text("点击添加合适作品风格音乐")')
            if await default_text.count() == 0:
                douyin_logger.success("✅ 音乐添加成功！")
            else:
                raise Exception("❌ 音乐添加失败：仍显示默认提示文本")

        except Exception as e:
            douyin_logger.error(f"添加指定音乐失败: {str(e)}")
            
            
    async def set_thumbnail(self, page: Page, thumbnail_path: str):
        """
        设置图片封面（缩略图）
        :param page: 浏览器页面对象
        :param thumbnail_path: 缩略图文件路径
        """
        if thumbnail_path:  # 如果提供了缩略图路径
            # 点击"选择封面"按钮
            # await page.click('text="选择封面"')
            # # 等待封面设置弹窗出现
            # await page.wait_for_selector("div.semi-modal-content:visible")
            # # 点击"设置竖封面"
            # await page.click('text="设置竖封面"')
            # await page.wait_for_timeout(2000)  # 等待2秒，确保弹窗加载完成
            # # 定位上传区域并上传缩略图文件
            # await page.locator("div[class^='semi-upload upload'] >> input.semi-upload-hidden-input").set_input_files(thumbnail_path)
            # await page.wait_for_timeout(2000)  # 等待2秒，确保上传完成
            # # 点击"完成"按钮确认设置
            # await page.locator("div[class^='extractFooter'] button:visible:has-text('完成')").click()
            try:
                # 定位编辑封面元素（结合class+文本，精准匹配）
                edit_cover_selector = 'span.mycard-info-text-span-Z8KqXI:has-text("编辑封面")'
                edit_cover_element = page.locator(edit_cover_selector)
            
                # 等待元素可见且可交互
                # await edit_cover_element.wait_for(state="visible", timeout=10000)
                # # 滚动到元素（避免视口外遮挡）
                # await edit_cover_element.scroll_into_view_if_needed()
                # 执行点击（force=True处理层级遮挡）
                await edit_cover_element.click(force=True)
                
                # 点击"上传封面"标签
                await page.click('div[role="tab"].semi-tabs-tab:has-text("上传封面")')     
                await page.wait_for_timeout(2000)  # 等待2秒，确保弹窗加载完成
                # 定位上传区域并上传缩略图文件
                upload_box = page.locator("div.box-V7vvoN")
                await upload_box.wait_for(state="visible")
                # 先滚动到元素
                await upload_box.scroll_into_view_if_needed()
                # 强制点击（忽略遮挡）
                # await upload_box.click(force=True)
                await upload_box.set_input_files(thumbnail_path)
                await page.wait_for_timeout(2000)  # 等待2秒，确保上传完成

                root = Tk()
                root.attributes("-topmost", True)  # 窗口置顶
                root.withdraw()  # 隐藏主窗口

                # 此时弹出的messagebox会继承置顶属性，显示在最上层
                messagebox.showinfo("提示", "请确保调整好封面，按回车继续...")
                douyin_logger.success("封面编辑操作已确认完成")
                await page.locator("button:has-text('确定').primary-cECiOJ").nth(1).click()
                 # ========== 集成滚动+循环点击确定按钮逻辑 ==========
                # 关键代码+详细日志
                # 严格匹配CSS样式条件后再点击
                confirm_btn = page.locator("button.button-dhlUZE.submit-wycsGi.primary-cECiOJ.large-fv3ghk")

                # 1. 滚动到按钮
                douyin_logger.info("📌 滚动到目标按钮位置...")
                await confirm_btn.scroll_into_view_if_needed()

                # 2. 严格匹配CSS样式条件（background:#fe2c55 + color:#fff + opacity:1）
                douyin_logger.info("⏳ 等待按钮样式完全匹配 .button-dhlUZE.primary-cECiOJ 规则...")
                for i in range(6):  # 最多检查6次（每次等待5秒，共30秒）  
                    # 获取精确的样式属性
                    style_status = await confirm_btn.evaluate("""el => {
                        const computed = window.getComputedStyle(el);
                        return {
                            hasPrimaryClass: el.classList.contains('primary-cECiOJ'),
                            isDisabled: el.disabled,
                            background: computed.backgroundColor,
                            color: computed.color,
                            opacity: computed.opacity,
                            backgroundHex: computed.backgroundColor.includes('rgb(254, 44, 85)') ? '#fe2c55' : computed.backgroundColor,
                            colorHex: computed.color.includes('rgb(255, 255, 255)') ? '#fff' : computed.color
                        };
                    }""")
                    
                    # 严格判断：必须完全匹配CSS规则
                    is_ready = (
                        style_status['hasPrimaryClass'] and 
                        not style_status['isDisabled'] and 
                        (style_status['background'] == 'rgb(254, 44, 85)' or style_status['backgroundHex'] == '#fe2c55') and
                        (style_status['color'] == 'rgb(255, 255, 255)' or style_status['colorHex'] == '#fff') and
                        style_status['opacity'] == '1'
                    )
                    
                    douyin_logger.info(f"  样式检测({i+1}/6): bg={style_status['backgroundHex']}, color={style_status['colorHex']}, opacity={style_status['opacity']}, disabled={style_status['isDisabled']}")
                    
                    if is_ready:
                        douyin_logger.info(f"✅ 按钮样式完全匹配！background:#fe2c55, color:#fff, opacity:1")
                        break
                    await asyncio.sleep(5)  # 每3秒检查一次
                else:
                    douyin_logger.info("⚠️ 警告：30秒内未匹配到目标样式")

                # 3. 点击直到消失
                douyin_logger.info("🔴 开始点击按钮，直到消失...")
                # 优化点击逻辑：短间隔检查状态，避免重复点击和过长等待
                for j in range(100):  # 增加检查次数，减少单次等待时间
                    # 每次循环先检查按钮状态
                    btn_count = await confirm_btn.count()
                    is_visible = await confirm_btn.is_visible() if btn_count > 0 else False
                    
                    if btn_count == 0 or not is_visible:
                        douyin_logger.info(f"🎉 按钮已消失（总检查{j+1}次后成功）")
                        break
                    
                    # 只在第1、5、10次检查时尝试点击（避免频繁点击导致重复上传）
                    if j in [0,19,39]:
                        douyin_logger.info(f"  执行点击...(第{j//20 +1}次点击)")
                        await confirm_btn.click()
                    else:
                        douyin_logger.info(f"  检查状态中...({j+1}/100，按钮仍存在)")
                    
                    await asyncio.sleep(5)  # 短间隔检查，5秒一次
                else:
                    douyin_logger.info("⚠️ 警告：多次检查后按钮仍未消失")
                
            except Exception as e:
                douyin_logger.error(f"点击编辑封面失败: {str(e)}")
                await page.screenshot(path="edit_cover_error.png")
    async def set_thumbnail_manual(self, page: Page):
        """
        设置图片封面（缩略图）
        :param page: 浏览器页面对象
        """
        if not self.product_url or not self.product_title:
                douyin_logger.warning("未提供商品链接或短标题，跳过添加设置相册封面")
                return
        # 上传图片封面（缩略图）
        douyin_logger.info("点击编辑封面并等待人工处理弹窗")
        try:
            # 定位编辑封面元素（结合class+文本，精准匹配）
            edit_cover_selector = 'span.mycard-info-text-span-Z8KqXI:has-text("编辑封面")'
            edit_cover_element = page.locator(edit_cover_selector)
            
            # 等待元素可见且可交互
            await edit_cover_element.wait_for(state="visible", timeout=10000)
            # 滚动到元素（避免视口外遮挡）
            await edit_cover_element.scroll_into_view_if_needed()
            # 执行点击（force=True处理层级遮挡）
            await edit_cover_element.click(force=True)
            
            root = Tk()
            root.attributes("-topmost", True)  # 窗口置顶
            root.withdraw()  # 隐藏主窗口

            # 此时弹出的messagebox会继承置顶属性，显示在最上层
            messagebox.showinfo("提示", "请确保调整好封面，按回车继续...")
            douyin_logger.success("封面编辑操作已确认完成")
            
        except Exception as e:
            douyin_logger.error(f"点击编辑封面失败: {str(e)}")
            await page.screenshot(path="edit_cover_error.png")
        confirm_btn = page.locator('button.button-dhlUZE.submit-eXWVUP.primary-cECiOJ.large-fv3ghk')
        await confirm_btn.wait_for(state="visible", timeout=10000)
        await confirm_btn.click(force=True)


    async def upload(self, playwright: Playwright, headless: bool = False) -> None:
        """
        执行图片上传和发布操作
        :param playwright: Playwright对象
        """
        # 使用Chromium浏览器启动一个浏览器实例
        if self.local_executable_path:
            # 如果指定了本地Chrome路径，则使用该路径
            browser = await playwright.chromium.launch(headless=headless, executable_path=self.local_executable_path)
        else:
            # 否则使用默认的Chromium
            browser = await playwright.chromium.launch(headless=headless)
        # 创建浏览器上下文，使用指定的cookie文件保持登录状态
        context = await browser.new_context(storage_state=f"{self.account_file}")
        # 设置初始化脚本
        context = await set_init_script(context)

        # 创建一个新的页面
        page = await context.new_page()
        # 访问抖音创作者中心的图片上传页面（default-tab=3表示图片标签）
        await page.goto("https://creator.douyin.com/creator-micro/content/upload?default-tab=3")
        douyin_logger.info(f'[+]正在上传-------{self.graphic_title}')  # 这里日志可能笔误，应为图片
        # 等待页面跳转到上传页面
        douyin_logger.info(f'[-] 正在打开主页...')
        await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload?default-tab=3")
        # 上传图片文件（通过定位输入框并设置文件路径）
        # await page.locator("div[class^='container'] input").set_input_files(self.file_path)
        await asyncio.sleep(1)  # 等待页面加载
        
        # 1. 监听并等待文件选择器出现
        async with page.expect_file_chooser() as fc_info:
            # 2. 点击你原来定位到的那个上传按钮
            await page.get_by_role("button", name="上传图文").click()

        # 3. 获取文件选择器对象，并设置文件路径
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)
 
        # 等待页面跳转到发布页面（兼容两种不同版本的页面URL）
        while True:
            try:
                # 尝试等待第一个版本的发布页面，超时3秒
                await page.wait_for_url(
                    "https://creator.douyin.com/creator-micro/content/publish?enter_from=publish_page", timeout=3000)
                douyin_logger.info("[+] 成功进入version_1发布页面!")
                break  # 成功进入则跳出循环
            except Exception:
                try:
                    # 如果第一个版本超时，尝试等待第二个版本的发布页面
                    await page.wait_for_url(
                        "https://creator.douyin.com/creator-micro/content/post/image?default-tab=3&enter_from=publish_page&media_type=image&type=new",
                        timeout=3000)
                    douyin_logger.info("[+] 成功进入version_2发布页面!")
                    break  # 成功进入则跳出循环
                except:
                    douyin_logger.info("  [-] 超时未进入图片发布页面，重新尝试...")
                    await asyncio.sleep(0.5)  # 等待0.5秒后重试

        
        # 填充标题和话题标签
        await asyncio.sleep(1)  # 等待页面加载
        douyin_logger.info(f'  [-] 正在填充标题和话题...')
        title_container = page.locator('input.semi-input[placeholder="添加作品标题"]')

        
        if await title_container.count():
            # 如果找到标题输入框，填充标题（限制20字以内）
            await title_container.fill(self.graphic_title[:20])
            douyin_logger.info("标题已填充完成-普通输入框")
        else:
            # 兼容另一种标题输入框（富文本编辑器）
            titlecontainer = page.locator(".notranslate")
            await titlecontainer.click()
            # 清除现有内容
            await page.keyboard.press("Backspace")
            await page.keyboard.press("Control+KeyA")
            await page.keyboard.press("Delete")
            # 输入标题并按Enter确认
            await page.keyboard.type(self.graphic_title[:20])
            await page.keyboard.press("Enter")
            douyin_logger.info("标题已填充完成-富文本编辑器")
        
        # 定位话题输入区域
        css_selector = ".zone-container"
        await page.type(css_selector,self.graphic_content)  # 填充图文内容
        # 遍历标签列表，逐个添加话题（话题格式为#标签名）
        self.hottags = [tag.strip() for tag in self.hottags.split(" ") if tag.strip()]
        for index, tag in enumerate(self.hottags, start=1):
            await page.type(css_selector, tag)
            await page.press(css_selector, "Space")  # 空格分隔话题
        douyin_logger.info(f'总共添加{len(self.hottags)}个话题')
        await asyncio.sleep(1)  # 等待1秒，确保内容填充完成
        # 等待图片上传完成
        while True:
            try:
                # 检查"清空并重新上传"按钮是否存在（存在说明上传完成）
                number = await page.locator('[class^="bottom-button"] div:has-text("清空并重新上传")').count()
                if number > 0:
                    douyin_logger.success("  [-]图片上传完毕")
                    break
                else:
                    douyin_logger.info("  [-] 正在上传图片中...")
                    await asyncio.sleep(2)  # 每2秒检查一次

                    # 检查是否出现上传失败提示
                    if await page.locator('div.progress-div > div:has-text("上传失败")').count():
                        douyin_logger.error("  [-] 发现上传出错了... 准备重试")
                        await self.handle_upload_error(page)  # 调用错误处理方法重新上传
            except:
                douyin_logger.info("  [-] 正在上传图片中...")
                await asyncio.sleep(2)
        
        
        # 创建主窗口并设置置顶，再隐藏
        await self.click_disallow_permission(page)  # 设置保存权限
        await self.add_ai_declaration(page)         # 添加AI声明
        await self.add_specified_music(page)        # 添加指定音乐
        # await self.add_shopping_cart(page)          # 添加小黄车功能
        await self.add_shopping_cart2(page)          # 添加小黄车功能


        # 如果设置了发布时间，则设置定时发布
        if self.publish_date != 0:
            await self.set_schedule_time_douyin(page, self.publish_date)
        # 执行发布操作并检查是否成功

        if self.check:
            root = Tk()
            root.attributes("-topmost", True)  # 窗口置顶
            root.withdraw()  # 隐藏主窗口

            # 此时弹出的messagebox会继承置顶属性，显示在最上层
            messagebox.showinfo("提示", "请确检查所有信息，按回车继续...")

        while True:
            try:
                # 定位"发布"按钮
                publish_button = page.get_by_role('button', name="发布", exact=True)
                if await publish_button.count():
                    await publish_button.click()  # 点击发布
                # 等待页面跳转到作品管理页面（表示发布成功），超时3秒
                await page.wait_for_url("https://creator.douyin.com/creator-micro/content/manage**",
                                        timeout=3000)
                douyin_logger.success("  [-]图片发布成功")
                break
            except:
                douyin_logger.info("  [-] 图片正在发布中...")
                # 截图保存当前页面状态（用于调试）
                await page.screenshot(full_page=True)
                await asyncio.sleep(0.5)  # 每0.5秒检查一次

        # 保存更新后的cookie
        await context.storage_state(path=self.account_file)
        douyin_logger.success('  [-]cookie更新完毕！')
        await asyncio.sleep(2)  # 延迟2秒，方便观察操作结果
        # 关闭浏览器上下文和浏览器实例
        await context.close()
        await browser.close()

    async def shotwebsite(self,  playwright: Playwright, slp, shot) -> None:
            """
            执行图片上传和发布操作
            :param playwright: Playwright对象
            """
            # 使用Chromium浏览器启动一个浏览器实例
            if self.local_executable_path:
                # 如果指定了本地Chrome路径，则使用该路径
                browser = await playwright.chromium.launch(headless=False, executable_path=self.local_executable_path)
            else:
                # 否则使用默认的Chromium
                browser = await playwright.chromium.launch(headless=False)
            # 创建浏览器上下文，使用指定的cookie文件保持登录状态
            context = await browser.new_context(storage_state=f"{self.account_file}")
            # 设置初始化脚本
            context = await set_init_script(context)

            # 创建一个新的页面
            page = await context.new_page()
            # 访问抖音创作者中心的图片上传页面（default-tab=3表示图片标签）
            # await page.goto("https://creator.douyin.com/home")

            # try:
            #     # 设置最多等 15000 毫秒 (15秒)
            #     await page.goto("https://creator.douyin.com/home", timeout=10)
            # except Exception:
            #     # 发生超时错误时不中断程序，直接 pass，继续执行后面的截图代码
            #     pass

            # 只要 HTML 文档加载和解析完成就继续，不等图片和样式表
            await page.goto("https://creator.douyin.com/home", wait_until="domcontentloaded")

            await asyncio.sleep(10) 
            hao = Path(self.account_file).stem
            import time
            tm = time.strftime("%Y-%m-%d-%H-%M-%S")
            if shot:
                await page.screenshot(path=f"首页截屏/{hao}_{tm}.png")
            if slp is None:
                # 仅查看账号时保持浏览器打开，用户手动关闭窗口后再退出。
                while not page.is_closed():
                    await asyncio.sleep(1)
            else:
                await asyncio.sleep(slp)






    async def main_shotwebsite(self, shot, slp):
        """主方法，启动playwright并执行上传发布流程"""
        async with async_playwright() as playwright:
            await self.shotwebsite(playwright, shot=shot, slp=slp)



    async def main(self, headless):
        """主方法，启动playwright并执行上传发布流程"""
        async with async_playwright() as playwright:
            await self.upload(playwright, headless=headless)
