import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.douyin_uploader.main import doubao_setup

if __name__ == '__main__':
    
    account_file = Path(BASE_DIR / "cookies" / "doubao" / "account1.json")
    account_file.parent.mkdir(exist_ok=True)
    cookie_setup = asyncio.run(doubao_setup(str(account_file), handle=True))

    
