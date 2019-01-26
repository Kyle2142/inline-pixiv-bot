#!/usr/bin/env python

import asyncio
import configparser
import logging
import os
from logging.handlers import RotatingFileHandler

import telethon
from telethon.tl.functions.messages import SetInlineBotResultsRequest, SendMultiMediaRequest, SetTypingRequest, \
    UploadMediaRequest
from telethon.tl.types import InputBotInlineResult, InputPhoto, InputMediaPhoto, InputSingleMedia, \
    InputMediaPhotoExternal, SendMessageUploadPhotoAction, InputBotInlineMessageMediaAuto, InputWebDocument

from custompyxiv import CustomPyxiv

MAX_GROUPED_MEDIA = 10
RESULTS_PER_QUERY = 30


@telethon.events.register(telethon.events.InlineQuery(pattern="(?i)^(R18|NSFW)? ?(.+)?$"))
async def inline_handler(event: telethon.events.InlineQuery.Event):
    offset = int(event.offset) if event.offset.isdigit() else 0
    next_offset = offset + RESULTS_PER_QUERY
    if next_offset > pixiv.MAX_PIXIV_RESULTS:
        await event.answer(cache_time=86000)
        return
    nsfw = bool(event.pattern_match.group(1))
    ranking = 'day_r18' if nsfw else 'day'

    logger.info("Inline query %d: text='%s' offset=%s", event.id, event.text, event.offset or '0')

    pixiv_data = await pixiv.get_pixiv_results(offset, query=event.pattern_match.group(2), ranking=ranking, nsfw=nsfw)

    results = []
    for i, img in enumerate(pixiv_data):
        thumb = InputWebDocument(img['thumb_url'], 0, 'image/jpeg', [])
        content = InputWebDocument(img['url'], 0, 'image/jpeg', [])
        results.append(
            InputBotInlineResult(str(i), 'photo', InputBotInlineMessageMediaAuto(
                "Title: {}\nUser: {}".format(img['title'], img['user'])), thumb=thumb, content=content)
        )
    logger.debug("Inline query %d: Processed %d results", event.id, len(results))

    try:
        await event.client(SetInlineBotResultsRequest(event.id, results, next_offset=str(next_offset),
                                                      cache_time=config['TG API'].getint('cache_time')))  # half day
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
    logger.info("New query: " + match.group(0))

    await event.client(SetTypingRequest(event.input_chat, SendMessageUploadPhotoAction(0)))
    results = (await pixiv.get_pixiv_results(int(match.group(2) or 0) * MAX_GROUPED_MEDIA,  # user gives page num
                                             ranking='day_r18' if match.group(1) else 'day', ))[:MAX_GROUPED_MEDIA]
    try:
        images = await event.client(
            [UploadMediaRequest(event.input_chat, InputMediaPhotoExternal(result['url'], 86000)) for result in results]
        )
    except telethon.errors.MultiError as e:
        logging.warning("UploadMedia returned one or more errors", exc_info=True)
        images = filter(None, e.results)
        if not images:
            logging.exception("All UploadMedia requests failed")
            return

    images = [InputSingleMedia(InputMediaPhoto(InputPhoto(img.photo.id, img.photo.access_hash, b'')), '') for img in
              images]
    try:
        await event.client(SendMultiMediaRequest(event.input_chat, images))
    except (telethon.errors.UserIsBlockedError, telethon.errors.RPCError):  # TODO: add other relevant errors
        logger.exception("Failed to send multimedia")


async def main():
    await pixiv.login(config['pixiv']['username'], config['pixiv']['password'])
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

    if not os.path.exists('logs'):
        os.mkdir('logs', 0o770)
    logger = logging.getLogger(__name__)
    logger.setLevel(getattr(logging, config['main']['logging level'], logging.INFO))
    h = logging.handlers.RotatingFileHandler("logs/bot.log", encoding='utf-8', maxBytes=5 * 1024 * 1024, backupCount=5)
    logging.basicConfig(format="%(asctime)s\t%(levelname)s:%(message)s", handlers=(h,), level=logging.WARNING)

    pixiv = CustomPyxiv()

    bot = telethon.TelegramClient(config['TG API']['session'],
                                  config['TG API'].getint('api_id'), config['TG API']['api_hash'],
                                  auto_reconnect=True, connection_retries=1000)
    bot.flood_sleep_threshold = 5
    bot.add_event_handler(inline_handler)
    bot.add_event_handler(top_images)

    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
