import asyncio
from pathlib import Path
import time
from uploader.douyin_image_uploader.main import douyin_setup, DouYinImage
import random
from conf import BASE_DIR
from uploader.douyin_uploader.main import doubao_setup, doubao
from utils.files_times import generate_schedule_time_from_today, get_title_and_hashtags

from datetime import timedelta
from datetime import datetime
from pathlib import Path
import os
from upload_image_to_douyin图文_basic_tuwen import basic_tuwen 


if __name__ == '__main__':

    # 账号
    # account_file = Path(BASE_DIR / "cookies" / "doubao" / "shanhedadi.json")
    account_file = Path(BASE_DIR / "cookies" / "doubao" / "account.json")

    # cookie_setup = asyncio.run(doubao_setup(account_file, handle=False))
    app = doubao(account_file)

    style = '写实'
    # style = '铅笔画风格'
    # style = '版画风格'
    # style = '雕塑风格'
    # style = '可爱动画风格'
    # style = '像素画风格'
    # style = '抽象主义风格'
    # style = '老照片风格'
    # style = '电影风格'
    # style = '电影级质感'

    name = '大爷买菜'
    # name = '叔叔带娃'
    # name = '后妈'
    # name = '武汉站'
    # name = '单亲爸爸'


    folder = '/code/social-auto-upload/story/' + name

    txt_file = [i for i in os.listdir(folder) if 'txt'  or 'srt' in i][0]
    with open(folder + '/' +  txt_file, "r", encoding='utf-8') as file:
        content = file.readlines()
    story = content[0][:-1]


    dld_n = 3
    prompt = f"我是个故事短视频作者，请你把下面这段故事配图，图片中不要出现汉字，共配{dld_n}张图，画面风格为：{style}，比例9:16。"
    
    
    text = prompt + story
    theme = name

    tt = generate_schedule_time_from_today(total_videos = 1 * 100, daily_times=[ 7, 13 , 19 ], start_days = 0)[0:6]
    # tt = [0]

    for t in range(tt):  
        savefolder = 'story_image/' + name + '_' +  str(time.time())[:10] + '/'
        # 豆包跑图
        asyncio.run(app.main(dld_n, text, savefolder, theme), debug=False)

        # 图文上传抖音
        tmp = savefolder.split('/')
        upload_folder = Path(BASE_DIR) / tmp[0] / tmp[1]
        image_files = []
        for ext in ["*.jpeg", "*.jpg", "*.png", "*.gif", "*.webp"]:
            image_files.extend(upload_folder.glob(ext))

        asyncio.run(douyin_setup(account_file, handle=False))


        take_account = ["pingpingli.json"]

        graphic_title = ""
        hottags = "#民间故事 #真实的故事"
        graphic_content = ""
        product_title = False
        product_url = None
        # product_url = None
        # check = False
        check = True
        music_id= 1  # 指定音乐ID

        basic_tuwen(tt, take_account, image_files, graphic_title, hottags, graphic_content, product_title, product_url, check, music_id)
