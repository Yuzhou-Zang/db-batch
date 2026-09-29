from datetime import timedelta

from datetime import datetime
from pathlib import Path

from conf import BASE_DIR


def get_absolute_path(relative_path: str, base_dir: str = None) -> str:
    # Convert the relative path to an absolute path
    absolute_path = Path(BASE_DIR) / base_dir / relative_path
    return str(absolute_path)


def get_title_and_hashtags(filename):
    """
  获取视频标题和 hashtag

  Args:
    filename: 视频文件名

  Returns:
    视频标题和 hashtag 列表
  """

    # 获取视频标题和 hashtag txt 文件名
    txt_filename = filename.replace(".mp4", ".txt")

    # 读取 txt 文件
    with open(txt_filename, "r", encoding="utf-8") as f:
        content = f.read()

    # 获取标题和 hashtag
    splite_str = content.strip().split("\n")
    title = splite_str[0]
    hashtags = splite_str[1].replace("#", "").split(" ")

    return title, hashtags


def generate_schedule_time_next_day(total_videos, videos_per_day = 1, daily_times=None, timestamps=False, start_days=0):
    """
    Generate a schedule for video uploads, starting from the next day.

    Args:
    - total_videos: Total number of videos to be uploaded.
    - videos_per_day: Number of videos to be uploaded each day.
    - daily_times: Optional list of specific times of the day to publish the videos.
    - timestamps: Boolean to decide whether to return timestamps or datetime objects.
    - start_days: Start from after start_days.

    Returns:
    - A list of scheduling times for the videos, either as timestamps or datetime objects.
    """
    if videos_per_day <= 0:
        raise ValueError("videos_per_day should be a positive integer")

    if daily_times is None:
        # Default times to publish videos if not provided
        daily_times = [6, 11, 14, 16, 22]

    if videos_per_day > len(daily_times):
        raise ValueError("videos_per_day should not exceed the length of daily_times")

    # Generate timestamps
    schedule = []
    current_time = datetime.now()

    for video in range(total_videos):
        day = video // videos_per_day + start_days + 1  # +1 to start from the next day
        daily_video_index = video % videos_per_day

        # Calculate the time for the current video
        hour = daily_times[daily_video_index]
        time_offset = timedelta(days=day, hours=hour - current_time.hour, minutes=-current_time.minute,
                                seconds=-current_time.second, microseconds=-current_time.microsecond)
        timestamp = current_time + time_offset

        schedule.append(timestamp)

    if timestamps:
        schedule = [int(time.timestamp()) for time in schedule]
    return schedule
def get_image_title_and_hashtags(filename):
    """
  获取视频标题和 hashtag

  Args:
    filename: 视频文件名

  Returns:
    视频标题和 hashtag 列表
  """

    # 获取视频标题和 hashtag txt 文件名
    txt_filename = filename.replace(".jpg", ".txt").replace(".png", ".txt").replace(".jpeg", ".txt")

    # 读取 txt 文件
    with open(txt_filename, "r", encoding="utf-8") as f:
        content = f.read()

    # 获取标题和 hashtag
    splite_str = content.strip().split("\n")
    title = splite_str[0]
    hashtags = splite_str[1].replace("#", "").split(" ")

    return title, hashtags
def get_graphic_productinfo(filename):
    """
  获取视频标题和 hashtag

  Args:
    filename: 视频文件名

  Returns:
    视频标题（graphic_title）、hashtag列表、完整产品信息字典
  """

    # 获取视频标题和 hashtag txt 文件名
    txt_filename = filename.replace(".jpg", ".txt").replace(".png", ".txt").replace(".jpeg", ".txt")

    # 读取 txt 文件
    with open(txt_filename, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]  # 去除空行和首尾空格

    
    
    if len(lines) >= 4:
        # 解析前四行固定内容
        product_url = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else lines[0]
        product_title = lines[1].split(":", 1)[1].strip() if ":" in lines[1] else lines[1]
        graphic_title = lines[2].split(":", 1)[1].strip() if ":" in lines[2] else lines[2]
        hottags = lines[3].split(":", 1)[1].strip() if ":" in lines[3] else lines[3]
        
        # 剩余所有行作为graphic_content（包括多行内容）
        if len(lines) > 4:
            # 处理第五行及以后的内容
            graphic_content_lines = lines[4:]
            # 如果第五行有key前缀，去掉前缀后再拼接
            if ":" in graphic_content_lines[0]:
                first_line_content = graphic_content_lines[0].split(":", 1)[1].strip()
                graphic_content = first_line_content + "\n" + "\n".join(graphic_content_lines[1:])
            else:
                graphic_content = "\n".join(graphic_content_lines)
        else:
            graphic_content = ""
    else:
        # 处理文件内容不完整的情况
        raise ValueError("文件内容格式不正确，缺少必要的行")

    # 解析hashtags为列表
    # hashtags_list = [tag.strip() for tag in product_info["hottags"].replace("#", "").split(",") if tag.strip()]

    # 返回graphic_title、hashtag列表和完整产品信息
    return product_url, product_title, graphic_title, hottags, graphic_content
