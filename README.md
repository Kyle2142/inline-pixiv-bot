InlinePixivBot
==============
A simple Telegram bot which mainly provides inline mode, fetching illustrations from [Pixiv](https://pixiv.net)

You can view my instance of it at [@InlinePixivBot](https://t.me/inlinepixivbot)

## Quick start: Docker install/run

1. download `example-config.ini` into a memorable location (perhaps `~/.config/inline-pixiv-bot`?) and edit it as per the installation section.
2. Fire up docker! It will use the config file from the previous step.
```bash
docker run -d --name inline-pixiv-bot \
    -v ~/.config/inline-pixiv-bot/config.ini:/usr/src/app/config.ini \
    -v ~/.config/inline-pixiv-bot/bot.session:/usr/src/app/bot.session \
    kyle2142/inline-pixiv-bot:latest
```
The second `-v` line is optional and is only for re-using a session file (it must exist).  
Note that if you are running this on a PC/laptop, you will likely need to configure file sharing for the config file.  
As a docker-only feature, `docker logs inline-pixiv-bot` works.

## Requirements
* Python 3.5 or higher

The following can be automatically installed using `requirements.txt` (refer to next section)
* [Telethon](https://github.com/LonamiWebs/Telethon)
* [Pixivpy-async](https://github.com/Mikubill/pixivpy-async)

## Installation

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

## Running
Simply `python3 inlinepixivbot.py`

You can use a program like `tmux` or `screen` to keep this as a background service.
Alternatively, here is a sample `systemd` service file:
```
[Unit]
Description=Inline telegram bot for pixiv
After=network.target

[Service]
WorkingDirectory=/path/to/inlinepixivbot/folder
#note that the below assumes you have a venv as per step 3 above
ExecStart=/path/to/inlinepixivbot/folder/bin/python inlinepixivbot.py
TimeoutStopSec=10
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
You can install this by
```bash
sudo systemctl edit --force -l inlinepixivbot
sudo systemctl enable inlinepixivbot  # if you want the bot started on reboot
sudo systemctl start inlinepixivbot
```
Logs are stored in `logs/bot.log` and will automatically rotate up to a maximum of 5 5MB files
