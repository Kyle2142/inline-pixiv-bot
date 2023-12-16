#!/usr/bin/env python3

import asyncio
import configparser
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import telethon
from telethon.tl.functions.messages import (
    SetInlineBotResultsRequest, SendMultiMediaRequest, SetTypingRequest,
    UploadMediaRequest
)
from telethon.tl.types import (
    InputBotInlineResult, InputPhoto, InputMediaPhoto, InputSingleMedia,
    InputMediaPhotoExternal, SendMessageUploadPhotoAction, SendMessageUploadDocumentAction,
    InputBotInlineMessageMediaAuto, InputWebDocument
)

from custompixivpy import CustomPixivPy

IN_DOCKER = os.getenv('DOCKER', False)
LOG_FILE = 'logs/bot.log'
MAX_GROUPED_MEDIA = 10


async def gen_message(event, illust_id: int, title: str, user_id: int, user_name: str):
    text = f"<a href='https://www.pixiv.net/en/artworks/{illust_id}'>{title}</a>" \
           f" (<a href='https://pixiv.cat/{illust_id}.png'>full size</a>)" \
           f"\nUser: <a href='https://www.pixiv.net/en/users/{user_id}'>{user_name}</a>"
    # not sure of a better way to get the entities since I can't use event.builder
    return InputBotInlineMessageMediaAuto(*await event._client._parse_message_text(text, 'HTML'))


@telethon.events.register(telethon.events.InlineQuery(pattern=r"^(\d+)"))
async def inline_id_handler(event: telethon.events.InlineQuery.Event):
    illust_id = int(event.pattern_match.group(1))
    logger.info('Inline query %d: id=%d', event.id, illust_id)
    pixiv_data = pixiv.illust_detail(illust_id)
    if pixiv_data.get('error'):
        return  # allows other handler to take over

    illust = pixiv_data['illust']
    message = await gen_message(event, illust_id, illust['title'], illust['user']['id'], illust['user']['name'])

    if illust.get('meta_pages'):
        pages = illust['meta_pages']
    else:
        temp = illust['meta_single_page']
        temp.update(illust['image_urls'])
        temp.setdefault('original', temp['original_image_url'])
        pages = ({'image_urls': temp},)

    results = []
    for i, page in enumerate(pages):
        images = page['image_urls']
        thumb = InputWebDocument(images['medium'], 0, 'image/jpeg', [])
        content = InputWebDocument(images['original'], 0, 'image/jpeg', [])
        results.append(InputBotInlineResult(str(i), 'photo', message, thumb=thumb, content=content))

    try:
        await event.client(SetInlineBotResultsRequest(event.id, results, gallery=True,
                                                      cache_time=config['TG API'].getint('cache_time')))
    except telethon.errors.QueryIdInvalidError:
        pass
    except telethon.errors.RPCError:
        logger.warning("Inline query %d: Sending results failed", event.id, exc_info=True)
    else:
        logger.debug("Inline query %d: Complete", event.id)
    raise telethon.events.StopPropagation()


@telethon.events.register(telethon.events.InlineQuery(pattern="(?i)^(R18|NSFW)? ?(.+)?$"))
async def search_handler(event: telethon.events.InlineQuery.Event):
    cache_time = config['TG API'].getint('cache_time')

    offset = int(event.offset) if event.offset.isdigit() else 0
    # next_offset = offset + pixiv.RESULTS_PER_QUERY
    # if next_offset > pixiv.MAX_PIXIV_RESULTS:
    #     await event.answer(cache_time=cache_time)
    #     return
    nsfw = bool(event.pattern_match.group(1))

    logger.info("Inline query %d: text='%s' offset=%s", event.id, event.text, offset)

    # offset = offset // pixiv.RESULTS_PER_QUERY + 1
    pixiv_data, next_offset = pixiv.get_pixiv_results(offset, query=event.pattern_match.group(2), nsfw=nsfw)

    results = []
    for i, img in enumerate(pixiv_data):
        thumb = InputWebDocument(img['thumb_url'], 0, 'image/jpeg', [])
        content = InputWebDocument(img['url'], 0, 'image/jpeg', [])
        message = await gen_message(event, img['id'], img['title'], img['user_id'], img['user_name'])
        results.append(
            InputBotInlineResult(str(i + offset), 'photo', message, thumb=thumb, content=content, url=img['url'])
        )
    logger.debug("Inline query %d: Processed %d results", event.id, len(results))

    if not results:
        await event.answer(cache_time=cache_time)
        return

    try:
        await event.client(SetInlineBotResultsRequest(event.id, results, gallery=True, next_offset=str(next_offset),
                                                      cache_time=cache_time))
    except telethon.errors.QueryIdInvalidError:
        pass
    except telethon.errors.RPCError:
        logger.warning("Inline query %d: Sending results failed", event.id, exc_info=True)
    else:
        logger.debug("Inline query %d: Complete", event.id)