def generate_schedule_time_from_today(total_videos, videos_per_day=None, daily_times=None, timestamps=False, start_days=0):
    """
    生成视频上传排期，从今天开始。
    如果当前时间已过当天某个时间点，则跳过该时间点，使用下一个可用时间点。
    按顺序循环使用时间点，超出当天的自动顺延到次日。

    参数:
    - total_videos: 需要上传的视频总数
    - videos_per_day: 每天发布的视频数量（None表示不限制，按时间点数量自动分配）
    - daily_times: 可选的每日发布时间点列表（小时数）
    - timestamps: 是否返回时间戳而非datetime对象
    - start_days: 起始偏移天数（从今天+start_days天后开始）

    返回:
    - 排期时间列表，包含datetime对象或时间戳
    """
    # 验证视频总数必须为正整数
    if total_videos <= 0:
        raise ValueError("total_videos应该是正整数")

    # 设置默认发布时间点，如果用户未提供
    if daily_times is None:
        daily_times = [6, 11, 14, 16, 22]
    
    # 对时间点进行排序，确保按时间顺序处理
    daily_times = sorted(daily_times)
    
    # 如果未指定每天发布数量，则默认使用所有时间点
    if videos_per_day is None:
        videos_per_day = len(daily_times)
    elif videos_per_day <= 0:
        raise ValueError("videos_per_day应该是正整数")

    schedule = []
    current_time = datetime.now() + timedelta(hours=2) 
    base_start_day = start_days  # 基础起始天数偏移量

    # 获取当前时间的具体时分秒
    current_hour = current_time.hour
    current_minute = current_time.minute
    current_second = current_time.second
    
    # 查找第一个可用的时间槽（大于当前时间的时间点）
    start_day_offset = 0
    first_available_idx = 0
    
    # 遍历所有时间点，找到第一个未过期的时间点
    for i, hour in enumerate(daily_times):
        # 检查当前时间是否已过该时间点
        if hour > current_hour:
            first_available_idx = i
            break
        elif hour == current_hour:
            # 如果是当前小时，检查是否已过整点
            if current_minute == 0 and current_second == 0:
                first_available_idx = i
                break
        # 如果所有时间点都已过期，顺延到明天
        if i == len(daily_times) - 1:
            start_day_offset = 1
            first_available_idx = 0

    # 计算总的起始天数
    total_days_offset = base_start_day + start_day_offset
    current_day = total_days_offset
    current_time_idx = first_available_idx
    videos_scheduled = 0

    # 循环生成排期，直到达到视频总数
    while videos_scheduled < total_videos:
        # 获取当前要使用的时间点
        scheduled_hour = daily_times[current_time_idx]
        
        # 创建排期时间对象
        scheduled_datetime = current_time.replace(
            hour=scheduled_hour,
            minute=0,
            second=0,
            microsecond=0
        ) + timedelta(days=current_day)
        
        schedule.append(scheduled_datetime)
        videos_scheduled += 1
        
        # 移动到下一个时间点
        current_time_idx += 1
        
        # 如果用完了当天的所有时间点，切换到下一天
        if current_time_idx >= len(daily_times):
            current_time_idx = 0
            current_day += 1

    # 如果需要返回时间戳，转换格式
    if timestamps:
        schedule = [int(dt.timestamp()) for dt in schedule]
    
    return schedule
