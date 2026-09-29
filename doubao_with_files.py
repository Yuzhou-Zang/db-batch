import asyncio
from pathlib import Path
import time
from uploader.douyin_image_uploader.main import douyin_setup, DouYinImage

from conf import BASE_DIR
from uploader.douyin_uploader.main import doubao_setup, doubao
from utils.files_times import generate_schedule_time_next_day, get_title_and_hashtags

from datetime import timedelta
from datetime import datetime
from pathlib import Path
import os
from upload_image_to_douyin图文_basic_tuwen import main as upload_image_main

if __name__ == '__main__':

    # 账号
    # account_file = Path(BASE_DIR / "cookies" / "doubao" / "shanhedadi.json")
    account_file = Path(BASE_DIR / "cookies" / "doubao" / "account.json")
    cookie_setup = asyncio.run(doubao_setup(account_file, handle=False))
    app = doubao(account_file)

    # 生图提示词
    folder = '/code/social-auto-upload/doubao_file/' 
    txt_file = '女穿男装.txt'
    with open(folder + '/' +  txt_file, "r", encoding='utf-8') as file:
        content = file.readlines()
    promt = ''
    for line in content:
        promt += line[:-1]
    text = promt

    # 上传图片路径
    theme = '女穿男2'
    upload_file_path = Path(BASE_DIR) / "doubao_file" / theme 
    # 下载图片路径
    savefolder = 'dianshang_result/' +  theme + '_' + str(time.time())[:10] + '/'
    # 豆包跑图
    dld_n = 4
    asyncio.run(app.main_with_files(dld_n, text, savefolder, theme, upload_file_path), debug=False)

    # 图文上传抖音
    # savefolder = 'dianshang_result/毛衣_1766143955/'
    tmp = savefolder.split('/')
    subfolder = Path(BASE_DIR) / tmp[0] / tmp[1]

    hao = "shanhedadi.json"
    publish_date = 0
    # account_file = Path(BASE_DIR) / "cookies" / "douyin_uploader" / "pingpingli.json"
    account_file = Path(BASE_DIR) / "cookies" / "douyin_uploader" / hao

    asyncio.run(douyin_setup(account_file, handle=False))
    image_files = []
    for ext in ["*.jpeg", "*.jpg", "*.png", "*.gif", "*.webp"]:
        image_files.extend(subfolder.glob(ext))
    
    graphic_title = ""
    # hottags = "#女装 #冬季服装"
    hottags = "#男装 #冬季服装"
    graphic_content = ""

    folder = 'doubao_file/' + theme
    txt_file = [i for i in os.listdir(folder) if i[-3:] == 'txt' or i[-3:] == 'srt'][0]
    with open(folder + '/' +  txt_file, "r", encoding='utf-8') as file:
        content = file.readlines()
    product_url = content[0][:-1]

    product_title = "视频同款"
    uploader = DouYinImage(
        graphic_title=graphic_title,
        hottags=hottags,
        graphic_content=graphic_content,
        file_path=image_files,
        publish_date=publish_date,
        account_file=account_file,
        product_url=product_url,
        music_id= 1,  # 指定音乐ID
        check= True,
        product_title=product_title
    )

    # 执行上传
    asyncio.run(uploader.main())





    # tmp = savefolder.split('/')
    # asyncio.run(upload_image_main(subfolder = Path(BASE_DIR) / tmp[0] / tmp[1]), debug=False)

    # asyncio.run(upload_image_main(subfolder = Path(BASE_DIR) / "story_image" / "大爷买菜_1766049083"), debug=False)

    # dld_n = 4
    # text = f"生成{dld_n}张图，比例9:16，第一张：一个中年美丽大姐穿着图中的商品，在高档服装店，看向镜头微笑。第二张：一个中年美丽大姐穿着图中的商品，在高级装修的家里，看向镜头微笑。第三张：一个中年美丽大姐穿着图中的商品，在高档餐厅，看向镜头微笑。第四张：一个中年美丽大姐穿着图中的商品，在高档咖啡店，看向镜头微笑。"
    # dld_n = 1
    # text = "生成一张图：一个中年美丽大姐穿着图中的商品，在高档服装店，看向镜头微笑"

    # product_url = False
    # product_url = "https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id=3714101951915491346&origin_type=pc_buyin_selection_decision"
