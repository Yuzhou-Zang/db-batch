# -*- coding: utf-8 -*-
import argparse
import asyncio
import json
import time
from pathlib import Path

from doubao_video import (
    DoubaoVideoGenerator,
    QuotaExhaustedError,
    VideoGenerateFailedError,
)
from 加模糊 import blur_video_inplace


# ==========================
# 运行参数（直接改这里即可）
# ==========================
SCRIPT_DIR = Path(__file__).resolve().parent
# CONFIG_PATH = (SCRIPT_DIR / "文生图config" / "芍药.json").resolve()
# CONFIG_PATH = (SCRIPT_DIR / "文生图config" / "金钻.json").resolve()
CONFIG_PATH = (SCRIPT_DIR / "文生图config" / "test.json").resolve()

TARGET_COUNT = "10"  # 正整数 或 "all"
# TARGET_COUNT = "all"  # 正整数 或 "all"


def load_generation_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件JSON格式错误: {CONFIG_PATH} ({exc})") from exc

    if not isinstance(config, dict):
        raise ValueError(f"配置文件内容必须是对象: {CONFIG_PATH}")

    required_fields = ["prompt", "reference_image_paths", "ratio", "theme"]
    missing_fields = [key for key in required_fields if key not in config]
    if missing_fields:
        raise ValueError(f"配置缺少字段: {', '.join(missing_fields)}")

    prompt = config["prompt"]
    ratio = config["ratio"]
    theme = config["theme"]
    reference_image_paths = config["reference_image_paths"]

    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("配置字段 prompt 必须是非空字符串。")
    if not isinstance(ratio, str) or not ratio.strip():
        raise ValueError("配置字段 ratio 必须是非空字符串。")
    if not isinstance(theme, str) or not theme.strip():
        raise ValueError("配置字段 theme 必须是非空字符串。")
    if not isinstance(reference_image_paths, list) or not reference_image_paths:
        raise ValueError("配置字段 reference_image_paths 必须是非空数组。")

    resolved_reference_paths = []
    for index, raw_path in enumerate(reference_image_paths):
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(
                f"配置字段 reference_image_paths[{index}] 必须是非空字符串路径。"
            )
        candidate = Path(raw_path.strip())
        if not candidate.is_absolute():
            candidate = (SCRIPT_DIR / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"参考图不存在: {candidate}")
        resolved_reference_paths.append(candidate)

    return {
        "prompt": prompt.strip(),
        "reference_image_paths": resolved_reference_paths,
        "ratio": ratio.strip(),
        "theme": theme.strip(),
    }


GENERATION_CONFIG = load_generation_config()
PROMPT = GENERATION_CONFIG["prompt"]
# 支持上传多张参考图，按顺序填写。
REFERENCE_IMAGE_PATHS = GENERATION_CONFIG["reference_image_paths"]
RATIO = GENERATION_CONFIG["ratio"]
THEME = GENERATION_CONFIG["theme"]


SAVE_DIR = (SCRIPT_DIR / "doubao_video_output").resolve()
HEADLESS = False
ENABLE_BLUR_AFTER_GENERATE = True

POOL_COOKIES_DIR = (SCRIPT_DIR / "cookies" / "doubao").resolve()
MAX_RETRY_PER_ACCOUNT = 3


def log(message: str) -> None:
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {message}")


def parse_cli_args():
    parser = argparse.ArgumentParser(description="豆包视频账号池调度")
    parser.add_argument(
        "--target-count",
        required=False,
        help="总生成目标，传正整数或 all（不传则使用脚本内 TARGET_COUNT）",
    )
    return parser.parse_args()


def validate_target_count(value):
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "all":
            return "all"
        if normalized.isdigit() and int(normalized) > 0:
            return int(normalized)

    if value == "all":
        return "all"
    if isinstance(value, int) and value > 0:
        return value
    raise ValueError("TARGET_COUNT 仅支持正整数或字符串 'all'。")


def resolve_target_count(cli_target_count):
    selected = TARGET_COUNT if cli_target_count is None else cli_target_count
    return validate_target_count(selected)


def scan_account_files() -> list[Path]:
    if not POOL_COOKIES_DIR.exists():
        raise FileNotFoundError(f"账号目录不存在: {POOL_COOKIES_DIR}")

    account_files = sorted([p for p in POOL_COOKIES_DIR.glob("*.json") if p.is_file()])
    if not account_files:
        raise RuntimeError(f"未在 {POOL_COOKIES_DIR} 下找到任何 json 账号文件。")
    return account_files


