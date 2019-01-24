#InlinePixivBot
A simple Telegram bot which mainly provides inline mode, fetching illustrations from [Pixiv](https://pixiv.net)

You can view my instance of it at [@InlinePixivBot](https://t.me/inlinepixivbot)
##Requirements
* Python 3.5 or higher

The following can be automatically installed using `requirements.txt` (refer to next section)
* [Telethon](https://github.com/LonamiWebs/Telethon)
* [Pyxiv](https://github.com/Kyle2142/pyxiv) (an `aiohttp` port of [pixivpy](https://github.com/upbit/pixivpy))

##Installation

These steps are intended for unix-like systems but are easily translated for others

1. `git clone https://github.com/Kyle2142/inline-pixiv-bot`
2. `cd inline-pixiv-bot`
3. Optional: set up a virtualenv
    1. `virtualenv -p /usr/bin/python3 .`
    2. `source ./bin/activate`
4. `pip3 install -r requirements.txt`
5. Copy and edit config.
    1. `cp example-config.ini config.ini`
    2. `nano config.ini` (use your preferred editor)

##Running
Simply `python3 inlinepixivbot.py`

It is recommended you use a program like `tmux` or `screen`

Logs are stored in `logs/bot.log` and will automatically rotate up to a maximum of 5 5MB files

##License

Feel free to do what you like with this, but please credit me :)
