from __future__ import annotations

import asyncio
import copy
import shutil
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dola_blur import blur_video_inplace as blur_dola_video_inplace
from dola_video import (
    ContentBlockedError as DolaContentBlockedError,
    DolaVideoGenerator,
    QuotaExhaustedError as DolaQuotaExhaustedError,
)
from doubao_video import (
    ContentBlockedError as DoubaoContentBlockedError,
    DoubaoVideoGenerator,
    QuotaExhaustedError as DoubaoQuotaExhaustedError,
)
from 加模糊 import blur_video_inplace as blur_doubao_video_inplace

from .storage import (
    RUNTIME_DIR,
    AccountStore,
    PlatformSettingsStore,
    RuntimeStore,
    TaskStore,
    now_iso,
    safe_filename,
)
from .runtime_log import bind_log_context, log_event


FINAL_JOB_STATES = {"completed", "failed", "cancelled", "interrupted"}
VIDEO_GENERATORS = {
    "doubao": DoubaoVideoGenerator,
    "dola": DolaVideoGenerator,
}
VIDEO_BLUR_HANDLERS = {
    "doubao": blur_doubao_video_inplace,
    "dola": blur_dola_video_inplace,
}
QUOTA_EXHAUSTED_ERRORS = (DoubaoQuotaExhaustedError, DolaQuotaExhaustedError)
CONTENT_BLOCKED_ERRORS = (DoubaoContentBlockedError, DolaContentBlockedError)