async def run_one_round(round_no: int, target_count) -> dict:
    accounts = scan_account_files()
    log(f"开始第 {round_no} 轮账号池调度，可用账号数: {len(accounts)}")

    summary = {
        "target_count": target_count,
        "generated_total": 0,
        "success_count": 0,
        "quota_exhausted_count": 0,
        "failed_count": 0,
        "target_reached": False,
        "pool_exhausted": False,
        "incomplete_target": False,
        "remaining": 0,
        "account_stats": {},
        "account_order_processed": [],
    }

    for idx, account_file in enumerate(accounts, start=1):
        if target_count != "all" and summary["generated_total"] >= target_count:
            summary["target_reached"] = True
            break

        account_name = account_file.name
        log(f"[{idx}/{len(accounts)}] 处理账号: {account_name}")
        summary["account_order_processed"].append(account_name)
        summary["account_stats"][account_name] = {
            "success_count": 0,
            "quota_exhausted": False,
            "failed": False,
            "last_error": "",
        }

        retry = 0
        while True:
            if target_count != "all" and summary["generated_total"] >= target_count:
                summary["target_reached"] = True
                break

            try:
                generator = DoubaoVideoGenerator(account_file=account_file)
                saved_path = await generator.main(
                    prompt=PROMPT,
                    reference_image_paths=REFERENCE_IMAGE_PATHS,
                    ratio=RATIO,
                    save_dir=SAVE_DIR,
                    theme=f"{THEME}_{account_file.stem}",
                    headless=HEADLESS,
                )
                generated_path = Path(saved_path)
                log(f"账号生成成功: {account_name} -> {generated_path}")
                if ENABLE_BLUR_AFTER_GENERATE:
                    log(f"开始加模糊并覆盖原文件: {generated_path.name}")
                    blur_video_inplace(generated_path)
                    log(f"加模糊成功并已覆盖: {generated_path.name}")
                else:
                    log(f"已关闭后处理，跳过加模糊: {generated_path.name}")
                retry = 0
                summary["success_count"] += 1
                summary["generated_total"] += 1
                summary["account_stats"][account_name]["success_count"] += 1

                if target_count != "all":
                    log(f"总进度: {summary['generated_total']}/{target_count}")
                else:
                    log(f"总进度: 已生成 {summary['generated_total']} 个（all 模式）")

                # 成功后继续使用当前账号，直到额度用尽或达到全局目标
                continue
            except QuotaExhaustedError as e:
                log(f"账号额度用尽，切换下一个: {account_name} ({e})")
                summary["quota_exhausted_count"] += 1
                summary["account_stats"][account_name]["quota_exhausted"] = True
                summary["account_stats"][account_name]["last_error"] = str(e)
                break
            except VideoGenerateFailedError as e:
                retry += 1
                if retry > MAX_RETRY_PER_ACCOUNT:
                    log(
                        f"账号失败并跳过: {account_name}，视频生成失败重试已达上限。最后错误: {e}"
                    )
                    summary["failed_count"] += 1
                    summary["account_stats"][account_name]["failed"] = True
                    summary["account_stats"][account_name]["last_error"] = str(e)
                    break
                else:
                    log(
                        f"检测到视频生成失败，准备重试 {retry}/{MAX_RETRY_PER_ACCOUNT}: "
                        f"{account_name}，错误: {e}"
                    )
                    await asyncio.sleep(3)
            except Exception as e:
                retry += 1
                if retry > MAX_RETRY_PER_ACCOUNT:
                    log(f"账号失败并跳过: {account_name}，重试已达上限。最后错误: {e}")
                    summary["failed_count"] += 1
                    summary["account_stats"][account_name]["failed"] = True
                    summary["account_stats"][account_name]["last_error"] = str(e)
                    break
                else:
                    log(f"账号异常，准备重试 {retry}/{MAX_RETRY_PER_ACCOUNT}: {account_name}，错误: {e}")
                    await asyncio.sleep(3)

    if not summary["target_reached"]:
        summary["pool_exhausted"] = True

    if target_count != "all" and summary["generated_total"] < target_count:
        summary["incomplete_target"] = True
        summary["remaining"] = target_count - summary["generated_total"]

    return summary


def print_summary(round_no: int, summary: dict) -> None:
    target_count = summary["target_count"]
    log(
        f"第 {round_no} 轮结束：目标={target_count}，已生成={summary['generated_total']}，"
        f"成功次数={summary['success_count']}，额度用尽账号={summary['quota_exhausted_count']}，失败账号={summary['failed_count']}"
    )

    if summary["target_reached"]:
        log("状态：已达到目标生成数量。")
    elif summary["pool_exhausted"]:
        log("状态：账号池本轮已全部处理完（可用额度耗尽或失败）。")

    if summary["incomplete_target"]:
        log(f"状态：未完成目标，剩余 {summary['remaining']} 个。")

    for account_name in summary["account_order_processed"]:
        stats = summary["account_stats"][account_name]
        log(
            f" - {account_name}: success={stats['success_count']}, "
            f"quota_exhausted={stats['quota_exhausted']}, failed={stats['failed']}, "
            f"last_error={stats['last_error']}"
        )


async def main(target_count) -> None:
    round_no = 1
    summary = await run_one_round(round_no, target_count)
    print_summary(round_no, summary)


if __name__ == "__main__":
    args = parse_cli_args()
    target_count = resolve_target_count(args.target_count)
    asyncio.run(main(target_count), debug=False)
