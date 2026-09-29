# -*- coding: utf-8 -*-
import asyncio
import re
import time
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Playwright, TimeoutError as PlaywrightTimeoutError, async_playwright

from conf import LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script


# ==========================
# 运行参数（直接改这里即可）
# ==========================
ACCOUNT_FILE = Path("cookies/dola/account1.json")
PROMPT = "参考图是芍药，一位年轻的中国男子蹲在户外的芍药花田里，他双手正扶着一株放在黑色塑料花盆上的健康芍药花苗，花苗长着许多红绿相间的饱满芽苞。在他脚下的草地上，并排横放着三株芍药根块，根系粗壮发达，带有泥土，顶部有很多红色的新芽。背景是大片盛开的红色、粉色和紫色芍药花海，远处有树木和几个模糊的人影。阴天，柔和的自然光线。他举着芍药说：比牡丹还漂亮的精品芍药花苗根全部处理了，都是带芽苞发货，收到家随便找个花盆塑料桶给它种上浇透水，很快就能开出拳头大的花，花瓣层层叠叠，淡雅清香，朋友来了都夸好看。种一次年年都有花看。"
# 支持上传多张参考图，按顺序填写。
REFERENCE_IMAGE_PATHS = [
    Path("芍药.png"),
]
RATIO = "9:16"
SAVE_DIR = Path("dola_video_output")
THEME = "shaoyao"
HEADLESS = False
MODEL_NAME = "Dreamina Seedance 2.0 Fast"
VIDEO_DURATION = "10s"







DOWNLOAD_TOTAL_WAIT_SECONDS = 20 * 60
INITIAL_STATE_WAIT_SECONDS = 2
STATE_POLL_INTERVAL_SECONDS = 5
PAGE_REFRESH_INTERVAL_SECONDS = 30
ONLY_CLICK_LATEST_VIDEO = True
VERBOSE_DECISION_LOG = False
QUOTA_EXHAUSTED_MESSAGES = (
    "今天的生成次数已经达到上限，明天再来免费生成吧～",
    "今日视频生成免费次数已用完",
    "今日视频生成免费次数用完了",
    "今日免费额度已用完",
    "已达到今日生成上限",
    "今日生成次数已达上限",
    "免费次数已用完",
    "免费次数用完了",
)
QUOTA_EXHAUSTED_PATTERNS = (
    re.compile(r"(?:今日|今天)?(?:视频生成)?免费次数(?:已经|已)?用完(?:了)?"),
    re.compile(
        r"(?:今日|今天)?(?:免费)?(?:视频生成|生成|创作)?额度"
        r"(?:已经|已)?(?:用完|耗尽|不足)(?:了)?"
    ),
    re.compile(r"(?:生成|创作)?次数(?:已经|已)?达到(?:今日|今天)?上限"),
    re.compile(r"(?:今日|今天)(?:生成|创作)?次数(?:已经|已)?达(?:到)?上限"),
)
GENERATION_ACCEPTED_MESSAGES = (
    "视频生成已提交",
    "预计等待",
    "视频生成好后",
    "本次生成将消耗每日免费额度",
)
GENERATION_COMPLETED_MESSAGES = (
    "你的视频生成好了",
    "视频已经生成好了",
    "视频已生成完成",
)
GENERATION_BLOCKED_MESSAGES = (
    "疑似包含侵权",
    "疑似包含违规",
    "侵权 / 违规内容",
    "侵权/违规内容",
    "无法返回该内容",
    "涉及版权限制",
    "可能涉及版权",
    "版权限制",
    "请更换输入内容后重试",
    "无法生成你要求的内容",
    "无法生成你请求的内容",
    "无法为你生成该内容",
    "无法帮助生成此类内容",
)
TRANSIENT_FAILURE_MESSAGES = (
    "生成失败，请重试",
    "生成失败，请稍后重试",
    "服务繁忙",
    "系统繁忙",
    "请稍后重试",
    "网络异常",
)
GENERATION_BLOCKED_APPEAL_MESSAGE = "这都是我原创的，没有侵权，你直接生成就行"


class QuotaExhaustedError(Exception):
    """账号当日额度已用尽。"""

    pass


class VideoGenerateFailedError(Exception):
    """视频生成失败（未扣额度），可按重试策略继续尝试。"""

    pass


class ContentBlockedError(Exception):
    """内容明确违规，申诉一次后仍失败，不应换账号重复消耗。"""

    pass