class TaskRunner:
    def __init__(
        self,
        account_store: AccountStore,
        task_store: TaskStore,
        runtime_store: RuntimeStore,
        platform_settings_store: PlatformSettingsStore,
    ) -> None:
        self.account_store = account_store
        self.task_store = task_store
        self.runtime_store = runtime_store
        self.platform_settings_store = platform_settings_store
        self.pending: list[dict[str, Any]] = []
        self.run_states: dict[str, dict[str, Any]] = {}
        self.run_order: list[str] = []
        self.queue_event = asyncio.Event()
        self.queue_running = False
        self.single_run_id: str | None = None
        self.orchestrator_task: asyncio.Task | None = None
        self.scheduler_task: asyncio.Task | None = None
        self.active_execution: asyncio.Task | None = None
        self.active_request: dict[str, Any] | None = None
        self.direct_execution: asyncio.Task | None = None
        self.direct_request: dict[str, Any] | None = None
        self.direct_state: dict[str, Any] | None = None
        self.state_lock = asyncio.Lock()
        self.stopping = False

    async def start(self) -> None:
        self.runtime_store.mark_interrupted_if_needed()
        previous = self.runtime_store.get()
        history = self.runtime_store.list_history()
        previous_run_id = previous.get("run_id")
        if previous_run_id and not any(
            item.get("run_id") == previous_run_id for item in history
        ):
            history.append(previous)
        for saved_state in history:
            run_id = saved_state.get("run_id")
            if not run_id:
                continue
            # 兼容旧版“立即执行”记录；新版全部归入统一任务队列。
            saved_state.pop("is_direct", None)
            self.run_states[run_id] = saved_state
            self.run_order.append(run_id)
            if saved_state.get("status") in {"queued", "stopped"}:
                try:
                    task = self.task_store.get(saved_state["task_id"])
                    task_snapshot, assets_dir = self._snapshot_task(task, run_id)
                    self.pending.append(
                        {
                            "run_id": run_id,
                            "task_id": task["id"],
                            "task_name": saved_state.get("task_name", task["name"]),
                            "source": saved_state.get("source", "manual"),
                            "requested_at": saved_state.get("requested_at", now_iso()),
                            "task_snapshot": task_snapshot,
                            "assets_dir": str(assets_dir),
                            "priority": bool(saved_state.get("priority", False)),
                        }
                    )
                except Exception as exc:
                    saved_state["status"] = "interrupted"
                    saved_state["message"] = f"服务重启后无法恢复任务配置: {exc}"
                    saved_state["finished_at"] = now_iso()
        self.runtime_store.save_history(
            [self.run_states[run_id] for run_id in self.run_order]
        )
        self.stopping = False
        self.orchestrator_task = asyncio.create_task(self._orchestrator())
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        log_event(
            f"[RESULT] 任务运行器已启动 | 恢复运行记录={len(self.run_states)} | 等待队列={len(self.pending)}",
            level="SUCCESS",
        )

    async def stop(self) -> None:
        log_event("[ACTION] 正在停止任务运行器及后台调度。")
        self.stopping = True
        if self.scheduler_task:
            self.scheduler_task.cancel()
        if self.active_execution and not self.active_execution.done():
            self.active_execution.cancel()
        if self.direct_execution and not self.direct_execution.done():
            self.direct_execution.cancel()
        if self.orchestrator_task:
            self.orchestrator_task.cancel()
        tasks = [
            task
            for task in (
                self.scheduler_task,
                self.active_execution,
                self.direct_execution,
                self.orchestrator_task,
            )
            if task is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        log_event("[RESULT] 任务运行器已停止。", level="SUCCESS")

    def _snapshot_task(self, task: dict[str, Any], run_id: str) -> tuple[dict[str, Any], Path]:
        """冻结排队时的任务配置和参考图，后续编辑/删除模板不影响本次运行。"""
        snapshot = copy.deepcopy(task)
        assets_dir = (RUNTIME_DIR / "queue_assets" / run_id).resolve()
        assets_dir.mkdir(parents=True, exist_ok=True)
        copied_images: list[str] = []
        for index, raw_path in enumerate(task.get("images", []), start=1):
            source = Path(raw_path)
            if not source.exists() or not source.is_file():
                raise ValueError(f"参考图片不存在: {source}")
            target = assets_dir / f"{index:02d}_{safe_filename(source.name, 'image')}"
            shutil.copy2(source, target)
            copied_images.append(str(target))
        snapshot["images"] = copied_images
        return snapshot, assets_dir

    @staticmethod
    def _cleanup_request_assets(request: dict[str, Any]) -> None:
        raw_path = request.get("assets_dir")
        if not raw_path:
            return
        assets_dir = Path(raw_path).resolve()
        allowed_root = (RUNTIME_DIR / "queue_assets").resolve()
        try:
            assets_dir.relative_to(allowed_root)
        except ValueError:
            return
        if assets_dir.exists():
            shutil.rmtree(assets_dir)

    async def enqueue(
        self,
        task_id: str,
        source: str = "manual",
        auto_start: bool = False,
        priority: bool = False,
    ) -> dict[str, Any]:
        task = self.task_store.get(task_id)
        run_id = uuid.uuid4().hex
        task_snapshot, assets_dir = self._snapshot_task(task, run_id)
        request = {
            "run_id": run_id,
            "task_id": task_id,
            "task_name": task["name"],
            "source": source,
            "requested_at": now_iso(),
            "task_snapshot": task_snapshot,
            "assets_dir": str(assets_dir),
            "priority": priority,
        }
        run_state = {
            "run_id": run_id,
            "task_id": task_id,
            "task_name": task["name"],
            "source": source,
            "priority": priority,
            "status": "queued",
            "message": "任务正在队列中等待。",
            "requested_at": request["requested_at"],
            "total_count": int(task["count"]),
            "completed_count": 0,
            "failed_count": 0,
            "output_dir": task["output_dir"],
            "jobs": [],
        }
        if priority:
            self.pending.insert(0, request)
        else:
            self.pending.append(request)
        self.run_states[run_id] = run_state
        self.run_order.append(run_id)
        self.runtime_store.write(run_state)
        log_event(
            f"[ACTION] 任务已加入运行队列 | 来源={source} | 数量={task['count']} | 优先执行={priority}",
            run_id=run_id[:8],
            task_name=task["name"],
        )
        if auto_start:
            self.queue_running = True
        if self.queue_running:
            self.queue_event.set()
        return {key: value for key, value in request.items() if key not in {"task_snapshot", "assets_dir"}}

    async def run_direct(self, task_id: str, source: str = "manual") -> dict[str, Any]:
        if self.queue_running or (
            self.active_execution and not self.active_execution.done()
        ):
            raise ValueError("已有任务正在运行，请等待结束后再点击立即运行")

        # “立即运行”插到统一队列最前面，但只执行这一条。完成后调度器
        # 自动暂停，其他任务仍保持原来的排队状态。
        queued = await self.enqueue(
            task_id,
            source="immediate",
            auto_start=False,
            priority=True,
        )
        self.single_run_id = queued["run_id"]
        self.queue_running = True
        self.queue_event.set()
        return queued

    async def _run_direct(self, request: dict[str, Any]) -> None:
        try:
            await self._execute(request)
        finally:
            self._cleanup_request_assets(request)
            self.direct_request = None
            self.direct_execution = None

    async def start_queue(self) -> None:
        self.single_run_id = None
        if self.active_execution and not self.active_execution.done():
            self.queue_running = True
            return
        if not any(
            self.run_states.get(item["run_id"], {}).get("status") == "queued"
            for item in self.pending
        ):
            raise ValueError("任务队列中没有处于排队状态的任务")
        self.queue_running = True
        self.queue_event.set()
        log_event(f"[ACTION] 用户启动全部队列 | 待处理任务={len(self.pending)}")

    async def stop_queue(self) -> None:
        has_queue_task = self.active_execution and not self.active_execution.done()
        if not self.queue_running and not has_queue_task:
            raise ValueError("任务队列当前没有运行")
        self.queue_running = False
        log_event("[ACTION] 用户请求停止全部队列。", level="WARNING")
        self.queue_event.clear()
        self.single_run_id = None
        if has_queue_task:
            state = self.run_states.get(self.active_request["run_id"]) if self.active_request else None
            if state:
                state["status"] = "cancelling"
                state["message"] = "正在停止当前任务并暂停队列……"
                self.runtime_store.write(state)
            self.active_execution.cancel()

    async def start_run(self, run_id: str) -> None:
        state = self.run_states.get(run_id)
        if not state:
            raise KeyError("队列任务不存在")
        if state.get("status") != "stopped":
            raise ValueError("只有已停止的任务可以恢复排队")
        if not any(item["run_id"] == run_id for item in self.pending):
            raise ValueError("这个任务已经结束，不能恢复排队")
        state["status"] = "queued"
        state["message"] = "任务已恢复排队，等待全部运行。"
        self.runtime_store.write(state)
        log_event(
            "[ACTION] 用户启动单个运行任务。",
            run_id=run_id[:8],
            task_name=state.get("task_name", ""),
        )
        if self.queue_running:
            self.queue_event.set()

    async def stop_run(self, run_id: str) -> None:
        state = self.run_states.get(run_id)
        if not state:
            raise KeyError("队列任务不存在")
        status = state.get("status")
        if status == "queued":
            state["status"] = "stopped"
            state["message"] = "任务已停止排队。"
            self.runtime_store.write(state)
            log_event(
                "[DECISION] 排队任务尚未开始，已直接标记停止。",
                level="WARNING",
                run_id=run_id[:8],
                task_name=state.get("task_name", ""),
            )
            if not self.active_request and not any(
                self.run_states.get(item["run_id"], {}).get("status") == "queued"
                for item in self.pending
            ):
                self.queue_running = False
                self.queue_event.clear()
            return
        if status in {"running", "cancelling"} and self.active_request and (
            self.active_request["run_id"] == run_id
        ):
            log_event(
                "[ACTION] 用户请求停止正在执行的任务。",
                level="WARNING",
                run_id=run_id[:8],
                task_name=state.get("task_name", ""),
            )
            await self.stop_queue()
            return
        raise ValueError("这个状态的任务不能停止")

    async def reorder_runs(self, run_ids: list[str]) -> None:
        movable_ids = [
            item["run_id"]
            for item in self.pending
            if self.run_states.get(item["run_id"], {}).get("status")
            in {"queued", "stopped"}
        ]
        requested = [run_id for run_id in run_ids if run_id in movable_ids]
        if len(requested) != len(movable_ids) or set(requested) != set(movable_ids):
            raise ValueError("拖拽顺序与当前可排序任务不一致，请刷新页面后重试")
        request_map = {item["run_id"]: item for item in self.pending}
        locked = [item for item in self.pending if item["run_id"] not in movable_ids]
        self.pending = [request_map[run_id] for run_id in requested] + locked

    async def delete_run(self, run_id: str) -> None:
        request = next((item for item in self.pending if item["run_id"] == run_id), None)
        if request:
            self.pending = [item for item in self.pending if item["run_id"] != run_id]
            self._cleanup_request_assets(request)
        elif self.active_request and self.active_request["run_id"] == run_id:
            self.queue_running = False
            self.queue_event.clear()
            if self.active_execution and not self.active_execution.done():
                self.active_execution.cancel()
        elif run_id not in self.run_states:
            raise KeyError("队列任务不存在")

        self.run_states.pop(run_id, None)
        self.run_order = [item for item in self.run_order if item != run_id]
        self.runtime_store.delete_history(run_id)
        if not self.pending and not (
            self.active_execution and not self.active_execution.done()
        ):
            self.queue_running = False
            self.queue_event.clear()

    def snapshot(self) -> dict[str, Any]:
        active_run_id = self.active_request["run_id"] if self.active_request else None
        if active_run_id not in self.run_states:
            active_run_id = None
        pending_ids = [item["run_id"] for item in self.pending]
        ordered_ids = []
        if active_run_id:
            ordered_ids.append(active_run_id)
        ordered_ids.extend(run_id for run_id in pending_ids if run_id != active_run_id)
        ordered_ids.extend(
            run_id
            for run_id in self.run_order
            if run_id not in ordered_ids and run_id in self.run_states
        )
        visible_states = [self.run_states[run_id] for run_id in ordered_ids]
        if active_run_id:
            base = dict(self.run_states[active_run_id])
        elif visible_states:
            base = dict(visible_states[-1])
        else:
            base = {"status": "idle", "message": "当前没有排队或运行中的任务。", "jobs": []}
        base["queue_running"] = self.queue_running
        base["active_run_id"] = active_run_id
        base["single_run_id"] = self.single_run_id
        base["queue_runs"] = visible_states
        base["direct_active"] = False
        base["direct_run"] = None
        base["direct_runs"] = []
        return base

    async def _orchestrator(self) -> None:
        while True:
            await self.queue_event.wait()
            if not self.queue_running:
                self.queue_event.clear()
                continue
            request = next(
                (
                    item
                    for item in self.pending
                    if self.run_states.get(item["run_id"], {}).get("status") == "queued"
                ),
                None,
            )
            if request is None:
                self.queue_running = False
                self.queue_event.clear()
                continue

            self.pending = [
                item for item in self.pending if item["run_id"] != request["run_id"]
            ]
            self.active_request = request
            self.active_execution = asyncio.create_task(self._execute(request))
            try:
                await self.active_execution
            except asyncio.CancelledError:
                if self.stopping:
                    raise
            finally:
                run_id = request["run_id"]
                single_run_finished = self.single_run_id == run_id
                run_state = self.run_states.get(run_id)
                if run_state and run_state.get("status") == "stopped":
                    if not any(item["run_id"] == run_id for item in self.pending):
                        self.pending.insert(0, request)
                else:
                    self._cleanup_request_assets(request)
                self.active_execution = None
                self.active_request = None
                if single_run_finished:
                    self.single_run_id = None
                    self.queue_running = False
                    self.queue_event.clear()
                else:
                    has_queued = any(
                        self.run_states.get(item["run_id"], {}).get("status") == "queued"
                        for item in self.pending
                    )
                    if not self.queue_running or not has_queued:
                        self.queue_running = False
                        self.queue_event.clear()

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                for task in self.task_store.list():
                    if task.get("schedule_type") != "once" or not task.get(
                        "schedule_pending"
                    ):
                        continue
                    scheduled_at = task.get("scheduled_at")
                    if not scheduled_at:
                        continue
                    due = datetime.fromisoformat(scheduled_at)
                    current = datetime.now(due.tzinfo) if due.tzinfo else datetime.now()
                    if current >= due:
                        log_event(
                            f"[DECISION] 定时任务已到执行时间 | 计划时间={scheduled_at} | 下一步=加入队列并自动运行",
                            task_name=task.get("name", ""),
                        )
                        self.task_store.mark_schedule_consumed(task["id"])
                        await self.enqueue(task["id"], source="schedule", auto_start=True)
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_event(
                    f"[ERROR] 定时任务扫描失败，3秒后继续 | {exc}\n{traceback.format_exc()}",
                    level="ERROR",
                )
                await asyncio.sleep(3)

    async def _write_state(self, state: dict[str, Any]) -> None:
        async with self.state_lock:
            completed = sum(job["status"] == "completed" for job in state["jobs"])
            failed = sum(job["status"] == "failed" for job in state["jobs"])
            state["completed_count"] = completed
            state["failed_count"] = failed
            self.runtime_store.write(state)

    async def _take_waiting_job(
        self, state: dict[str, Any], account: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with self.state_lock:
            for job in state["jobs"]:
                if job["status"] != "waiting":
                    continue
                job["status"] = "generating"
                job["account_id"] = account["id"]
                job["account_name"] = account["name"]
                job["platform"] = account.get("platform", "doubao")
                job["attempts"] += 1
                job["started_at"] = now_iso()
                state["message"] = "所选平台的多个账号正在并行生成。"
                self.runtime_store.write(state)
                return job
        return None

    async def _execute(self, request: dict[str, Any]) -> None:
        task = request["task_snapshot"]
        enabled_platforms = self.platform_settings_store.get()["enabled_platforms"]
        all_accounts = self.account_store.list()
        accounts = [
            account
            for account in all_accounts
            if account.get("platform", "doubao") in enabled_platforms
            and account.get("enabled")
            and account.get("cookie_exists")
            and not account.get("quota_exhausted_today")
        ]
        log_event(
            f"[ACTION] 开始执行任务 | 目标视频={task['count']} | 启用平台={','.join(enabled_platforms)} | 账号总数={len(all_accounts)} | 可用账号={len(accounts)}",
            run_id=request["run_id"][:8],
            task_name=task["name"],
        )
        for account in all_accounts:
            platform = account.get("platform", "doubao")
            reasons = []
            if platform not in enabled_platforms:
                reasons.append("平台未勾选")
            if not account.get("enabled"):
                reasons.append("账号未启用")
            if not account.get("cookie_exists"):
                reasons.append("Cookie文件不存在")
            if account.get("quota_exhausted_today"):
                reasons.append("今日额度已用完")
            decision = "跳过：" + "、".join(reasons) if reasons else "可用，将参与任务分配"
            log_event(
                f"[DECISION] 账号筛选结果={decision}",
                level="WARNING" if reasons else "INFO",
                run_id=request["run_id"][:8],
                task_name=task["name"],
                platform=platform,
                account_name=account.get("name", ""),
            )
        jobs = [
            {
                "index": index,
                "status": "waiting",
                "account_id": None,
                "account_name": "",
                "platform": "",
                "attempts": 0,
                "output_path": "",
                "error": "",
                "warning": "",
            }
            for index in range(1, int(task["count"]) + 1)
        ]
        state = request.get("direct_state") or self.run_states.get(request["run_id"], {})
        state.update(
            {
                "run_id": request["run_id"],
                "task_id": task["id"],
                "task_name": task["name"],
                "source": request["source"],
                "status": "running",
                "message": "正在分配账号。",
                "requested_at": request["requested_at"],
                "started_at": now_iso(),
                "total_count": len(jobs),
                "completed_count": 0,
                "failed_count": 0,
                "output_dir": task["output_dir"],
                "enabled_platforms": enabled_platforms,
                "jobs": jobs,
                "accounts": [
                    {
                        "id": account["id"],
                        "name": account["name"],
                        "platform": account.get("platform", "doubao"),
                        "status": "ready",
                    }
                    for account in accounts
                ],
            }
        )
        if not request.get("is_direct"):
            self.run_states[request["run_id"]] = state
        self.runtime_store.write(state)

        if not accounts:
            self.queue_running = False
            self.queue_event.clear()
            state["status"] = "failed"
            enabled_accounts = [
                account
                for account in all_accounts
                if account.get("platform", "doubao") in enabled_platforms
                and account.get("enabled")
                and account.get("cookie_exists")
            ]
            if enabled_accounts and all(
                account.get("quota_exhausted_today") for account in enabled_accounts
            ):
                state["message"] = "已启用账号的今日额度均已用完，请明天再运行。"
            else:
                state["message"] = "没有可用账号，请先在账号池添加并启用账号。"
            state["finished_at"] = now_iso()
            await self._write_state(state)
            log_event(
                f"[ERROR] 任务无法开始 | 原因={state['message']}",
                level="ERROR",
                run_id=request["run_id"][:8],
                task_name=task["name"],
            )
            return

        Path(task["output_dir"]).mkdir(parents=True, exist_ok=True)

        async def set_account_status(account_id: str, status: str) -> None:
            async with self.state_lock:
                for item in state["accounts"]:
                    if item["id"] == account_id:
                        item["status"] = status
                        break
                self.runtime_store.write(state)

        async def worker(account: dict[str, Any]) -> None:
            await set_account_status(account["id"], "working")
            while True:
                job = await self._take_waiting_job(state, account)
                if not job:
                    await set_account_status(account["id"], "finished")
                    log_event(
                        "[RESULT] 当前账号没有待领取的视频，账号工作结束。",
                        level="SUCCESS",
                        run_id=request["run_id"][:8],
                        task_name=task["name"],
                        platform=account.get("platform", "doubao"),
                        account_name=account["name"],
                    )
                    return
                platform = account.get("platform", "doubao")
                with bind_log_context(
                    run_id=request["run_id"][:8],
                    task_name=task["name"],
                    job=f"{job['index']}/{len(jobs)}",
                    platform=platform,
                    account_name=account["name"],
                ):
                    try:
                        log_event(
                            f"[ACTION] 视频已分配给当前账号 | 第{job['attempts']}次尝试 | 模型={task.get('model', 'Seedance 2.0 Fast')} | 比例={task['ratio']} | 参考图={len(task['images'])}张 | 模糊={'开启' if task.get('enable_blur', True) else '关闭'}"
                        )
                        generator_class = VIDEO_GENERATORS.get(platform)
                        if generator_class is None:
                            raise ValueError(f"不支持的账号平台: {platform}")
                        generator = generator_class(account_file=Path(account["cookie_path"]))
                        saved_path = await generator.main(
                            prompt=task["prompt"],
                            reference_image_paths=[Path(item) for item in task["images"]],
                            ratio=task["ratio"],
                            save_dir=Path(task["output_dir"]),
                            theme=f"{safe_filename(task['theme'])}_{safe_filename(account['name'])}",
                            headless=bool(task.get("headless", False)),
                            model_name=task.get("model", "Seedance 2.0 Fast"),
                        )
                        log_event(
                            f"[RESULT] 视频生成并下载完成 | 文件={Path(saved_path).resolve()}",
                            level="SUCCESS",
                        )
                        warning = ""
                        if task.get("enable_blur", True):
                            try:
                                log_event("[ACTION] 开始执行视频模糊处理。")
                                blur_handler = VIDEO_BLUR_HANDLERS.get(platform)
                                if blur_handler is None:
                                    raise ValueError(f"不支持的平台模糊处理: {platform}")
                                await asyncio.to_thread(blur_handler, Path(saved_path))
                                log_event("[RESULT] 视频模糊处理完成。", level="SUCCESS")
                            except Exception as exc:
                                warning = f"视频已生成，但加模糊失败: {exc}"
                                log_event(
                                    f"[ERROR] {warning}\n{traceback.format_exc()}",
                                    level="ERROR",
                                )
                        async with self.state_lock:
                            job["status"] = "completed"
                            job["output_path"] = str(Path(saved_path).resolve())
                            job["warning"] = warning
                            job["finished_at"] = now_iso()
                            state["completed_count"] = sum(
                                item["status"] == "completed" for item in jobs
                            )
                            self.runtime_store.write(state)
                        log_event("[RESULT] 当前视频处理结束，状态=已完成。", level="SUCCESS")
                    except QUOTA_EXHAUSTED_ERRORS as exc:
                        log_event(
                            f"[DECISION] 判断结果=当前账号今日额度已用完 | 依据={exc} | 下一步=标记账号并把视频交回队列",
                            level="WARNING",
                        )
                        self.account_store.mark_quota_exhausted(account["id"])
                        async with self.state_lock:
                            job["status"] = "waiting"
                            job["account_id"] = None
                            job["account_name"] = ""
                            job["platform"] = ""
                            job["error"] = ""
                            for item in state["accounts"]:
                                if item["id"] == account["id"]:
                                    item["status"] = "quota_exhausted"
                            state["message"] = f"账号 {account['name']} 额度已用尽，正在切换账号。"
                            self.runtime_store.write(state)
                        return
                    except CONTENT_BLOCKED_ERRORS as exc:
                        log_event(
                            f"[DECISION] 判断结果=申诉一次后仍被阻断 | 依据={exc} | 下一步=标记失败且不换账号重试",
                            level="ERROR",
                        )
                        async with self.state_lock:
                            job["status"] = "failed"
                            job["error"] = str(exc)
                            job["finished_at"] = now_iso()
                            state["message"] = (
                                f"第 {job['index']} 个视频申诉一次后仍未成功，已标记失败，"
                                "不再更换账号重试。"
                            )
                            self.runtime_store.write(state)
                    except asyncio.CancelledError:
                        log_event(
                            "[DECISION] 用户停止任务 | 下一步=取消当前视频。",
                            level="WARNING",
                        )
                        async with self.state_lock:
                            if job["status"] not in FINAL_JOB_STATES:
                                job["status"] = "cancelled"
                                job["error"] = "用户停止任务"
                            self.runtime_store.write(state)
                        raise
                    except Exception as exc:
                        max_attempts = int(task.get("max_retries", 3)) + 1
                        will_retry = job["attempts"] < max_attempts
                        next_action = (
                            f"交回队列，准备第{job['attempts'] + 1}次尝试"
                            if will_retry
                            else "已达到最大尝试次数，标记失败"
                        )
                        log_event(
                            f"[ERROR] 视频执行失败 | 原因={exc} | 当前尝试={job['attempts']}/{max_attempts} | 下一步={next_action}\n{traceback.format_exc()}",
                            level="ERROR",
                        )
                        async with self.state_lock:
                            job["error"] = str(exc)
                            if will_retry:
                                job["status"] = "waiting"
                                job["account_id"] = None
                                job["account_name"] = ""
                                job["platform"] = ""
                                state["message"] = (
                                    f"第 {job['index']} 个视频失败，准备第 "
                                    f"{job['attempts'] + 1} 次尝试。"
                                )
                            else:
                                job["status"] = "failed"
                                job["finished_at"] = now_iso()
                            self.runtime_store.write(state)

        try:
            await asyncio.gather(*(worker(account) for account in accounts))
        except asyncio.CancelledError:
            async with self.state_lock:
                for job in jobs:
                    if job["status"] not in FINAL_JOB_STATES:
                        job["status"] = "cancelled"
                        job["error"] = "用户停止任务"
                state["status"] = "stopped"
                state["message"] = "任务已停止。"
                state["finished_at"] = now_iso()
                self.runtime_store.write(state)
            raise

        waiting_count = sum(job["status"] == "waiting" for job in jobs)
        failed_count = sum(job["status"] == "failed" for job in jobs)
        completed_count = sum(job["status"] == "completed" for job in jobs)
        if waiting_count:
            self.queue_running = False
            self.queue_event.clear()
            state["status"] = "waiting_for_account"
            state["message"] = "可用账号均已退出，剩余视频可稍后重新运行。"
        elif failed_count:
            state["status"] = "completed_with_errors"
            state["message"] = f"运行结束：成功 {completed_count}，失败 {failed_count}。"
        else:
            state["status"] = "completed"
            state["message"] = f"全部 {completed_count} 个视频已生成。"
        state["finished_at"] = now_iso()
        await self._write_state(state)
        log_event(
            f"[RESULT] 本次任务运行结束 | 状态={state['status']} | 成功={completed_count} | 失败={failed_count} | 等待={waiting_count}",
            level="SUCCESS" if not failed_count and not waiting_count else "WARNING",
            run_id=request["run_id"][:8],
            task_name=task["name"],
        )
