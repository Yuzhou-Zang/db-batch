from __future__ import annotations

import asyncio
import json
import os
import traceback
import webbrowser
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.web_request import FileField

from .login import LoginManager
from .runtime_log import SESSION_LOG, install_stream_capture, log_event
from .runner import TaskRunner
from .storage import AccountStore, PlatformSettingsStore, RuntimeStore, TaskStore


STATIC_DIR = Path(__file__).resolve().parent / "static"


def json_response(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        status=status,
        content_type="application/json",
        charset="utf-8",
    )


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except KeyError as exc:
        return json_response({"error": str(exc).strip("'")}, status=404)
    except (ValueError, TypeError) as exc:
        return json_response({"error": str(exc)}, status=400)
    except web.HTTPException:
        raise
    except Exception as exc:
        log_event(
            f"[ERROR] 接口处理失败：{request.method} {request.path} | {exc}\n{traceback.format_exc()}",
            level="ERROR",
        )
        return json_response({"error": f"服务器错误: {exc}"}, status=500)


@web.middleware
async def no_cache_middleware(request: web.Request, handler):
    response = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


def account_store(request: web.Request) -> AccountStore:
    return request.app["account_store"]


def task_store(request: web.Request) -> TaskStore:
    return request.app["task_store"]


def runner(request: web.Request) -> TaskRunner:
    return request.app["runner"]


def login_manager(request: web.Request) -> LoginManager:
    return request.app["login_manager"]


def platform_settings(request: web.Request) -> PlatformSettingsStore:
    return request.app["platform_settings_store"]


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def health(_: web.Request) -> web.Response:
    return json_response({"ok": True})


async def list_accounts(request: web.Request) -> web.Response:
    return json_response(account_store(request).list())


async def set_all_accounts_enabled(request: web.Request) -> web.Response:
    values = await request.json()
    if not isinstance(values.get("enabled"), bool):
        raise ValueError("enabled 必须是布尔值")
    return json_response(account_store(request).set_all_enabled(values["enabled"]))


async def update_account(request: web.Request) -> web.Response:
    values = await request.json()
    account = account_store(request).update(request.match_info["account_id"], values)
    return json_response(account)


async def delete_account(request: web.Request) -> web.Response:
    account_id = request.match_info["account_id"]
    state = runner(request).snapshot()
    if state.get("status") in {"running", "cancelling"}:
        busy_ids = {
            item.get("account_id")
            for item in state.get("jobs", [])
            if item.get("status") == "generating"
        }
        if account_id in busy_ids:
            raise ValueError("这个账号正在生成视频，请先停止当前任务")
    account_store(request).delete(account_id)
    return json_response({"ok": True})


async def start_login(request: web.Request) -> web.Response:
    values = await request.json()
    session = await login_manager(request).start(
        str(values.get("name", "")),
        str(values.get("platform", "doubao")),
    )
    return json_response(session, status=201)


async def save_login(request: web.Request) -> web.Response:
    account = await login_manager(request).save(request.match_info["session_id"])
    return json_response(account, status=201)


async def cancel_login(request: web.Request) -> web.Response:
    await login_manager(request).cancel(request.match_info["session_id"])
    return json_response({"ok": True})


async def get_platform_settings(request: web.Request) -> web.Response:
    return json_response(platform_settings(request).get())


async def update_platform_settings(request: web.Request) -> web.Response:
    values = await request.json()
    settings = platform_settings(request).update(values.get("enabled_platforms"))
    return json_response(settings)


def task_values_from_form(form: Any) -> dict[str, Any]:
    return {
        "name": form.get("name", ""),
        "prompt": form.get("prompt", ""),
        "count": form.get("count", 1),
        "ratio": form.get("ratio", "9:16"),
        "model": form.get("model", "Seedance 2.0 Fast"),
        "theme": form.get("theme", form.get("name", "video")),
        "output_dir": form.get("output_dir", ""),
        "schedule_type": form.get("schedule_type", "manual"),
        "scheduled_at": form.get("scheduled_at", ""),
        "headless": as_bool(form.get("headless")),
        "enable_blur": as_bool(form.get("enable_blur"), default=False),
        "max_retries": form.get("max_retries", 3),
    }


def images_from_form(form: Any) -> list[tuple[str, bytes]]:
    images: list[tuple[str, bytes]] = []
    for item in form.getall("images", []):
        if not isinstance(item, FileField) or not item.filename:
            continue
        images.append((item.filename, item.file.read()))
    return images


async def list_tasks(request: web.Request) -> web.Response:
    return json_response(task_store(request).list())


async def create_task(request: web.Request) -> web.Response:
    form = await request.post()
    task = task_store(request).create(task_values_from_form(form), images_from_form(form))
    return json_response(task, status=201)


async def update_task(request: web.Request) -> web.Response:
    form = await request.post()
    task = task_store(request).update(
        request.match_info["task_id"],
        task_values_from_form(form),
        images_from_form(form),
    )
    return json_response(task)


async def set_task_hidden(request: web.Request) -> web.Response:
    values = await request.json()
    task = task_store(request).set_hidden(
        request.match_info["task_id"], as_bool(values.get("hidden"))
    )
    return json_response(task)


