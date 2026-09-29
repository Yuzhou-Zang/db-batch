# -*- coding: utf-8 -*-
import argparse
import asyncio
import time
from pathlib import Path

from doubao_video import (
    DoubaoVideoGenerator,
    QuotaExhaustedError,
)


# ==========================
# 运行参数（直接改这里即可）
# ==========================
SCRIPT_DIR = Path(__file__).resolve().parent

TARGET_COUNT = "all"  # 正整数 或 "all"
PROMPT = "参考图是芍药，一位年轻的中国男子蹲在户外的芍药花田里，他双手正扶着一株放在黑色塑料花盆上的健康芍药花苗，花苗长着许多红绿相间的饱满芽苞。在他脚下的草地上，并排横放着三株芍药根块，根系粗壮发达，带有泥土，顶部有很多红色的新芽。背景是大片盛开的红色、粉色和紫色芍药花海，远处有树木和几个模糊的人影。阴天，柔和的自然光线。他举着芍药说：比牡丹还漂亮的精品芍药花苗根全部处理了，都是带芽苞发货，收到家随便找个花盆塑料桶给它种上浇透水，很快就能开出拳头大的花，花瓣层层叠叠，淡雅清香，朋友来了都夸好看。种一次年年都有花看。"
# 支持上传多张参考图，按顺序填写。
REFERENCE_IMAGE_PATHS = [
    (SCRIPT_DIR / "芍药.png").resolve(),
]
RATIO = "9:16"
SAVE_DIR = (SCRIPT_DIR / "doubao_video_output").resolve()
THEME = "shaoyao"
HEADLESS = False

POOL_COOKIES_DIR = (SCRIPT_DIR / "cookies" / "doubao").resolve()
MAX_RETRY_PER_ACCOUNT = 2


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
                log(f"账号成功: {account_name} -> {saved_path}")
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
