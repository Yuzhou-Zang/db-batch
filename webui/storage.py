from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
ACCOUNTS_DIR = DATA_DIR / "accounts"
ACCOUNT_COOKIES_DIR = DATA_DIR / "account_cookies"
TASKS_DIR = DATA_DIR / "tasks"
RUNTIME_DIR = DATA_DIR / "runtime"
TRASH_DIR = DATA_DIR / "trash"
PLATFORM_SETTINGS_PATH = DATA_DIR / "platform_settings.json"
DEFAULT_OUTPUT_DIR = (PROJECT_DIR / "doubao_video_output").resolve()
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
SUPPORTED_ACCOUNT_PLATFORMS = {"doubao", "dola"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


def safe_filename(value: str, fallback: str = "task") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip(" ._")
    return cleaned[:60] or fallback


def resolve_output_dir(raw_value: str | None) -> Path:
    if not raw_value or not raw_value.strip():
        return DEFAULT_OUTPUT_DIR
    candidate = Path(raw_value.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_DIR / candidate
    return candidate.resolve()


def _unique_trash_path(name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return TRASH_DIR / f"{safe_filename(name)}_{timestamp}_{uuid.uuid4().hex[:6]}"


class AccountStore:
    def __init__(self) -> None:
        ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
        ACCOUNT_COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        TRASH_DIR.mkdir(parents=True, exist_ok=True)

    def bootstrap_legacy_accounts(self) -> None:
        if any(ACCOUNTS_DIR.glob("*.json")):
            return
        legacy_dir = PROJECT_DIR / "cookies" / "doubao"
        if not legacy_dir.exists():
            return
        for cookie_path in sorted(legacy_dir.glob("*.json")):
            self.create(
                name=cookie_path.stem,
                cookie_path=cookie_path.resolve(),
                enabled=True,
                managed_cookie=False,
            )

    def list(self) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        today = datetime.now().astimezone().date().isoformat()
        for path in ACCOUNTS_DIR.glob("*.json"):
            try:
                account = read_json(path)
                if isinstance(account, dict):
                    # 兼容升级前的账号记录；旧账号全部属于豆包。
                    account["platform"] = account.get("platform") or "doubao"
                    account["cookie_exists"] = Path(account["cookie_path"]).exists()
                    account["quota_exhausted_today"] = (
                        account.get("quota_exhausted_date") == today
                    )
                    accounts.append(account)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        return sorted(accounts, key=lambda item: item.get("created_at", ""))

    def get(self, account_id: str) -> dict[str, Any]:
        path = ACCOUNTS_DIR / f"{account_id}.json"
        account = read_json(path)
        if not isinstance(account, dict):
            raise KeyError("账号不存在")
        account["platform"] = account.get("platform") or "doubao"
        return account

    def create(
        self,
        name: str,
        cookie_path: Path,
        enabled: bool = True,
        managed_cookie: bool = True,
        platform: str = "doubao",
    ) -> dict[str, Any]:
        platform = platform.strip().lower()
        if platform not in SUPPORTED_ACCOUNT_PLATFORMS:
            raise ValueError("账号平台必须是豆包或 Dola")
        account_id = uuid.uuid4().hex
        timestamp = now_iso()
        default_platform_name = "Dola" if platform == "dola" else "豆包"
        account = {
            "id": account_id,
            "platform": platform,
            "name": name.strip() or f"{default_platform_name}账号-{account_id[:6]}",
            "cookie_path": str(Path(cookie_path).resolve()),
            "managed_cookie": managed_cookie,
            "enabled": bool(enabled),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        atomic_write_json(ACCOUNTS_DIR / f"{account_id}.json", account)
        return account

    def update(self, account_id: str, values: dict[str, Any]) -> dict[str, Any]:
        account = self.get(account_id)
        if "name" in values:
            name = str(values["name"]).strip()
            if not name:
                raise ValueError("账号名称不能为空")
            account["name"] = name
        if "enabled" in values:
            account["enabled"] = bool(values["enabled"])
        account["updated_at"] = now_iso()
        atomic_write_json(ACCOUNTS_DIR / f"{account_id}.json", account)
        return account

    def set_all_enabled(self, enabled: bool) -> list[dict[str, Any]]:
        timestamp = now_iso()
        for account in self.list():
            account["enabled"] = enabled
            account["updated_at"] = timestamp
            account.pop("cookie_exists", None)
            account.pop("quota_exhausted_today", None)
            atomic_write_json(ACCOUNTS_DIR / f"{account['id']}.json", account)
        return self.list()

    def mark_quota_exhausted(self, account_id: str) -> dict[str, Any]:
        """记录账号当天额度用完；跨天后列表会自动恢复为未标记。"""
        account = self.get(account_id)
        timestamp = now_iso()
        account["quota_exhausted_date"] = datetime.now().astimezone().date().isoformat()
        account["quota_exhausted_at"] = timestamp
        account["updated_at"] = timestamp
        atomic_write_json(ACCOUNTS_DIR / f"{account_id}.json", account)
        return account

    def delete(self, account_id: str) -> None:
        account = self.get(account_id)
        trash_path = _unique_trash_path(f"account_{account.get('name', account_id)}")
        trash_path.mkdir(parents=True, exist_ok=True)
        metadata_path = ACCOUNTS_DIR / f"{account_id}.json"
        shutil.move(str(metadata_path), str(trash_path / metadata_path.name))

        cookie_path = Path(account["cookie_path"])
        if account.get("managed_cookie") and cookie_path.exists():
            try:
                cookie_path.relative_to(ACCOUNT_COOKIES_DIR)
            except ValueError:
                return
            shutil.move(str(cookie_path), str(trash_path / cookie_path.name))


class TaskStore:
    def __init__(self) -> None:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        TRASH_DIR.mkdir(parents=True, exist_ok=True)

    def bootstrap_legacy_tasks(self) -> None:
        if any(TASKS_DIR.glob("*/task.json")):
            return
        config_dir = PROJECT_DIR / "文生图config"
        if not config_dir.exists():
            return
        for config_path in sorted(config_dir.glob("*.json")):
            try:
                config = read_json(config_path)
                image_sources: list[Path] = []
                for raw_path in config.get("reference_image_paths", []):
                    image_path = Path(str(raw_path))
                    if not image_path.is_absolute():
                        image_path = PROJECT_DIR / image_path
                    if image_path.exists() and image_path.is_file():
                        image_sources.append(image_path.resolve())
                if not config.get("prompt") or not image_sources:
                    continue
                self.create_from_paths(
                    {
                        "name": config_path.stem,
                        "prompt": config["prompt"],
                        "count": 1,
                        "ratio": config.get("ratio", "9:16"),
                        "model": "Seedance 2.0 Fast",
                        "theme": config.get("theme", config_path.stem),
                        "output_dir": str(DEFAULT_OUTPUT_DIR),
                        "schedule_type": "manual",
                        "scheduled_at": "",
                        "headless": False,
                        "enable_blur": True,
                        "max_retries": 3,
                    },
                    image_sources,
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue

    def list(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for path in TASKS_DIR.glob("*/task.json"):
            try:
                task = read_json(path)
                if isinstance(task, dict):
                    task["image_names"] = [Path(item).name for item in task.get("images", [])]
                    tasks.append(task)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(tasks, key=lambda item: item.get("updated_at", ""), reverse=True)

    def get(self, task_id: str) -> dict[str, Any]:
        task = read_json(TASKS_DIR / task_id / "task.json")
        if not isinstance(task, dict):
            raise KeyError("任务不存在")
        return task

    def _normalize(self, values: dict[str, Any], task_id: str) -> dict[str, Any]:
        name = str(values.get("name", "")).strip()
        prompt = str(values.get("prompt", "")).strip()
        if not name:
            raise ValueError("任务名称不能为空")
        if not prompt:
            raise ValueError("提示词不能为空")

        count = int(values.get("count", 1))
        if count < 1 or count > 999:
            raise ValueError("生成数量必须在 1 到 999 之间")

        schedule_type = str(values.get("schedule_type", "manual"))
        if schedule_type not in {"manual", "once"}:
            raise ValueError("执行方式无效")
        scheduled_at = str(values.get("scheduled_at", "")).strip()
        if schedule_type == "once" and not scheduled_at:
            raise ValueError("定时任务必须选择执行时间")
        if scheduled_at:
            datetime.fromisoformat(scheduled_at)

        output_dir = resolve_output_dir(str(values.get("output_dir", "")))
        timestamp = now_iso()
        return {
            "id": task_id,
            "name": name,
            "prompt": prompt,
            "count": count,
            "ratio": str(values.get("ratio", "9:16")).strip() or "9:16",
            "model": str(values.get("model", "Seedance 2.0 Fast")).strip()
            or "Seedance 2.0 Fast",
            "theme": safe_filename(str(values.get("theme", name)), "video"),
            "output_dir": str(output_dir),
            "schedule_type": schedule_type,
            "scheduled_at": scheduled_at,
            "schedule_pending": schedule_type == "once",
            "headless": bool(values.get("headless", False)),
            "enable_blur": bool(values.get("enable_blur", True)),
            "hidden": bool(values.get("hidden", False)),
            "max_retries": max(0, min(int(values.get("max_retries", 3)), 10)),
            "updated_at": timestamp,
        }

    def _save_image_bytes(
        self, task_id: str, images: Iterable[tuple[str, bytes]]
    ) -> list[str]:
        image_dir = TASKS_DIR / task_id / "images"
        if image_dir.exists():
            shutil.rmtree(image_dir)
        image_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for index, (filename, content) in enumerate(images, start=1):
            suffix = Path(filename).suffix.lower()
            if suffix not in ALLOWED_IMAGE_SUFFIXES:
                raise ValueError(f"不支持的参考图格式: {filename}")
            if not content:
                raise ValueError(f"参考图为空: {filename}")
            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError(f"参考图超过 20MB: {filename}")
            target = image_dir / f"{index:03d}{suffix}"
            target.write_bytes(content)
            saved.append(str(target.resolve()))
        return saved

    def _copy_image_paths(self, task_id: str, paths: Iterable[Path]) -> list[str]:
        image_dir = TASKS_DIR / task_id / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for index, source in enumerate(paths, start=1):
            suffix = source.suffix.lower()
            if suffix not in ALLOWED_IMAGE_SUFFIXES:
                continue
            target = image_dir / f"{index:03d}{suffix}"
            shutil.copy2(source, target)
            saved.append(str(target.resolve()))
        return saved

    def create(
        self, values: dict[str, Any], images: Iterable[tuple[str, bytes]]
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex
        task = self._normalize(values, task_id)
        task["created_at"] = task["updated_at"]
        task["images"] = self._save_image_bytes(task_id, images)
        if not task["images"]:
            shutil.rmtree(TASKS_DIR / task_id, ignore_errors=True)
            raise ValueError("至少需要上传一张参考图")
        atomic_write_json(TASKS_DIR / task_id / "task.json", task)
        return task

    def create_from_paths(
        self, values: dict[str, Any], image_paths: Iterable[Path]
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex
        task = self._normalize(values, task_id)
        task["created_at"] = task["updated_at"]
        task["images"] = self._copy_image_paths(task_id, image_paths)
        if not task["images"]:
            shutil.rmtree(TASKS_DIR / task_id, ignore_errors=True)
            raise ValueError("至少需要一张参考图")
        atomic_write_json(TASKS_DIR / task_id / "task.json", task)
        return task

    def update(
        self,
        task_id: str,
        values: dict[str, Any],
        images: Iterable[tuple[str, bytes]] | None = None,
    ) -> dict[str, Any]:
        previous = self.get(task_id)
        normalized_values = dict(values)
        normalized_values["hidden"] = previous.get("hidden", False)
        task = self._normalize(normalized_values, task_id)
        task["created_at"] = previous.get("created_at", task["updated_at"])
        image_items = list(images or [])
        task["images"] = (
            self._save_image_bytes(task_id, image_items)
            if image_items
            else previous.get("images", [])
        )
        if not task["images"]:
            raise ValueError("至少需要一张参考图")
        atomic_write_json(TASKS_DIR / task_id / "task.json", task)
        return task

    def set_hidden(self, task_id: str, hidden: bool) -> dict[str, Any]:
        task = self.get(task_id)
        task["hidden"] = bool(hidden)
        task["updated_at"] = now_iso()
        atomic_write_json(TASKS_DIR / task_id / "task.json", task)
        return task

    def mark_schedule_consumed(self, task_id: str) -> None:
        task = self.get(task_id)
        task["schedule_pending"] = False
        task["updated_at"] = now_iso()
        atomic_write_json(TASKS_DIR / task_id / "task.json", task)

    def delete(self, task_id: str) -> None:
        task = self.get(task_id)
        source = TASKS_DIR / task_id
        target = _unique_trash_path(f"task_{task.get('name', task_id)}")
        shutil.move(str(source), str(target))


class RuntimeStore:
    def __init__(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self.path = RUNTIME_DIR / "current.json"
        self.history_path = RUNTIME_DIR / "history.json"

    def get(self) -> dict[str, Any]:
        state = read_json(self.path, default={"status": "idle", "jobs": []})
        return state if isinstance(state, dict) else {"status": "idle", "jobs": []}

    def write(self, state: dict[str, Any]) -> None:
        state["updated_at"] = now_iso()
        atomic_write_json(self.path, state)
        run_id = state.get("run_id")
        if run_id:
            history = self.list_history()
            for index, item in enumerate(history):
                if item.get("run_id") == run_id:
                    history[index] = copy.deepcopy(state)
                    break
            else:
                history.append(copy.deepcopy(state))
            atomic_write_json(self.history_path, history)

    def list_history(self) -> list[dict[str, Any]]:
        history = read_json(self.history_path, default=[])
        if not isinstance(history, list):
            return []
        return [item for item in history if isinstance(item, dict) and item.get("run_id")]

    def save_history(self, history: list[dict[str, Any]]) -> None:
        atomic_write_json(self.history_path, history)

    def delete_history(self, run_id: str) -> None:
        history = [
            item for item in self.list_history()
            if item.get("run_id") != run_id
        ]
        atomic_write_json(self.history_path, history)

    def mark_interrupted_if_needed(self) -> None:
        state = self.get()
        # 排队任务可以由运行器在重启后恢复，只有真正执行中的任务才算中断。
        if state.get("status") not in {"running", "cancelling"}:
            return
        state["status"] = "interrupted"
        state["message"] = "上次运行因服务关闭而中断，可以重新点击立即运行。"
        for job in state.get("jobs", []):
            if job.get("status") in {"waiting", "generating", "downloading"}:
                job["status"] = "interrupted"
        self.write(state)


class PlatformSettingsStore:
    """保存任务池顶部的全局运行平台选择。"""

    def get(self) -> dict[str, Any]:
        settings = read_json(PLATFORM_SETTINGS_PATH, default={})
        if not isinstance(settings, dict):
            settings = {}
        raw_platforms = settings.get("enabled_platforms", ["doubao"])
        if not isinstance(raw_platforms, list):
            raw_platforms = ["doubao"]
        selected = set(raw_platforms)
        enabled_platforms = [
            platform
            for platform in ("doubao", "dola")
            if platform in selected
        ]
        if not enabled_platforms:
            enabled_platforms = ["doubao"]
        return {"enabled_platforms": enabled_platforms}

    def update(self, enabled_platforms: Any) -> dict[str, Any]:
        if not isinstance(enabled_platforms, list):
            raise ValueError("运行平台格式不正确")
        selected = {str(platform).strip().lower() for platform in enabled_platforms}
        invalid = selected - SUPPORTED_ACCOUNT_PLATFORMS
        if invalid:
            raise ValueError("运行平台只能选择豆包或 Dola")
        normalized = [
            platform
            for platform in ("doubao", "dola")
            if platform in selected
        ]
        if not normalized:
            raise ValueError("至少选择一个运行平台")
        settings = {"enabled_platforms": normalized, "updated_at": now_iso()}
        atomic_write_json(PLATFORM_SETTINGS_PATH, settings)
        return {"enabled_platforms": normalized}
