import asyncio
from datetime import datetime
from pathlib import Path

from conf import BASE_DIR
from uploader.tencent_uploader.main import weixin_setup

def clear_tencent_uploader_files() -> int:
    target_dir = Path(r"D:\code\social-auto-upload\cookies\tencent_uploader")
    if not target_dir.exists():
        return 0
    deleted = 0
    for p in target_dir.rglob("*"):
        if p.is_file() or p.is_symlink():
            p.unlink()
            deleted += 1
    return deleted


if __name__ == '__main__':

    # deleted = clear_tencent_uploader_files()
    # print(f"已删除 {deleted} 个文件")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    account_file = Path(BASE_DIR / "cookies" / "tencent_uploader" / f"account_{timestamp}.json")
    account_file.parent.mkdir(exist_ok=True)
    cookie_setup = asyncio.run(weixin_setup(str(account_file), handle=True))



