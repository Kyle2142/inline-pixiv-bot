import datetime
import logging
from functools import wraps

import aiohttp
from pixivpy_async import AppPixivAPI, PixivError, PixivAPI

logger = logging.getLogger(__file__)


def retry(f):
    @wraps(f)
    async def wrapper(*args, **kwargs):
        for _ in range(1, CustomPixivPy.MAX_RETRIES + 1):
            try:
                return await f(*args, **kwargs)
            except aiohttp.ServerConnectionError:
                pass

    return wrapper


class CustomPixivPy:
    """
    A wrapper around PixivAPI and AppPixivAPI to facilitate automatic re-authentication (for required methods) and custom result format
    """
    TOKEN_LIFESPAN = datetime.timedelta(seconds=3600)
    MAX_PIXIV_RESULTS = 3000
    RESULTS_PER_QUERY = 50
    MAX_RETRIES = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # forces reauth() to trigger if any method is called:
        self.last_auth = datetime.datetime.fromtimestamp(0)
        self.username = ""
        self.password = ""

        self.aapi = AppPixivAPI(env=True)
        self.papi = PixivAPI(env=True)

    async def login(self, username, password):
        self.password = password
        self.username = username
        await self.aapi.login(username, password)
        await self.papi.login(username, password)
        self.last_auth = datetime.datetime.now()
        logger.debug('Pyxiv login done')
        return self  # allows chaining

    @retry
    async def illust_ranking(self, mode='day', offset=None):
        await self.reauth()
        json_result = await self.aapi.illust_ranking(mode=mode)
        # print(json_result)
        offset = (offset or 0) // self.RESULTS_PER_QUERY + 1
        print("offset-1", offset-1)
        for a in range(offset-1):
            next_qs = self.aapi.parse_qs(json_result.next_url)
            json_result = await self.aapi.illust_ranking(**next_qs)
        
        # notice that not good to use
        return json_result

    @retry
    async def search_illust(self, word=None, search_target='text', sort='date_desc', offset=None):
        await self.reauth()
        offset = (offset or 0) // self.RESULTS_PER_QUERY + 1
        response = await self.aapi.trending_tags_illust()
        for trend_tag in response.trend_tags[:10]:
            if not word:
                word = trend_tag.tag
                print("%s -  %s(id=%s)" % (trend_tag.tag, trend_tag.illust.title, trend_tag.illust.id))
            
            
        return await self.aapi.search_illust(word, search_target='partial_match_for_tags',sort=sort,offset=offset)

        # return await self.papi.search_works(word, offset, mode=search_target, types=['illustration'],
        #                                     sort=sort, include_stats=False, image_sizes=['medium', 'large'])

    @retry
    async def illust_detail(self, illust_id, req_auth=True):
        await self.reauth()
        return await self.aapi.illust_detail(illust_id, req_auth)

    async def reauth(self):
        """Re-authenticates with pixiv if the last login was more than TOKEN_LIFESPAN ago"""
        if datetime.datetime.now() - self.last_auth > self.TOKEN_LIFESPAN:
            await self.login(self.username, self.password)
            await self.papi.login(self.username, self.password)
            logger.debug("Reauth successful")
            self.last_auth = datetime.datetime.now()

    async def get_pixiv_results(self, offset=None, *, query="", nsfw=False):
        """
        Get results from Pixiv as a dict
        If no parameters are given, SFW daily ranking is returned
        :param offset: Optional. page offset
        :param query: Optional. Specify a search query
        :param nsfw: Whether to allow NSFW illustrations, false by default
        :return: list of dicts containing illustration information
        """
        json_result, last_error = None, None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                json_result = await self.search_illust(query, offset=offset, sort='popular') \
                    if query else await self.illust_ranking('day_r18' if nsfw else 'day', offset=offset)
            except PixivError as e:
                if attempt == self.MAX_RETRIES:
                    logger.warning("Failed fetching Pixiv data: %s", e)
                    raise e from None
            else:
                break

        results = []
        if json_result.get('has_error'):
            return results
        print("get the query : ", query)
        # it = (x for x in json_result.illusts)
        for img in json_result.illusts:
            if not nsfw and img['sanity_level'] > 2:
                continue  # white = SFW, semi_black = questionable, black = NSFW
            results.append({
                'url': img['image_urls']['large'],
                'thumb_url': img['image_urls']['medium'],
                'title': img['title'],
                'user_name': img['user']['name'],
                'user_link': f"https://www.pixiv.net/en/users/{img['user']['id']}"})
            # print(img['image_urls']['large'])
            logger.debug(results[-1])
        results.append({
                'url': 'https://xcx.zhenghaodichan.com:9000/test/9.jpg',
                'thumb_url': 'https://xcx.zhenghaodichan.com:9000/test/9.jpg',
                'title': 'https://xcx.zhenghaodichan.com:9000/test/9.jpg',
                'user_name': 'https://xcx.zhenghaodichan.com:9000/test/9.jpg',
                'user_link': f"https://www.pixiv.net/en/users/{img['user']['id']}"})
        print(results)
        return results
