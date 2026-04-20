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

* [uv](https://docs.astral.sh/uv/)
  * This will find/create an appropriate python env as needed

## Installation

These steps are intended for unix-like systems but are easily translated for others

1. `git clone https://github.com/Kyle2142/inline-pixiv-bot`
2. `cd inline-pixiv-bot`
3. Copy and edit config.
    1. `cp example-config.ini config.ini`
    2. `nano config.ini` (use your preferred editor)

## Running

Simply `uv run inlinepixivbot.py`

You can use a program like `tmux` or `screen` to keep this as a background service.
Alternatively, here is a sample `systemd` service file:
```
[Unit]
Description=Inline telegram bot for pixiv
After=network.target

[Service]
WorkingDirectory=/path/to/inlinepixivbot/folder
# .venv can be created with `uv sync`
ExecStart=.venv/bin/python inlinepixivbot.py
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
Logs are stored in `logs/bot.log` and will automatically rotate up to a maximum of 5 files (5MB each)


## Tests

`uv run pytest tests/`
