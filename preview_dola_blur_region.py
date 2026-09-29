from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from dola_blur import (
    BOTTOM_RIGHT_X_END_RATIO,
    BOTTOM_RIGHT_X_START_RATIO,
    BOTTOM_RIGHT_Y_END_RATIO,
    BOTTOM_RIGHT_Y_START_RATIO,
    calc_region_by_ratio,
)


def draw_dola_blur_region(input_path: Path, output_path: Path) -> tuple[int, int, int, int]:
    with Image.open(input_path) as source:
        image = source.convert("RGB")
        x, y, width, height = calc_region_by_ratio(
            image.width,
            image.height,
            BOTTOM_RIGHT_X_START_RATIO,
            BOTTOM_RIGHT_X_END_RATIO,
            BOTTOM_RIGHT_Y_START_RATIO,
            BOTTOM_RIGHT_Y_END_RATIO,
        )

        # 使用醒目的红色空心框标出实际模糊范围，不遮住框内水印。
        line_width = max(3, round(min(image.width, image.height) * 0.006))
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (x, y, x + width - 1, y + height - 1),
            outline=(255, 0, 0),
            width=line_width,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="PNG")
        return x, y, width, height


def main() -> None:
    parser = argparse.ArgumentParser(description="在图片上预览Dola右下角模糊区域")
    parser.add_argument("input", type=Path, help="输入图片路径")
    parser.add_argument("output", type=Path, help="输出PNG路径")
    args = parser.parse_args()

    region = draw_dola_blur_region(args.input, args.output)
    print(f"图片尺寸与矩形区域处理完成，region={region}")
    print(f"预览图片已保存: {args.output.resolve()}")


if __name__ == "__main__":
    main()