async def delete_task(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    state = runner(request).snapshot()
    if state.get("task_id") == task_id and state.get("status") in {
        "running",
        "cancelling",
    }:
        raise ValueError("这个任务正在运行，请先停止")
    task_store(request).delete(task_id)
    return json_response({"ok": True})


async def run_task(request: web.Request) -> web.Response:
    direct_run = await runner(request).run_direct(
        request.match_info["task_id"], source="manual"
    )
    return json_response(direct_run, status=202)


async def queue_task(request: web.Request) -> web.Response:
    queued = await runner(request).enqueue(
        request.match_info["task_id"], source="manual", auto_start=False
    )
    return json_response(queued, status=202)


async def runtime(request: web.Request) -> web.Response:
    return json_response(runner(request).snapshot())


async def runtime_logs(request: web.Request) -> web.Response:
    try:
        after_id = max(0, int(request.query.get("after", "0")))
    except ValueError as exc:
        raise ValueError("日志游标格式不正确") from exc
    return json_response(SESSION_LOG.snapshot(after_id=after_id))


async def start_runtime(request: web.Request) -> web.Response:
    await runner(request).start_queue()
    return json_response({"ok": True})


async def stop_runtime(request: web.Request) -> web.Response:
    await runner(request).stop_queue()
    return json_response({"ok": True})


async def delete_runtime_run(request: web.Request) -> web.Response:
    await runner(request).delete_run(request.match_info["run_id"])
    return json_response({"ok": True})


async def start_runtime_run(request: web.Request) -> web.Response:
    await runner(request).start_run(request.match_info["run_id"])
    return json_response({"ok": True})


async def stop_runtime_run(request: web.Request) -> web.Response:
    await runner(request).stop_run(request.match_info["run_id"])
    return json_response({"ok": True})


async def reorder_runtime_runs(request: web.Request) -> web.Response:
    values = await request.json()
    run_ids = values.get("run_ids", [])
    if not isinstance(run_ids, list) or not all(isinstance(item, str) for item in run_ids):
        raise ValueError("任务顺序格式不正确")
    await runner(request).reorder_runs(run_ids)
    return json_response({"ok": True})


async def on_startup(app: web.Application) -> None:
    app["account_store"].bootstrap_legacy_accounts()
    app["task_store"].bootstrap_legacy_tasks()
    await app["runner"].start()
    log_event(
        f"[RESULT] 管理页面服务启动完成：http://127.0.0.1:{app['port']} | 本次日志开始记录",
        level="SUCCESS",
    )
    if os.environ.get("DOUBAO_WEB_NO_BROWSER") != "1":
        port = app["port"]
        asyncio.get_running_loop().call_later(
            1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")
        )


async def on_cleanup(app: web.Application) -> None:
    log_event("[ACTION] 管理页面服务正在关闭。")
    await app["login_manager"].close_all()
    await app["runner"].stop()


def create_app(port: int = 8765) -> web.Application:
    accounts = AccountStore()
    tasks = TaskStore()
    runtime_state = RuntimeStore()
    platform_state = PlatformSettingsStore()
    task_runner = TaskRunner(accounts, tasks, runtime_state, platform_state)
    logins = LoginManager(accounts)

    app = web.Application(
        middlewares=[error_middleware, no_cache_middleware],
        client_max_size=100 * 1024**2,
    )
    app["port"] = port
    app["account_store"] = accounts
    app["task_store"] = tasks
    app["runtime_store"] = runtime_state
    app["platform_settings_store"] = platform_state
    app["runner"] = task_runner
    app["login_manager"] = logins

    app.router.add_get("/", index)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/accounts", list_accounts)
    app.router.add_put("/api/accounts/enabled", set_all_accounts_enabled)
    app.router.add_put("/api/accounts/{account_id}", update_account)
    app.router.add_delete("/api/accounts/{account_id}", delete_account)
    app.router.add_post("/api/accounts/login/start", start_login)
    app.router.add_post("/api/accounts/login/{session_id}/save", save_login)
    app.router.add_post("/api/accounts/login/{session_id}/cancel", cancel_login)
    app.router.add_get("/api/settings/platforms", get_platform_settings)
    app.router.add_put("/api/settings/platforms", update_platform_settings)
    app.router.add_get("/api/tasks", list_tasks)
    app.router.add_post("/api/tasks", create_task)
    app.router.add_put("/api/tasks/{task_id}", update_task)
    app.router.add_put("/api/tasks/{task_id}/hidden", set_task_hidden)
    app.router.add_delete("/api/tasks/{task_id}", delete_task)
    app.router.add_post("/api/tasks/{task_id}/run", run_task)
    app.router.add_post("/api/tasks/{task_id}/queue", queue_task)
    app.router.add_get("/api/runtime", runtime)
    app.router.add_get("/api/runtime/logs", runtime_logs)
    app.router.add_post("/api/runtime/start", start_runtime)
    app.router.add_post("/api/runtime/stop", stop_runtime)
    app.router.add_put("/api/runtime/order", reorder_runtime_runs)
    app.router.add_post("/api/runtime/runs/{run_id}/start", start_runtime_run)
    app.router.add_post("/api/runtime/runs/{run_id}/stop", stop_runtime_run)
    app.router.add_delete("/api/runtime/runs/{run_id}", delete_runtime_run)
    app.router.add_static("/static/", STATIC_DIR)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def run() -> None:
    install_stream_capture()
    port = int(os.environ.get("DOUBAO_WEB_PORT", "8765"))
    web.run_app(
        create_app(port),
        host="127.0.0.1",
        port=port,
        print=lambda message: print(message.replace("0.0.0.0", "127.0.0.1")),
    )
