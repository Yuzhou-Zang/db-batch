import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.tencent_uploader.main import weixin_setup, TencentVideo
from utils.constant import TencentZoneTypes
# from utils.files_times import generate_schedule_time_next_day, get_title_and_hashtags
from utils.files_times import generate_schedule_time_from_today

if __name__ == '__main__':
    filepath = Path(BASE_DIR) / "居家"
    # filepath = 'D:/code/wenan/r3'

    account_file = Path(BASE_DIR / "cookies" / "tencent_uploader" / "account.json")

    # 获取视频目录
    folder_path = Path(filepath)
    # 获取文件夹中的所有文件
    files = list(folder_path.glob("*.mp4"))
    file_num = len(files)

    # 每天几点发布
    daily_times=[19]
    # 发多少天
    tianshu = 14
    publish_datetimes = generate_schedule_time_from_today(total_videos = 200, daily_times = daily_times, start_days = 0)[0:tianshu * len(daily_times)]
    cookie_setup = asyncio.run(weixin_setup(account_file, handle=True))
    # category = TencentZoneTypes.LIFESTYLE.value  # 标记原创需要否则不需要传
    
    for index, file in enumerate(files):
        # title, tags = get_title_and_hashtags(str(file))
        # 打印视频文件名、标题和 hashtag
        title = '点我头像一商品橱窗一搜索好物，例如【置物架】'
        tags = ['家居好物', '好物推荐']

        print(f"视频文件名：{file}")
        print(f"标题：{title}")
        print(f"Hashtag：{tags}")
        app = TencentVideo(title, file, tags, publish_datetimes[index], account_file)
        asyncio.run(app.main(), debug=False)
