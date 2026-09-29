from __future__ import annotations

import subprocess
import time
from pathlib import Path


# Dola水印只出现在右下角。比例参数来自584x1028成品截图的实测估算，
# 预留少量边距，兼容其他分辨率和相同比例的视频。
BOTTOM_RIGHT_X_START_RATIO = 0.83
BOTTOM_RIGHT_X_END_RATIO = 0.99
BOTTOM_RIGHT_Y_START_RATIO = 0.965
BOTTOM_RIGHT_Y_END_RATIO = 0.99

BLUR_LUMA_RADIUS = 8
BLUR_LUMA_POWER = 2

VIDEO_CODEC = "libx264"
VIDEO_PRESET = "medium"
VIDEO_CRF = 20
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"


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
    width_str, height_str = completed.stdout.strip().split("x", maxsplit=1)
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
    return x_start, y_start, x_end - x_start, y_end - y_start


def build_filter_complex(frame_w: int, frame_h: int) -> str:
    br_x, br_y, br_w, br_h = calc_region_by_ratio(
        frame_w,
        frame_h,
        BOTTOM_RIGHT_X_START_RATIO,
        BOTTOM_RIGHT_X_END_RATIO,
        BOTTOM_RIGHT_Y_START_RATIO,
        BOTTOM_RIGHT_Y_END_RATIO,
    )
    return (
        "[0:v]split=2[base][br_src];"
        f"[br_src]crop={br_w}:{br_h}:{br_x}:{br_y},"
        f"boxblur=luma_radius={BLUR_LUMA_RADIUS}:luma_power={BLUR_LUMA_POWER}[br_blur];"
        f"[base][br_blur]overlay={br_x}:{br_y}[vout]"
    )


def process_one_video_to_path(
    input_path: Path, output_path: Path, overwrite: bool = False
) -> None:
    frame_w, frame_h = probe_video_size(input_path)
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
        build_filter_complex(frame_w, frame_h),
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
        f"{source_path.stem}.dola_blur_tmp_{time.time_ns()}{source_path.suffix}"
    )
    try:
        process_one_video_to_path(source_path, temp_output, overwrite=True)
        if not temp_output.exists():
            raise RuntimeError(f"Dola模糊输出临时文件不存在: {temp_output}")
        temp_output.replace(source_path)
    finally:
        if temp_output.exists():
            temp_output.unlink()
