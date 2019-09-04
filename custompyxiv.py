import datetime
import logging
from functools import wraps

import aiohttp
from pyxiv import AppPixivAPI, PixivError

logger = logging.getLogger(__file__)


def retry(f):
    @wraps(f)
    async def wrapper(*args, **kwargs):
        for _ in range(1, CustomPyxiv.MAX_RETRIES + 1):
            try:
                return await f(*args, **kwargs)
            except aiohttp.ServerConnectionError:
                pass

    return wrapper


class CustomPyxiv(AppPixivAPI):
    """
    A wrapper around Pyxiv to facilitate automatic re-authentication (for required methods) and custom result format
    """
    TOKEN_LIFESPAN = datetime.timedelta(seconds=3600)
    MAX_PIXIV_RESULTS = 300
    MAX_RETRIES = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # forces reauth() to trigger if any method is called:
        self.last_auth = datetime.datetime.fromtimestamp(0)
        self.username = ""
        self.password = ""

    async def login(self, username, password):
        self.password = password
        self.username = username
        await super().login(username, password)
        self.last_auth = datetime.datetime.now()
        logger.debug('Pyxiv login done')
        return self  # allows chaining

    @retry
    async def illust_ranking(self, mode='day', filter='for_ios', date=None, offset=None, req_auth=True):
        await self.reauth()
        return await super().illust_ranking(mode, filter, date, offset, req_auth)

    @retry
    async def search_illust(self, word, search_target='partial_match_for_tags', sort='date_desc', duration=None,
                            filter='for_ios', offset=None, req_auth=True):
        await self.reauth()
        return await super().search_illust(word, search_target, sort, duration, filter, offset, req_auth)

    @retry
    async def illust_detail(self, illust_id, req_auth=True):
        await self.reauth()
        return await super().illust_detail(illust_id, req_auth)

    async def reauth(self):
        """Re-authenticates with pixiv if the last login was more than TOKEN_LIFESPAN ago"""
        if datetime.datetime.now() - self.last_auth > self.TOKEN_LIFESPAN:
            try:
                await self.login(self.username, self.password)
            except PixivError:
                raise
            else:
                logger.debug("Reauth successful")
                self.last_auth = datetime.datetime.now()

    async def get_pixiv_results(self, offset=None, *, ranking='day', query="", nsfw=False):
        """
        Get results from Pixiv as a dict
        If no parameters are given, SFW daily ranking is returned
        :param offset: Optional. page offset
        :param ranking: Optional. Specify which ranking category to search in, one of [day, week, month, day_male, day_female, week_original, week_rookie, day_manga]
        :param query: Optional. Specify a search query
        :param nsfw: Whether to allow NSFW illustrations, false by default
        :return: list of dicts containing illustration information
        """
        await self.reauth()
        if 'r18' in ranking.lower():
            nsfw = True
        json_result, last_error = None, None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                json_result = await self.search_illust(query, 'title_and_caption', offset=offset) \
                    if query else await self.illust_ranking(ranking, offset=offset)
            except PixivError as e:
                if attempt == self.MAX_RETRIES:
                    logger.warning("Failed fetching Pixiv data")
                    raise
            else:
                break
        results = []
        for img in json_result.illusts:
            if img['type'] != 'illust' or (not nsfw and img['sanity_level'] != 2):
                # we do not want manga etc. Sanity level 2 is sfw only
                continue
            results.append({'url': img['image_urls']['large'], 'thumb_url': img['image_urls']['square_medium'],
                            'title': img['title'], 'user': img['user']['name'], 'sanity': img['sanity_level']})
            logger.debug(results[-1])
        return results