class DolaVideoGenerator:
    def __init__(self, account_file: Path):
        self.account_file = Path(account_file)
        self.local_executable_path = LOCAL_CHROME_PATH
        self._submit_message_baseline_ids: set[str] = set()
        self._message_snapshots: dict[str, tuple[str, bool]] = {}
        self._completion_message_id: str | None = None
        self._last_generation_state = "waiting"
        self._last_generation_text = ""
        self._blocked_appeal_sent = False
        self._startup_popup_handled = False
    
    @staticmethod
    def _log(message: str) -> None:
        now = time.strftime("%H:%M:%S")
        print(f"[{now}] {message}")

    @staticmethod
    def _preview_text(text: str | None, limit: int = 120) -> str:
        if text is None:
            return "<None>"
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}..."

    @staticmethod
    def _log_decision(
        name: str,
        result: bool,
        source: str,
        matched: str | None = None,
        text: str | None = None,
    ) -> None:
        detail = [f"[decision] {name}={result}", f"source={source}"]
        if matched is not None:
            detail.append(f"matched={matched!r}")
        if text is not None and VERBOSE_DECISION_LOG:
            detail.append(f"text={DolaVideoGenerator._preview_text(text)}")
        DolaVideoGenerator._log(" | ".join(detail))

    @staticmethod
    def _contains_quota_exhausted_message(text: str) -> bool:
        if not text:
            DolaVideoGenerator._log_decision(
                "quota_exhausted",
                False,
                source="empty_text",
                text=text,
            )
            return False
        for message in QUOTA_EXHAUSTED_MESSAGES:
            if message and message in text:
                DolaVideoGenerator._log_decision(
                    "quota_exhausted",
                    True,
                    source="quota_messages",
                    matched=message,
                    text=text,
                )
                return True
        for pattern in QUOTA_EXHAUSTED_PATTERNS:
            match = pattern.search(text)
            if match:
                DolaVideoGenerator._log_decision(
                    "quota_exhausted",
                    True,
                    source="quota_patterns",
                    matched=match.group(0),
                    text=text,
                )
                return True
        DolaVideoGenerator._log_decision(
            "quota_exhausted",
            False,
            source="quota_messages",
            text=text,
        )
        return False

    @staticmethod
    def _classify_generation_message(message: dict) -> str:
        """把一条Dola回复归为唯一状态；未知绝不等同于失败或违规。"""
        text = re.sub(r"\s+", " ", str(message.get("text", ""))).strip()
        if message.get("has_video") or any(
            indicator in text for indicator in GENERATION_COMPLETED_MESSAGES
        ):
            return "completed"
        if DolaVideoGenerator._contains_quota_exhausted_message(text):
            return "quota_exhausted"
        if any(indicator in text for indicator in GENERATION_BLOCKED_MESSAGES):
            return "blocked"
        if any(indicator in text for indicator in GENERATION_ACCEPTED_MESSAGES) or re.search(
            r"今日剩余\s*\d+\s*个视频生成额度", text
        ):
            return "accepted"
        if any(indicator in text for indicator in TRANSIENT_FAILURE_MESSAGES):
            return "transient_failure"
        return "unknown"

    @classmethod
    def _select_generation_event(cls, messages: list[dict]) -> tuple[str, dict | None]:
        if not messages:
            return "no_change", None

        classified = [(cls._classify_generation_message(message), message) for message in messages]

        # 同一轮可能同时读到“违规”和随后异步到达的完成消息；
        # 新视频卡片/明确完成文案是最强事实，优先下载。
        for state, message in reversed(classified):
            if state == "completed":
                return state, message

        # 其余情况按页面中的最新一条已识别Dola回复决定。
        for state, message in reversed(classified):
            if state != "unknown":
                return state, message
        return "unknown", messages[-1]

    async def _is_chat_page_actionable(self, page: Page, timeout_ms: int = 1200) -> bool:
        checks = [
            lambda p: p.get_by_test_id("chat_input_input").first,
            lambda p: p.get_by_role("button", name="视频生成").first,
            lambda p: p.get_by_text("视频生成", exact=True).first,
        ]
        for factory in checks:
            locator = factory(page)
            try:
                await locator.wait_for(state="visible", timeout=timeout_ms)
                await locator.click(trial=True, timeout=timeout_ms)
                return True
            except (PlaywrightTimeoutError, PlaywrightError):
                continue
        return False

    async def _count_visible_blocking_layers(self, page: Page) -> tuple[int, int]:
        dialog_selectors = (
            "[role='dialog']",
            "div[class*='modal']",
            "div[class*='dialog']",
            "div[class*='popup']",
        )
        mask_selectors = (
            "div[class*='mask']",
            "div[class*='overlay']",
            "div[class*='backdrop']",
        )

        async def count_visible(selectors: tuple[str, ...]) -> int:
            total = 0
            for selector in selectors:
                locator = page.locator(selector)
                try:
                    count = await locator.count()
                except PlaywrightError:
                    continue
                for idx in range(count):
                    try:
                        if await locator.nth(idx).is_visible():
                            total += 1
                    except PlaywrightError:
                        continue
            return total

        dialog_count = await count_visible(dialog_selectors)
        mask_count = await count_visible(mask_selectors)
        return dialog_count, mask_count

    async def _collect_visible_popup_texts(self, page: Page, limit: int = 3) -> list[str]:
        selectors = [
            "[role='dialog']",
            "div[class*='modal']",
            "div[class*='dialog']",
            "div[class*='popup']",
        ]
        snippets: list[str] = []
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except PlaywrightError:
                continue
            if count == 0:
                continue
            for idx in range(min(count, limit)):
                try:
                    candidate = locator.nth(idx)
                    if not await candidate.is_visible():
                        continue
                    text = (await candidate.inner_text(timeout=800)).strip()
                except PlaywrightError:
                    continue
                if not text:
                    continue
                preview = self._preview_text(text, limit=60)
                if preview not in snippets:
                    snippets.append(preview)
                if len(snippets) >= limit:
                    return snippets
        return snippets

    async def _dismiss_startup_blocking_popup_once(self, page: Page) -> None:
        if self._startup_popup_handled:
            return
        self._startup_popup_handled = True
        self._log("步骤0/8：开屏弹窗检查（仅执行一次）。")

        # Dola首次打开会在左下角显示Cookie说明。它不是全屏遮罩，页面上的
        # 其他控件仍可能通过可点击检查，因此必须在通用弹窗判断之前主动关闭。
        cookie_actions = [
            lambda p: p.get_by_role("button", name="我知道了", exact=True),
            lambda p: p.get_by_text("我知道了", exact=True),
            lambda p: p.get_by_role(
                "button", name=re.compile(r"^(?:知道了|接受|同意|Got it|Accept)$", re.IGNORECASE)
            ),
            lambda p: p.locator("div").filter(
                has_text=re.compile(r"Dola\s*使用\s*Cookie", re.IGNORECASE)
            ).get_by_text("我知道了", exact=True),
        ]
        for factory in cookie_actions:
            locator = factory(page)
            try:
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    if not await candidate.is_visible():
                        continue
                    await candidate.click(timeout=1200)
                    await page.wait_for_timeout(250)
                    self._log("步骤0/8：已点击Dola Cookie提示中的“我知道了”。")
                    if await self._is_chat_page_actionable(page, timeout_ms=900):
                        self._log("步骤0/8完成：Cookie提示已关闭，页面可以继续操作。")
                        return
                    break
            except (PlaywrightTimeoutError, PlaywrightError):
                continue

        x_close_actions = [
            lambda p: p.locator("[role='dialog'] button[aria-label*='关闭']").first,
            lambda p: p.locator("button[aria-label*='关闭']").first,
            lambda p: p.locator("button[title*='关闭']").first,
            lambda p: p.locator("div[role='dialog'] svg").locator("xpath=ancestor::button[1]").first,
            lambda p: p.locator("div[class*='modal'] svg").locator("xpath=ancestor::button[1]").first,
        ]
        clicked_x = False
        for factory in x_close_actions:
            locator = factory(page)
            try:
                await locator.wait_for(state="visible", timeout=300)
                await locator.click(timeout=700)
                clicked_x = True
                await page.wait_for_timeout(180)
                break
            except (PlaywrightTimeoutError, PlaywrightError):
                continue

        if clicked_x:
            if await self._is_chat_page_actionable(page, timeout_ms=900):
                self._log("步骤0/8完成：已通过X关闭开屏弹窗并恢复页面可交互。")
                return
        elif await self._is_chat_page_actionable(page, timeout_ms=700):
            self._log("步骤0/8完成：未检测到阻断弹窗。")
            return

        # 轻量兜底：不做多轮扫描，单次尝试 Esc 和遮罩点击。
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(120)
            if await self._is_chat_page_actionable(page, timeout_ms=700):
                self._log("步骤0/8完成：已通过Esc恢复页面可交互。")
                return
        except PlaywrightError:
            pass

        for selector in ("div[class*='mask']", "div[class*='overlay']", "div[class*='backdrop']"):
            mask = page.locator(selector).first
            try:
                await mask.wait_for(state="visible", timeout=200)
                await mask.click(timeout=500, position={"x": 10, "y": 10})
                await page.wait_for_timeout(120)
                if await self._is_chat_page_actionable(page, timeout_ms=700):
                    self._log("步骤0/8完成：已通过遮罩点击恢复页面可交互。")
                    return
                break
            except (PlaywrightTimeoutError, PlaywrightError):
                continue

        popup_snippets = await self._collect_visible_popup_texts(page)
        dialog_count, mask_count = await self._count_visible_blocking_layers(page)
        popup_desc = " | ".join(popup_snippets) if popup_snippets else "<未捕获到弹窗文案>"
        raise RuntimeError(
            f"[开屏弹窗检查] 页面仍不可交互。url={page.url}，dialog_count={dialog_count}，mask_count={mask_count}，可见弹窗文案={popup_desc}"
        )

    async def _get_chat_messages(self, page: Page) -> list[dict]:
        """读取真实消息节点，并区分用户消息、Dola回复和视频卡片。"""
        nodes = page.locator("main [data-message-id]")
        try:
            count = await nodes.count()
        except PlaywrightError:
            return []

        messages: list[dict] = []
        for index in range(count):
            node = nodes.nth(index)
            try:
                message_id = await node.get_attribute("data-message-id")
                if not message_id:
                    continue
                class_name = await node.get_attribute("class") or ""
                is_user = "justify-end" in class_name
                if not is_user:
                    is_user = (
                        await node.locator("div[class*='send-msg-bubble']").count() > 0
                    )
                text = re.sub(
                    r"\s+", " ", (await node.inner_text(timeout=1500)).strip()
                )
                has_video = (
                    await node.locator(
                        "div[class*='video-player-wrapper'], "
                        "div[class*='block-video'], video"
                    ).count()
                    > 0
                )
            except PlaywrightError:
                continue
            messages.append(
                {
                    "id": message_id,
                    "text": text,
                    "is_user": is_user,
                    "has_video": has_video,
                    "index": index,
                }
            )
        return messages

    async def _capture_submit_message_baseline(self, page: Page) -> None:
        messages = await self._get_chat_messages(page)
        self._submit_message_baseline_ids = {message["id"] for message in messages}
        self._message_snapshots = {
            message["id"]: (message["text"], message["has_video"])
            for message in messages
        }
        self._completion_message_id = None
        self._last_generation_state = "waiting"
        self._last_generation_text = ""
        self._log(
            f"提交前消息基线已记录，共 {len(self._submit_message_baseline_ids)} 条真实消息。"
        )

    async def _read_new_assistant_messages(self, page: Page) -> list[dict]:
        """只返回本次提交后新增或内容发生变化的Dola回复。"""
        messages = await self._get_chat_messages(page)
        changed_assistant_messages: list[dict] = []
        for message in messages:
            signature = (message["text"], message["has_video"])
            previous = self._message_snapshots.get(message["id"])
            changed = previous != signature
            self._message_snapshots[message["id"]] = signature
            if changed and not message["is_user"]:
                changed_assistant_messages.append(message)
        return changed_assistant_messages

    async def _send_blocked_appeal_once(self, page: Page, source: str) -> None:
        if self._blocked_appeal_sent:
            self._log(
                f"[branch] blocked_appeal: 已发送过申诉文案，跳过重复发送（source={source}）"
            )
            return

        self._log(
            f"[branch] blocked_appeal: 检测到阻断文案，发送一次性申诉文案（source={source}）"
        )
        await self._capture_submit_message_baseline(page)
        await self._fill_prompt(page, GENERATION_BLOCKED_APPEAL_MESSAGE)
        await self._submit_by_enter(page)
        self._blocked_appeal_sent = True
        self._log("[branch] blocked_appeal: 申诉文案发送完成（本任务后续不再重复发送）")
        await page.wait_for_timeout(800)

    async def _click_first(
        self,
        page: Page,
        locator_factories,
        step_name: str,
        wait_timeout_ms: int = 3500,
    ) -> None:
        last_error = None
        candidate_groups = []

        # 第一轮不等待：把所有选择器都快速扫一遍。新版元素已经显示时，
        # 不会因为前面的旧版兼容选择器不存在而逐个等待超时。
        for factory in locator_factories:
            try:
                candidates = factory(page)
                candidate_groups.append(candidates)
                count = await candidates.count()
                for index in range(count):
                    locator = candidates.nth(index)
                    if not await locator.is_visible():
                        continue
                    await locator.click(timeout=wait_timeout_ms)
                    return
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                last_error = e

        # 第二轮才等待异步渲染。Dola有时会同时保留一份隐藏的旧组件，
        # 因此候选存在时仍逐个检查可见性，不固定死盯第一个节点。
        for candidates in candidate_groups:
            try:
                count = await candidates.count()
                if count:
                    for index in range(count):
                        locator = candidates.nth(index)
                        try:
                            await locator.wait_for(
                                state="visible", timeout=wait_timeout_ms
                            )
                            await locator.click(timeout=wait_timeout_ms)
                            return
                        except (PlaywrightTimeoutError, PlaywrightError) as e:
                            last_error = e
                            continue
                    continue

                # 当前尚无节点时，等待该选择器的第一个异步出现。
                locator = candidates.first
                await locator.wait_for(state="visible", timeout=wait_timeout_ms)
                await locator.click(timeout=wait_timeout_ms)
                return
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                last_error = e
                continue

        visible_controls = []
        try:
            texts = await page.locator(
                "button, [role='button'], [role='menuitem'], [role='option'], [role='radio']"
            ).all_inner_texts()
            for text in texts:
                normalized = re.sub(r"\s+", " ", text).strip()
                if normalized and normalized not in visible_controls:
                    visible_controls.append(normalized)
                if len(visible_controls) >= 20:
                    break
        except PlaywrightError:
            pass

        controls_desc = " | ".join(visible_controls) if visible_controls else "<未读取到>"
        raise RuntimeError(
            f"[{step_name}] 未找到可点击元素。"
            f"当前可见控件: {controls_desc}。最后错误: {last_error}"
        )

    async def _try_click_first(
        self,
        page: Page,
        locator_factories,
        wait_timeout_ms: int = 900,
    ) -> bool:
        try:
            await self._click_first(
                page,
                locator_factories,
                step_name="兼容入口探测",
                wait_timeout_ms=wait_timeout_ms,
            )
            return True
        except RuntimeError:
            return False

    async def _click_video_generate_button(self, page: Page) -> None:
        await self._click_first(
            page,
            [
                lambda p: p.get_by_text("视频生成", exact=True),
                lambda p: p.get_by_role("button", name="视频生成"),
                lambda p: p.get_by_test_id("skill_bar_button_4"),
                lambda p: p.get_by_test_id("skill_bar_button_3"),
            ],
            step_name="点击视频生成",
        )

    async def _upload_reference_image(self, page: Page, reference_image_paths) -> None:
        if isinstance(reference_image_paths, (str, Path)):
            reference_image_paths = [Path(reference_image_paths)]
        else:
            reference_image_paths = [Path(p) for p in reference_image_paths]

        if not reference_image_paths:
            raise ValueError("参考图列表为空，请至少提供一张参考图。")

        missing_paths = [p for p in reference_image_paths if not p.exists()]
        if missing_paths:
            raise FileNotFoundError(f"参考图不存在: {missing_paths}")

        async def try_click(locator_factories, wait_timeout_ms: int = 2500) -> bool:
            for factory in locator_factories:
                locator = factory(page).first
                try:
                    await locator.wait_for(state="visible", timeout=wait_timeout_ms)
                    await locator.click(timeout=wait_timeout_ms)
                    return True
                except (PlaywrightTimeoutError, PlaywrightError):
                    continue
            return False

        plus_locator_factories = [
            lambda p: p.get_by_role("button", name="+"),
            lambda p: p.get_by_role("button", name="添加"),
            lambda p: p.locator("input[type='file']").first.locator("xpath=preceding-sibling::button[1]"),
            lambda p: p.locator("button:has(svg)").first,
        ]

        async def trigger_plus_file_chooser():
            self._log("步骤：点击加号上传按钮")
            async with page.expect_file_chooser() as fc_info:
                clicked = await try_click(plus_locator_factories)
                if not clicked:
                    raise RuntimeError("未找到加号上传入口，无法触发文件选择框。")
            return await fc_info.value

        total_images = len(reference_image_paths)
        if total_images == 1:
            file_chooser = await trigger_plus_file_chooser()
            self._log("步骤：文件选择框已弹出，开始上传单张参考图")
            await file_chooser.set_files([str(reference_image_paths[0])])
            self._log("步骤：单张参考图上传完成")
            return

        self._log(f"步骤：检测到 {total_images} 张参考图，先尝试一次性上传")
        try:
            file_chooser = await trigger_plus_file_chooser()
            self._log("步骤：文件选择框已弹出，开始多图一次性上传")
            await file_chooser.set_files([str(p) for p in reference_image_paths])
            if not file_chooser.is_multiple():
                raise RuntimeError("当前文件选择器不支持多选")
            self._log(f"步骤：多图一次性上传完成，共 {total_images} 张")
            return
        except Exception as exc:
            self._log(f"步骤：多图一次性上传失败，自动降级逐张上传。原因: {exc}")

        for index, image_path in enumerate(reference_image_paths, start=1):
            file_chooser = await trigger_plus_file_chooser()
            await file_chooser.set_files([str(image_path)])
            self._log(f"步骤：逐张上传完成 {index}/{total_images}: {image_path.name}")
            await page.wait_for_timeout(300)

        self._log(f"步骤：逐张上传已完成，共 {total_images} 张")

    async def _select_duration(self, page: Page, duration: str) -> None:
        duration_pattern = re.compile(
            rf"(?:时长\s*)?{re.escape(duration)}(?:\s*[⌄∨∧^])?",
            re.IGNORECASE,
        )
        await self._click_first(
            page,
            [
                lambda p: p.get_by_role("button", name=duration_pattern),
                lambda p: p.locator("button").filter(has_text=duration_pattern),
                lambda p: p.locator("[role='button']").filter(
                    has_text=duration_pattern
                ),
            ],
            step_name="打开时长菜单",
        )
        await page.wait_for_timeout(150)

        await self._click_first(
            page,
            [
                lambda p: p.get_by_role("option", name=duration, exact=True),
                lambda p: p.get_by_role("menuitem", name=duration, exact=True),
                lambda p: p.locator(
                    "[role='menu'], [role='listbox'], div[class*='popover'], "
                    "div[class*='dropdown'], div[class*='popup']"
                ).get_by_text(duration, exact=True),
                # 菜单中的选项通常位于触发按钮之后，倒序可避开底部的当前值。
                lambda p: p.get_by_text(duration, exact=True).last,
            ],
            step_name=f"选择时长 {duration}",
        )

    async def _select_ratio(self, page: Page, ratio: str) -> None:
        ratio_options = [
            lambda p: p.get_by_role("radio", name=ratio, exact=True),
            lambda p: p.get_by_role("option", name=ratio, exact=True),
            lambda p: p.get_by_role("menuitem", name=ratio, exact=True),
            lambda p: p.locator(
                "[role='dialog'], [role='menu'], div[class*='popover'], "
                "div[class*='dropdown'], div[class*='popup']"
            ).get_by_text(ratio, exact=True),
            lambda p: p.get_by_role("button", name=ratio, exact=True),
            lambda p: p.get_by_text(ratio, exact=True).last,
        ]

        # Dola的比例是独立菜单，入口显示“比例”，与时长菜单分开。
        await self._click_first(
            page,
            [
                lambda p: p.get_by_role(
                    "button", name=re.compile(r"^比例(?:\s*[⌄∨∧^])?$")
                ),
                lambda p: p.locator("button").filter(
                    has_text=re.compile(r"^比例(?:\s*[⌄∨∧^])?$")
                ),
                lambda p: p.get_by_text("比例", exact=True),
            ],
            step_name="打开比例菜单",
        )
        await page.wait_for_timeout(150)
        await self._click_first(
            page,
            ratio_options,
            step_name=f"选择比例 {ratio}",
        )

    async def _select_model(self, page: Page, model_name: str) -> None:
        model_aliases = {
            "Seedance 2.0 Fast": "Dreamina Seedance 2.0 Fast",
            "Seedance 2.5": "Dreamina Seedance 2.5",
            "Seedance 1.0": "Dreamina Seedance 1.0",
        }
        target_model_name = model_aliases.get(model_name, model_name)
        current_model_pattern = re.compile(
            r"(?:模型\s*)?(?:Dreamina\s*)?Seedance\s*2\.0\s*Fast",
            re.IGNORECASE,
        )
        await self._click_first(
            page,
            [
                lambda p: p.get_by_role("button", name=current_model_pattern),
                lambda p: p.locator("button").filter(has_text=current_model_pattern),
                lambda p: p.locator("[role='button']").filter(
                    has_text=current_model_pattern
                ),
                lambda p: p.get_by_text("模型", exact=True),
                lambda p: p.get_by_role("button", name="模型"),
            ],
            step_name="打开模型面板",
        )

        await self._click_first(
            page,
            [
                lambda p: p.get_by_text(target_model_name, exact=True),
                lambda p: p.get_by_role("menuitem", name=target_model_name),
                lambda p: p.get_by_role("option", name=target_model_name),
                lambda p: p.get_by_role("button", name=target_model_name),
            ],
            step_name=f"选择模型 {target_model_name}",
        )

    async def _fill_prompt(self, page: Page, prompt: str) -> None:
        try:
            locator = page.get_by_test_id("chat_input_input").first
            await locator.wait_for(state="visible", timeout=5000)
            await locator.fill(prompt)
            return
        except (PlaywrightTimeoutError, PlaywrightError):
            pass

        await self._click_first(
            page,
            [
                lambda p: p.get_by_placeholder(re.compile(r"发消息")),
                lambda p: p.get_by_role("textbox"),
            ],
            step_name="定位输入框",
        )
        await page.get_by_role("textbox").first.fill(prompt)

    async def _confirm_safety_notice_if_present(
        self, page: Page, timeout_ms: int = 5000
    ) -> None:
        title = page.get_by_text("安全确认", exact=True).filter(visible=True).first
        try:
            await title.wait_for(state="visible", timeout=timeout_ms)
        except (PlaywrightTimeoutError, PlaywrightError):
            self._log("提交后未出现安全确认弹窗，继续运行。")
            return

        self._log("检测到安全确认弹窗，自动点击“确认”。")
        await self._click_first(
            page,
            [
                lambda p: p.get_by_role("dialog").filter(has_text="安全确认").get_by_role(
                    "button", name="确认", exact=True
                ),
                lambda p: p.locator("div[class*='modal']").filter(
                    has_text="安全确认"
                ).get_by_role("button", name="确认", exact=True),
                lambda p: title.locator(
                    "xpath=ancestor::*[@role='dialog' or contains(@class, 'modal')][1]"
                ).get_by_text("确认", exact=True),
                lambda p: p.get_by_role("button", name="确认", exact=True),
            ],
            step_name="确认安全提示",
            wait_timeout_ms=3000,
        )
        try:
            await title.wait_for(state="hidden", timeout=3000)
        except (PlaywrightTimeoutError, PlaywrightError):
            pass
        self._log("安全确认已完成。")

    async def _submit_by_enter(self, page: Page) -> None:
        # 你已确认当前页面可用 Enter 触发提交，优先使用该方式避免按钮定位失败。
        try:
            input_box = page.get_by_test_id("chat_input_input").first
            await input_box.wait_for(state="visible", timeout=5000)
            await input_box.press("Enter")
        except (PlaywrightTimeoutError, PlaywrightError):
            input_box = page.get_by_role("textbox").first
            await input_box.wait_for(state="visible", timeout=5000)
            await input_box.press("Enter")

        await self._confirm_safety_notice_if_present(page)

    async def _open_video_preview(
        self, page: Page, message_id: str | None = None
    ) -> None:
        # 只使用已验证稳定的视频组件选择器。
        selector = "div[class*='video-player-wrapper']"
        last_error = None

        if message_id:
            message_box = page.locator(
                f'main [data-message-id="{message_id}"]'
            ).first
            candidates = message_box.locator(selector)
        else:
            candidates = page.locator(selector)
        count = await candidates.count()
        # self._log(f"步骤：检测到可点击视频卡片数量 {count}")
        if count == 0:
            raise RuntimeError("[点击视频缩略图进入预览] 未找到可点击视频卡片。")

        if ONLY_CLICK_LATEST_VIDEO:
            idx = count - 1
            locator = candidates.nth(idx)
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
                await locator.wait_for(state="visible", timeout=2500)
                await locator.click(timeout=2500)
                self._log("步骤：已点击最新视频卡片")
                return
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                last_error = e
        else:
            # 兼容回退模式：必要时可改为遍历点击历史候选。
            for idx in range(count - 1, -1, -1):
                locator = candidates.nth(idx)
                try:
                    await locator.scroll_into_view_if_needed(timeout=2000)
                    await locator.wait_for(state="visible", timeout=2500)
                    await locator.click(timeout=2500)
                    self._log("步骤：已点击视频卡片")
                    return
                except (PlaywrightTimeoutError, PlaywrightError) as e:
                    last_error = e
                    continue

        raise RuntimeError(f"[点击视频缩略图进入预览] 未找到可点击视频组件。最后错误: {last_error}")

    async def _click_save_in_preview(self, page: Page) -> None:
        try:
            await self._click_first(
                page,
                [
                    lambda p: p.get_by_role(
                        "button", name=re.compile(r"^(?:保存|下载)$")
                    ),
                    lambda p: p.locator(
                        "button[aria-label*='下载'], button[title*='下载'], "
                        "button[data-testid*='download' i]"
                    ),
                    # 兼容旧版图标路径和按钮样式。
                    lambda p: p.locator(
                        "button:has(svg path[d^='M20.375 14.8535'])"
                    ),
                    lambda p: p.locator(
                        "button[class*='bg-dbx-fill-highlight']:has(svg)"
                    ),
                    lambda p: p.get_by_text("保存", exact=True),
                    lambda p: p.get_by_text("下载", exact=True),
                ],
                step_name="点击预览右上角下载",
                wait_timeout_ms=1800,
            )
            return
        except RuntimeError as semantic_error:
            semantic_error_text = str(semantic_error)
            self._log(
                "预览下载按钮没有可用文字或稳定属性，改用右上角蓝色图标定位。"
            )

        # Dola当前预览层的下载按钮是右上角蓝色圆形图标，没有文字，且SVG
        # 路径会随版本变化。仅在语义选择器全部失效后，根据预览工具栏的位置、
        # 尺寸和蓝色背景评分，避免误点最右侧的关闭按钮。
        viewport = await page.evaluate(
            "() => ({ width: window.innerWidth, height: window.innerHeight })"
        )
        icon_buttons = page.locator("button:has(svg), [role='button']:has(svg)")
        candidates = []
        count = await icon_buttons.count()
        for index in range(count):
            button = icon_buttons.nth(index)
            try:
                if not await button.is_visible():
                    continue
                box = await button.bounding_box()
                if not box:
                    continue
                right_gap = viewport["width"] - box["x"] - box["width"]
                if (
                    box["x"] < viewport["width"] * 0.55
                    or box["y"] > min(180, viewport["height"] * 0.28)
                    or box["width"] < 20
                    or box["height"] < 20
                    or box["width"] > 72
                    or box["height"] > 72
                ):
                    continue
                attributes = await button.evaluate(
                    """element => ({
                        aria: element.getAttribute('aria-label') || '',
                        title: element.getAttribute('title') || '',
                        testid: element.getAttribute('data-testid') || '',
                        className: typeof element.className === 'string' ? element.className : '',
                        background: getComputedStyle(element).backgroundColor,
                        color: getComputedStyle(element).color
                    })"""
                )
                description = " ".join(
                    str(attributes.get(key, ""))
                    for key in ("aria", "title", "testid", "className")
                ).lower()
                if re.search(r"关闭|close", description, re.IGNORECASE):
                    continue

                background = str(attributes.get("background", ""))
                rgb_match = re.search(
                    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", background
                )
                is_blue = False
                if rgb_match:
                    red, green, blue = map(int, rgb_match.groups())
                    is_blue = blue >= red + 25 and blue >= green + 5

                score = 0
                if re.search(r"下载|download|保存|save", description, re.IGNORECASE):
                    score += 100
                if is_blue:
                    score += 50
                if 32 <= right_gap <= 130:
                    score += 25
                if box["y"] <= 140:
                    score += 10
                if right_gap < 24:
                    score -= 40
                candidates.append((score, index, box, attributes))
            except PlaywrightError:
                continue

        if not candidates:
            raise RuntimeError(
                f"[点击预览右上角下载] 未找到符合位置和尺寸的图标按钮。"
                f"语义定位错误: {semantic_error_text}"
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        score, index, box, attributes = candidates[0]
        if score < 35:
            raise RuntimeError(
                "[点击预览右上角下载] 找到了图标按钮，但没有足够证据确认它是下载按钮。"
                f"候选位置={box}，候选属性={attributes}"
            )
        await icon_buttons.nth(index).click(timeout=5000)
        self._log(
            f"已点击预览右上角下载图标（score={score}，right_gap="
            f"{viewport['width'] - box['x'] - box['width']:.0f}px）。"
        )

    async def _close_preview_if_open(self, page: Page) -> None:
        try:
            await self._click_first(
                page,
                [
                    lambda p: p.get_by_role("button", name="关闭"),
                    lambda p: p.get_by_text("关闭", exact=True),
                    lambda p: p.locator("button").filter(has_text="").nth(1),
                ],
                step_name="关闭预览层",
                wait_timeout_ms=1200,
            )
            await page.wait_for_timeout(500)
        except Exception:
            # 如果当前不在预览层或没有关闭按钮，直接忽略
            return

    async def _download_message_video(
        self,
        page: Page,
        message_id: str,
        save_dir: Path,
        theme: str,
    ) -> Path:
        await self._open_video_preview(page, message_id=message_id)
        self._log(f"已进入本次任务的视频预览，message_id={message_id}。")
        # 预览播放器仍在转圈时，Dola的原片下载通常已经可用；下载事件偶尔
        # 会延迟，因此不要用过短超时误判为失败并重新打开预览。
        async with page.expect_download(timeout=45000) as download_info:
            await self._click_save_in_preview(page)
        download = await download_info.value
        readable_time = time.strftime("%Y%m%d_%H%M%S")
        filename = f"dola_{theme}_{readable_time}_{download.suggested_filename or 'dola_video.mp4'}"
        target_path = save_dir / filename
        await download.save_as(str(target_path))
        self._log(f"检测到下载事件，视频已保存到: {target_path}")
        return target_path

    async def _download_video(
        self,
        page: Page,
        save_dir: Path,
        theme: str,
        total_wait_seconds: int = DOWNLOAD_TOTAL_WAIT_SECONDS,
        poll_interval_seconds: int = STATE_POLL_INTERVAL_SECONDS,
        refresh_interval_seconds: int = PAGE_REFRESH_INTERVAL_SECONDS,
    ) -> Path:
        save_dir.mkdir(parents=True, exist_ok=True)
        start_ts = time.time()
        last_refresh_ts = time.time()
        attempt = 0

        while time.time() - start_ts < total_wait_seconds:
            round_start = time.time()
            attempt += 1
            elapsed_seconds = int(round_start - start_ts)
            elapsed_minutes = elapsed_seconds / 60
            total_wait_minutes = total_wait_seconds / 60
            self._log(
                f"第 {attempt} 轮下载检测开始（已等待 {elapsed_minutes:.1f} 分钟 / 最多 {total_wait_minutes:.1f} 分钟）"
            )
            # 完成消息一旦出现，就不再刷新会话页。刷新会关闭预览并让播放器
            # 从头加载，造成“转圈 -> 刷回去 -> 再来一遍”的循环。
            if (
                not self._completion_message_id
                and round_start - last_refresh_ts >= refresh_interval_seconds
            ):
                self._log("[branch] refresh_round: 到达刷新间隔，执行page.reload刷新页面")
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(1200)
                    self._log("[branch] refresh_round: page.reload刷新完成，页面已稳定")
                except PlaywrightTimeoutError as e:
                    self._log(
                        f"[branch] refresh_round: page.reload等待超时，继续后续流程，error={e}"
                    )
                except PlaywrightError as e:
                    self._log(
                        f"[branch] refresh_round: page.reload触发失败，继续后续流程，error={e}"
                    )
                finally:
                    last_refresh_ts = time.time()
            new_messages = await self._read_new_assistant_messages(page)
            state, state_message = self._select_generation_event(new_messages)
            if state_message:
                self._last_generation_state = state
                self._last_generation_text = state_message["text"]
                self._log(
                    f"状态识别：{state}，message_id={state_message['id']}，"
                    f"文本={self._preview_text(state_message['text'])}"
                )

            if state == "completed" and state_message:
                self._completion_message_id = state_message["id"]
            elif state == "quota_exhausted":
                raise QuotaExhaustedError(
                    f"当前账号今日额度已用尽: {self._last_generation_text}"
                )
            elif state == "blocked":
                if self._blocked_appeal_sent:
                    raise ContentBlockedError(
                        f"内容明确违规，申诉一次后仍未通过: {self._last_generation_text}"
                    )
                await self._send_blocked_appeal_once(
                    page, source=f"message_id={state_message['id']}"
                )
                self._last_generation_state = "waiting_after_appeal"
                self._last_generation_text = "已发送一次申诉，等待Dola重新判断。"
                # Dola可能先排队十分钟后才返回版权/违规。申诉相当于一次新的
                # 生成等待阶段，应重新给予完整等待窗口，不能沿用已经消耗的时间。
                start_ts = time.time()
                last_refresh_ts = time.time()
                attempt = 0
                self._log(
                    f"检测到延迟违规并已申诉，重新计算最多 "
                    f"{total_wait_seconds / 60:.1f} 分钟等待时间。"
                )
            elif state == "transient_failure":
                raise VideoGenerateFailedError(
                    f"Dola返回临时生成失败，可按任务重试规则重试: {self._last_generation_text}"
                )
            elif state == "accepted":
                self._log("任务已被Dola受理，继续等待生成，绝不重复提交。")
            elif state == "unknown":
                if self._blocked_appeal_sent:
                    raise ContentBlockedError(
                        "内容被拒绝后已申诉一次，但Dola返回了未识别回复，"
                        f"当前视频任务停止且不再更换账号重试: {self._last_generation_text}"
                    )
                self._log("出现未识别Dola回复，仅记录并继续等待，不申诉、不重提。")
            else:
                self._log(
                    f"本轮没有新Dola回复，保持状态 {self._last_generation_state}，继续等待。"
                )

            if self._completion_message_id:
                self._log("检测到本次任务完成，开始下载对应消息中的视频。")
                try:
                    return await self._download_message_video(
                        page,
                        message_id=self._completion_message_id,
                        save_dir=save_dir,
                        theme=theme,
                    )
                except (PlaywrightTimeoutError, RuntimeError, PlaywrightError) as e:
                    self._log(
                        f"完成消息已出现，但本轮下载尚未成功，稍后重试: {e}"
                    )
                    await self._close_preview_if_open(page)

            round_spent = time.time() - round_start
            wait_seconds = max(0, poll_interval_seconds - round_spent)
            if wait_seconds > 0:
                await page.wait_for_timeout(int(wait_seconds * 1000))

        raise TimeoutError(
            "等待视频生成或下载超时。"
            f"最后状态={self._last_generation_state}，"
            f"最后Dola回复={self._preview_text(self._last_generation_text)}"
        )

    async def upload_video_with_ref(
        self,
        playwright: Playwright,
        prompt: str,
        reference_image_paths,
        ratio: str,
        save_dir: Path,
        theme: str,
        headless: bool = False,
        model_name: str = MODEL_NAME,
        duration: str = VIDEO_DURATION,
    ) -> Path:
        if self.local_executable_path:
            browser = await playwright.chromium.launch(
                headless=headless,
                executable_path=self.local_executable_path,
            )
        else:
            browser = await playwright.chromium.launch(headless=headless)

        context = await browser.new_context(storage_state=str(self.account_file))
        context = await set_init_script(context)
        page = await context.new_page()
        self._submit_message_baseline_ids = set()
        self._message_snapshots = {}
        self._completion_message_id = None
        self._last_generation_state = "waiting"
        self._last_generation_text = ""
        self._blocked_appeal_sent = False
        self._startup_popup_handled = False
        self._log("已打开新页面，准备进入Dola。")
        await page.goto("https://www.dola.com/chat/", timeout=60000)
        await page.wait_for_timeout(1500)
        await self._dismiss_startup_blocking_popup_once(page)

        try:
            self._log("步骤1/8：点击“视频生成”入口。")
            await self._click_video_generate_button(page)
            await page.wait_for_timeout(500)
            self._log("步骤1/8完成。")

            self._log(f"步骤2/8：选择模型 {model_name}。")
            await self._select_model(page, model_name)
            await page.wait_for_timeout(500)
            self._log("步骤2/8完成。")

            self._log(f"步骤3/8：选择时长 {duration}。")
            await self._select_duration(page, duration)
            await page.wait_for_timeout(300)
            self._log("步骤3/8完成。")

            self._log(f"步骤4/8：选择比例 {ratio}。")
            await self._select_ratio(page, ratio)
            await page.wait_for_timeout(300)
            self._log("步骤4/8完成。")

            self._log("步骤5/8：上传参考图。")
            await self._upload_reference_image(page, reference_image_paths)
            await page.wait_for_timeout(500)
            self._log("步骤5/8完成。")

            self._log("步骤6/8：填写提示词。")
            await self._fill_prompt(page, prompt)
            await page.wait_for_timeout(500)
            self._log("步骤6/8完成。")

            self._log("步骤7/8：按回车提交视频任务。")
            await self._capture_submit_message_baseline(page)
            await self._submit_by_enter(page)
            self._log("步骤7/8完成。")
            self._log(
                f"步骤7.5/8：已提交任务，先等待 {INITIAL_STATE_WAIT_SECONDS} 秒再开始首次检测。"
            )
            await page.wait_for_timeout(INITIAL_STATE_WAIT_SECONDS * 1000)

            self._log(
                f"步骤8/8：等待视频生成并轮询下载（每 {STATE_POLL_INTERVAL_SECONDS} 秒检查状态，"
                f"每 {PAGE_REFRESH_INTERVAL_SECONDS} 秒刷新页面，最多 "
                f"{DOWNLOAD_TOTAL_WAIT_SECONDS / 60:.1f} 分钟）。"
            )
            downloaded_file = await self._download_video(page, save_dir, theme)
            self._log("步骤8/8完成。")

            await context.storage_state(path=str(self.account_file))
            self._log("Cookie 状态已保存，流程结束。")
            return downloaded_file
        finally:
            await context.close()
            await browser.close()

    async def main(
        self,
        prompt: str,
        reference_image_paths,
        ratio: str,
        save_dir: Path,
        theme: str,
        headless: bool = False,
        model_name: str = MODEL_NAME,
        duration: str = VIDEO_DURATION,
    ) -> Path:
        async with async_playwright() as playwright:
            return await self.upload_video_with_ref(
                playwright=playwright,
                prompt=prompt,
                reference_image_paths=reference_image_paths,
                ratio=ratio,
                save_dir=save_dir,
                theme=theme,
                headless=headless,
                model_name=model_name,
                duration=duration,
            )


if __name__ == "__main__":
    generator = DolaVideoGenerator(account_file=ACCOUNT_FILE)
    result = asyncio.run(
        generator.main(
            prompt=PROMPT,
            reference_image_paths=REFERENCE_IMAGE_PATHS,
            ratio=RATIO,
            save_dir=SAVE_DIR,
            theme=THEME,
            headless=HEADLESS,
        ),
        debug=False,
    )
    print(f"视频下载完成: {result}")
