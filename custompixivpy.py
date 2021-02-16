import datetime
import logging
from functools import wraps

from pixivpy3 import AppPixivAPI, PixivError, PixivAPI

logger = logging.getLogger(__file__)


def retry(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        for _ in range(1, CustomPixivPy.MAX_RETRIES + 1):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                logger.exception(e)

    return wrapper


class CustomPixivPy:
    """
    A wrapper around PixivAPI and AppPixivAPI to facilitate automatic re-authentication
     (for required methods) and custom result format
    """
    TOKEN_LIFESPAN = datetime.timedelta(seconds=3600)
    MAX_PIXIV_RESULTS = 3000
    RESULTS_PER_QUERY = 50
    MAX_RETRIES = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # forces reauth() to trigger if any method is called:
        self.last_auth = datetime.datetime.fromtimestamp(0)
        self.refresh_token = ""
        self.aapi = AppPixivAPI(**kwargs)
        self.papi = PixivAPI(**kwargs)

    def login(self, refresh_token):
        self.refresh_token = refresh_token
        self.aapi.auth(refresh_token=refresh_token)
        self.papi.auth(refresh_token=refresh_token)
        self.last_auth = datetime.datetime.now()
        logger.debug('Pyxiv login done')
        return self  # allows chaining

    @retry
    def illust_ranking(self, mode='daily', offset=None):
        self.reauth()
        offset = (offset or 0) // self.RESULTS_PER_QUERY + 1
        return self.papi.ranking('illust', mode, offset, include_stats=False, image_sizes=['medium', 'large'])

    @retry
    def search_illust(self, word, search_target='text', sort='date', offset=None):
        self.reauth()
        offset = (offset or 0) // self.RESULTS_PER_QUERY + 1
        return self.papi.search_works(word, offset, mode=search_target, types=['illustration'],
                                      sort=sort, include_stats=False, image_sizes=['medium', 'large'])

    @retry
    def illust_detail(self, illust_id, req_auth=True):
        self.reauth()
        return self.aapi.illust_detail(illust_id, req_auth)

    def reauth(self):
        """Re-authenticates with pixiv if the last login was more than TOKEN_LIFESPAN ago"""
        if datetime.datetime.now() - self.last_auth > self.TOKEN_LIFESPAN:
            self.login(self.refresh_token)
            self.papi.auth(refresh_token=self.refresh_token)
            logger.debug("Reauth successful")
            self.last_auth = datetime.datetime.now()

    def get_pixiv_results(self, offset=None, *, query="", nsfw=False):
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
                json_result = self.search_illust(query, offset=offset, sort='popular') \
                    if query else self.illust_ranking('daily_r18' if nsfw else 'daily', offset=offset)
            except PixivError as e:
                if attempt == self.MAX_RETRIES:
                    logger.warning("Failed fetching Pixiv data: %s", e)
                    raise e from None
            else:
                break

        results = []
        if json_result.get('has_error'):
            return results

        it = json_result.response if query else (x['work'] for x in json_result.response[0]['works'])
        for img in it:
            if not nsfw and img['sanity_level'] == 'black':
                continue  # white = SFW, semi_black = questionable, black = NSFW
            results.append({
                'url': img['image_urls']['large'],
                'thumb_url': img['image_urls']['medium'], 'title': img['title'],
                'user_name': img['user']['name'], 'user_link': f"https://www.pixiv.net/en/users/{img['user']['id']}"})
            logger.debug(results[-1])
        return results