@telethon.events.register(telethon.events.NewMessage(pattern=r"(?i)/top( nsfw)?(?: (\d+))?"))
# pattern: nsfw mode and page num are optional
async def top_images(event: telethon.events.NewMessage.Event):
    match = event.pattern_match
    logger.info("New query: %s", match.group(0))

    await event.client(SetTypingRequest(event.input_chat, SendMessageUploadPhotoAction(0)))
    offset = int(match.group(2) or 0)
    results, _ = (pixiv.get_pixiv_results(offset, nsfw=bool(match.group(1))))
    n = 10
    for chunk in (results[i:i + n] for i in range(0, (n - 1) * n, n)):
        try:
            images = await event.client(
                [UploadMediaRequest(event.input_chat, InputMediaPhotoExternal(result['url'], ttl_seconds=86000))
                 for result in chunk]
            )
        except telethon.errors.MultiError as e:
            logger.warning("UploadMedia returned one or more errors")
            logging.debug('error: %s', e, exc_info=True)
            if not any(e.results):
                logger.exception("All UploadMedia requests failed")
                return
            images = filter(None, e.results)

        images = [InputSingleMedia(InputMediaPhoto(InputPhoto(img.photo.id, img.photo.access_hash, b'')), '') for img in
                  images]
        try:
            await event.client(SendMultiMediaRequest(event.input_chat, images))
        except (telethon.errors.UserIsBlockedError, telethon.errors.RPCError):  # TODO: add other relevant errors
            logger.exception("Failed to send multimedia")


@telethon.events.register(telethon.events.NewMessage(pattern=r"(?i)/logs?"))
async def send_logs(event: telethon.events.NewMessage.Event):
    if event.chat_id != config['main'].getint('owner telegram id'):  # cannot use from_users due to config undefined
        return
    if os.path.exists(LOG_FILE):
        await event.client(SetTypingRequest(event.input_chat, SendMessageUploadDocumentAction(0)))
        await event.reply(file=LOG_FILE)
    else:
        await event.reply("No log file found")


@telethon.events.register(telethon.events.NewMessage(pattern=r"(?i)/(start|help)$"))
async def start_help(event: telethon.events.NewMessage.Event):
    await event.reply(
        "Hello! I am meant to be used in inline mode."
        "\nIf you are not sure what that means, try typing <code>@inlinepixivbot</code> and a space. "
        "You will see today's top images from Pixiv.net!\n"
        "\nIf you want, you can also send <code>/top n</code> (in this chat!), <code>n</code> being an optional offset."
        "\n\nAnother optional feature is NSFW mode. Simply include \"NSFW\" or \"R18\" at the start: "
        "<code>@inlinepixivbot nsfw</code>"
        "\nThis will show you today's top NSFW images from Pixiv.net", parse_mode='HTML'
    )


async def main():
    pixiv.login(config['pixiv']['refresh_token'])
    await bot.connect()
    if not await bot.is_user_authorized() or not await bot.is_bot():
        await bot.start(bot_token=config['TG API']['bot_token'])
    logger.info('Started bot')
    await bot.run_until_disconnected()


if __name__ == "__main__":
    if not os.path.exists('config.ini'):
        raise FileNotFoundError('config.ini not found. Please copy example-config.ini and edit the relevant values')
    config = configparser.ConfigParser()
    config.read_file(open('config.ini'))

    logger = logging.getLogger()
    level = getattr(logging, config['main']['logging level'], logging.INFO)
    logger.setLevel(level)
    if not os.path.exists('logs'):
        os.mkdir('logs', 0o770)
    h = logging.handlers.RotatingFileHandler(LOG_FILE, encoding='utf-8', maxBytes=5 * 1024 * 1024, backupCount=5)
    h.setFormatter(logging.Formatter("%(asctime)s\t%(levelname)s:%(message)s"))
    h.setLevel(level)
    logger.addHandler(h)
    if IN_DOCKER:  # we are in docker, use stdout as well
        logger.addHandler(logging.StreamHandler(sys.stdout))

    pixiv = CustomPixivPy()

    bot = telethon.TelegramClient(config['TG API']['session'],
                                  config['TG API'].getint('api_id'), config['TG API']['api_hash'],
                                  auto_reconnect=True, connection_retries=1000)
    bot.flood_sleep_threshold = 5

    for f in (inline_id_handler, search_handler, top_images, send_logs, start_help):
        bot.add_event_handler(f)

    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
