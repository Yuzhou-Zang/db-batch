from __future__ import annotations

import subprocess
import time
from pathlib import Path

# ==========================
# 可调参数（按你的习惯直接改这里）
# ==========================
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = (SCRIPT_DIR / "doubao_video_output_blur").resolve()
OUTPUT_PREFIX = "blur_"
INPUT_VIDEO_PATHS = [
    # Path(r"D:\code\social-auto-upload\doubao_video_output\shaoyao_1779713075_生成芍药花苗视频.mp4")
]
# 可选：填入一个或多个目录，自动处理目录下视频
INPUT_VIDEO_DIRS = [
    Path(r"D:\code\social-auto-upload\doubao_video_output"),
]
# True=递归处理子目录；False=仅处理目录第一层
SCAN_SUBDIRECTORIES = True

ALLOWED_INPUT_SUFFIXES = {".mp4"}

# 右下角水印区域估算
BOTTOM_RIGHT_X_START_RATIO = 0.68
BOTTOM_RIGHT_X_END_RATIO = 0.96
BOTTOM_RIGHT_Y_START_RATIO = 0.93
BOTTOM_RIGHT_Y_END_RATIO = 0.98

# 左上角模糊区域（对称于右下水印区域）
TOP_LEFT_X_START_RATIO = 1 - BOTTOM_RIGHT_X_END_RATIO
TOP_LEFT_X_END_RATIO = 1 - BOTTOM_RIGHT_X_START_RATIO
TOP_LEFT_Y_START_RATIO = 1 - BOTTOM_RIGHT_Y_END_RATIO
TOP_LEFT_Y_END_RATIO = 1 - BOTTOM_RIGHT_Y_START_RATIO



# 毛玻璃强度（ffmpeg boxblur）
BLUR_LUMA_RADIUS = 8
BLUR_LUMA_POWER = 2

# 输出编码参数
VIDEO_CODEC = "libx264"
VIDEO_PRESET = "medium"
VIDEO_CRF = 20
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"


def log(message: str) -> None:
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {message}")


def probe_video_size(video_path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        str(video_path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    output = completed.stdout.strip()
    width_str, height_str = output.split("x", maxsplit=1)
    return int(width_str), int(height_str)


def calc_region_by_ratio(
    frame_w: int,
    frame_h: int,
    x_start_ratio: float,
    x_end_ratio: float,
    y_start_ratio: float,
    y_end_ratio: float,
) -> tuple[int, int, int, int]:
    x_start = int(frame_w * x_start_ratio)
    x_end = int(frame_w * x_end_ratio)
    y_start = int(frame_h * y_start_ratio)
    y_end = int(frame_h * y_end_ratio)

    x_start = max(0, min(x_start, frame_w - 1))
    y_start = max(0, min(y_start, frame_h - 1))
    x_end = max(x_start + 2, min(x_end, frame_w))
    y_end = max(y_start + 2, min(y_end, frame_h))

    region_w = x_end - x_start
    region_h = y_end - y_start
    return x_start, y_start, region_w, region_h


def build_filter_complex(frame_w: int, frame_h: int) -> str:
    tl_x, tl_y, tl_w, tl_h = calc_region_by_ratio(
        frame_w,
        frame_h,
        TOP_LEFT_X_START_RATIO,
        TOP_LEFT_X_END_RATIO,
        TOP_LEFT_Y_START_RATIO,
        TOP_LEFT_Y_END_RATIO,
    )
    br_x, br_y, br_w, br_h = calc_region_by_ratio(
        frame_w,
        frame_h,
        BOTTOM_RIGHT_X_START_RATIO,
        BOTTOM_RIGHT_X_END_RATIO,
        BOTTOM_RIGHT_Y_START_RATIO,
        BOTTOM_RIGHT_Y_END_RATIO,
    )

    return (
        "[0:v]split=3[base][tl_src][br_src];"
        f"[tl_src]crop={tl_w}:{tl_h}:{tl_x}:{tl_y},"
        f"boxblur=luma_radius={BLUR_LUMA_RADIUS}:luma_power={BLUR_LUMA_POWER}[tl_blur];"
        f"[br_src]crop={br_w}:{br_h}:{br_x}:{br_y},"
        f"boxblur=luma_radius={BLUR_LUMA_RADIUS}:luma_power={BLUR_LUMA_POWER}[br_blur];"
        f"[base][tl_blur]overlay={tl_x}:{tl_y}[tmp1];"
        f"[tmp1][br_blur]overlay={br_x}:{br_y}[vout]"
    )


def process_one_video(input_path: Path, output_path: Path) -> None:
    process_one_video_to_path(input_path, output_path, overwrite=False)


def process_one_video_to_path(
    input_path: Path, output_path: Path, overwrite: bool = False
) -> None:
    frame_w, frame_h = probe_video_size(input_path)
    filter_complex = build_filter_complex(frame_w, frame_h)
    overwrite_flag = "-y" if overwrite else "-n"

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        overwrite_flag,
        "-i",
        str(input_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        "-c:v",
        VIDEO_CODEC,
        "-preset",
        VIDEO_PRESET,
        "-crf",
        str(VIDEO_CRF),
        "-c:a",
        AUDIO_CODEC,
        "-b:a",
        AUDIO_BITRATE,
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def blur_video_inplace(video_path: Path) -> None:
    source_path = Path(video_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"待模糊文件不存在: {source_path}")
    if not source_path.is_file():
        raise ValueError(f"待模糊路径不是文件: {source_path}")

    temp_output = source_path.with_name(
        f"{source_path.stem}.blur_tmp_{time.time_ns()}{source_path.suffix}"
    )
    try:
        process_one_video_to_path(source_path, temp_output, overwrite=True)
        if not temp_output.exists():
            raise RuntimeError(f"模糊输出临时文件不存在: {temp_output}")
        temp_output.replace(source_path)
    finally:
        if temp_output.exists():
            temp_output.unlink()


def resolve_input_files() -> tuple[list[Path], int, dict[str, int]]:
    valid_files: list[Path] = []
    invalid_count = 0
    seen_paths: set[Path] = set()
    source_stats = {
        "from_paths": 0,
        "from_dirs": 0,
        "duplicates": 0,
    }

    def try_add_video_file(raw_path: Path | str, source_key: str) -> None:
        nonlocal invalid_count

        input_path = Path(raw_path).expanduser().resolve()
        input_suffix = input_path.suffix.lower()

        if input_path in seen_paths:
            source_stats["duplicates"] += 1
            log(f"跳过重复输入: {input_path}")
            return
        seen_paths.add(input_path)

        if not input_path.exists():
            invalid_count += 1
            log(f"无效输入（文件不存在）: {input_path}")
            return
        if not input_path.is_file():
            invalid_count += 1
            log(f"无效输入（不是文件）: {input_path}")
            return
        if input_suffix not in ALLOWED_INPUT_SUFFIXES:
            invalid_count += 1
            log(
                "无效输入（文件后缀不支持）: "
                f"{input_path}，支持后缀: {sorted(ALLOWED_INPUT_SUFFIXES)}"
            )
            return

        valid_files.append(input_path)
        source_stats[source_key] += 1

    for raw_path in INPUT_VIDEO_PATHS:
        try_add_video_file(raw_path, "from_paths")

    for raw_dir in INPUT_VIDEO_DIRS:
        input_dir = Path(raw_dir).expanduser().resolve()
        if not input_dir.exists():
            invalid_count += 1
            log(f"无效目录（不存在）: {input_dir}")
            continue
        if not input_dir.is_dir():
            invalid_count += 1
            log(f"无效目录（不是目录）: {input_dir}")
            continue

        if SCAN_SUBDIRECTORIES:
            candidates = sorted(
                [
                    p
                    for p in input_dir.rglob("*")
                    if p.is_file() and p.suffix.lower() in ALLOWED_INPUT_SUFFIXES
                ],
                key=lambda p: str(p).lower(),
            )
        else:
            candidates = sorted(
                [
                    p
                    for p in input_dir.glob("*")
                    if p.is_file() and p.suffix.lower() in ALLOWED_INPUT_SUFFIXES
                ],
                key=lambda p: str(p).lower(),
            )

        if not candidates:
            log(f"目录无匹配视频: {input_dir}")
            continue

        for candidate in candidates:
            try_add_video_file(candidate, "from_dirs")

    return valid_files, invalid_count, source_stats


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_files, invalid_count, source_stats = resolve_input_files()
    run_timestamp = time.strftime("%Y%m%d_%H%M%S")

    if not input_files:
        log("没有可处理的有效输入文件，请检查 INPUT_VIDEO_PATHS。")
        return

    success = 0
    skipped = 0
    failed = 0

    log(f"输入文件数: {len(input_files)}")
    log(
        f"来源统计: 手工文件={source_stats['from_paths']}, "
        f"目录扫描={source_stats['from_dirs']}, 重复跳过={source_stats['duplicates']}"
    )
    log(f"输出目录: {OUTPUT_DIR}")
    log(f"输出前缀: {OUTPUT_PREFIX}{run_timestamp}_")
    if invalid_count:
        log(f"无效输入数量: {invalid_count}")
    log(f"开始处理 {len(input_files)} 个视频...")

    for idx, input_path in enumerate(input_files, start=1):
        output_name = f"{OUTPUT_PREFIX}{run_timestamp}_{input_path.stem}{input_path.suffix}"
        output_path = OUTPUT_DIR / output_name

        if output_path.exists():
            skipped += 1
            log(f"[{idx}/{len(input_files)}] 跳过（输出已存在）: {output_path.name}")
            continue

        try:
            process_one_video(input_path, output_path)
            success += 1
            log(f"[{idx}/{len(input_files)}] 完成: {input_path.name} -> {output_path.name}")
        except subprocess.CalledProcessError as exc:
            failed += 1
            log(f"[{idx}/{len(input_files)}] 失败: {input_path.name} ({exc})")
        except Exception as exc:
            failed += 1
            log(f"[{idx}/{len(input_files)}] 失败: {input_path.name} ({exc})")

    log("处理结束")
    log(f"成功: {success}")
    log(f"跳过: {skipped}")
    log(f"失败: {failed}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        log(str(exc))
    except subprocess.CalledProcessError as exc:
        log(f"ffmpeg/ffprobe 执行失败: {exc}")
    except Exception as exc:
        log(f"未处理异常: {exc}")
