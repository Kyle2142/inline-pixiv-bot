import datetime
import logging
import re
from functools import wraps
import threading
import time
from collections import OrderedDict

class SimpleTTLCache:
    def __init__(self, maxsize=50, ttl=600):
        self.maxsize = maxsize
        self.ttl = ttl
        self.data = OrderedDict()

    def get(self, key):
        now = time.time()
        if key in self.data:
            value, ts = self.data[key]
            if now - ts < self.ttl:
                # mark as recently used
                self.data.move_to_end(key)
                return value
            else:
                # expired
                del self.data[key]
        return None

    def __setitem__(self, key, value):
        now = time.time()
        if key in self.data:
            del self.data[key]
        self.data[key] = (value, now)
        # evict oldest if over capacity
        while len(self.data) > self.maxsize:
            self.data.popitem(last=False)

    def clear(self):
        self.data.clear()

try:
    from pixivpy3 import AppPixivAPI, PixivError, PixivAPI
except Exception:
    from pixivpy3 import AppPixivAPI, PixivError
    PixivAPI = None

logger = logging.getLogger(__name__)


def retry(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(1, CustomPixivPy.MAX_RETRIES + 1):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                last_exc = e
                logger.warning("Attempt %d/%d failed for %s: %s", attempt, CustomPixivPy.MAX_RETRIES, f.__name__, e, exc_info=True)
                if attempt < CustomPixivPy.MAX_RETRIES:
                    time.sleep(min(2 ** (attempt - 1), 8))
        # re-raise the last exception so callers can handle it
        raise last_exc
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
    # How long (seconds) an ID remains in the global seen set before it may be shown again
    GLOBAL_SEEN_TTL = 600

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # forces reauth() to trigger if any method is called:
        self.last_auth = datetime.datetime.fromtimestamp(0)
        self.refresh_token = ""
        self.aapi = AppPixivAPI(**kwargs)
        self.papi = PixivAPI(**kwargs) if PixivAPI is not None else None
        # in-memory cache for fetched pages: LRU with TTL
        # maxsize=50 entries, ttl=600 seconds (10 minutes)
        self.page_cache = SimpleTTLCache(maxsize=50, ttl=600)
        self._cache_lock = threading.Lock()
        # Flattened cache: per (query, nsfw) store flattened visible item list and timestamp
        # Format: key -> {'items': [...], 'ts': float, 'exhausted': bool, 'next_server_offset': int}
        self.flattened_cache = {}
        # Locks to serialize building per (query, nsfw) key
        self._flatten_locks = {}


    def login(self, refresh_token):
        self.refresh_token = refresh_token
        self.aapi.auth(refresh_token=refresh_token)
        if self.papi:
            try:
                self.papi.auth(refresh_token=refresh_token)
            except Exception:
                logger.debug("PixivAPI not available or auth failed; continuing with AppPixivAPI")
        self.last_auth = datetime.datetime.now()
        # Clear cached pages after login/refresh to avoid stale data
        try:
            with self._cache_lock:
                self.page_cache.clear()
                # clear flattened cache on login to avoid leaking state between sessions
                self.flattened_cache.clear()
        except Exception as e:
            logger.debug("Clearing caches after login failed: %s", e, exc_info=True)
        logger.debug('Pyxiv login done')
        return self  # allows chaining

    @retry
    def illust_ranking(self, mode='day', offset=0):
        self.reauth()
        return self.aapi.illust_ranking(mode, offset=offset)

    @retry
    def search_illust(self, word, search_target='partial_match_for_tags', sort='popular_desc', offset=None, **kwargs):
        self.reauth()
        return self.aapi.search_illust(word, search_target=search_target, sort=sort, offset=offset, **kwargs)

    @retry
    def illust_detail(self, illust_id, req_auth=True, **kwargs):
        self.reauth()
        return self.aapi.illust_detail(illust_id, req_auth, **kwargs)

    def reauth(self):
        """Re-authenticates with pixiv if the last login was more than TOKEN_LIFESPAN ago"""
        if not self.refresh_token:
            logger.debug("No refresh_token provided; skipping reauth")
            return
        if datetime.datetime.now() - self.last_auth > self.TOKEN_LIFESPAN:
            try:
                self.login(self.refresh_token)
                if self.papi:
                    try:
                        self.papi.auth(refresh_token=self.refresh_token)
                    except Exception as e:
                        logger.debug("PixivAPI auth during reauth failed or unavailable; continuing", exc_info=True)
                logger.debug("Reauth successful")
                self.last_auth = datetime.datetime.now()
            except Exception as e:
                logger.warning("Reauth failed: %s", e, exc_info=True)

    def _build_flattened(self, fkey, existing_items, required, start_server_offset=0, start_next_server_offset=None):
        """Extend the flattened list for fkey until it has at least `required` items or server is exhausted.
        Returns (items, exhausted, next_server_offset).
        """
        query, nsfw = fkey
        items = list(existing_items)
        seen_ids = set(v['id'] for v in items if isinstance(v, dict) and v.get('id') is not None)
        # start from provided next_server_offset if available, otherwise start_server_offset
        server_offset = start_next_server_offset if start_next_server_offset is not None else start_server_offset
        consumed = 0
        pages_fetched = 0
        seen_server_offsets = set()
        exhausted = False
        MAX_PAGES_PER_CALL = 20

        while len(items) < required and pages_fetched < MAX_PAGES_PER_CALL:
            # Fetch server page
            json_result = None
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    json_result = self.search_illust(query, offset=server_offset) if query else \
                        self.illust_ranking('day_r18' if nsfw else 'day', server_offset)
                except PixivError as e:
                    if attempt == self.MAX_RETRIES:
                        logger.warning("Failed fetching Pixiv data: %s", e)
                        raise e from None
                else:
                    break

            if not json_result:
                exhausted = True
                break

            # Normalize
            if not hasattr(json_result, 'get'):
                try:
                    json_result = dict(json_result)
                except Exception:
                    try:
                        json_result = json_result.json()
                    except Exception as e:
                        logger.warning("Unexpected Pixiv API response type at offset %s: %s", server_offset, e, exc_info=True)
                        exhausted = True
                        break
            if json_result.get('has_error'):
                logger.warning("Pixiv API returned error at offset %s", server_offset)
                exhausted = True
                break

            if server_offset in seen_server_offsets:
                logger.warning("Server offset %s was seen before; stopping to avoid loop", server_offset)
                exhausted = True
                break
            seen_server_offsets.add(server_offset)
            pages_fetched += 1

            illusts = json_result.get('illusts', [])
            logger.debug("Fetched server page offset=%s: %d server items, pages_fetched=%d", server_offset, len(illusts), pages_fetched)
            if not illusts:
                exhausted = True
                logger.debug("No illusts found on server page offset=%s; marking exhausted", server_offset)
                break

            added_this_page = 0
            skipped_this_page = 0
            for img in illusts:
                consumed += 1
                # Only handle 'illust' items; skip other types (server may return manga etc.)
                img_type = img.get('type')
                if img_type is None or str(img_type) != 'illust':
                    skipped_this_page += 1
                    continue
                # NSFW
                sanity = img.get('sanity_level', 0)
                try:
                    is_nsfw = int(sanity) == 6
                except Exception:
                    is_nsfw = False
                if is_nsfw != bool(nsfw):
                    skipped_this_page += 1
                    continue
                iid = img.get('id')
                if iid in seen_ids:
                    skipped_this_page += 1
                    continue
                seen_ids.add(iid)
                items.append({
                    'id': iid,
                    'url': img.get('image_urls', {}).get('large'),
                    'thumb_url': img.get('image_urls', {}).get('medium'),
                    'title': img.get('title'),
                    'user_name': img.get('user', {}).get('name'),
                    'user_id': img.get('user', {}).get('id'),
                    'w': img.get('width'), 'h': img.get('height')
                })
                added_this_page += 1
                if len(items) >= required:
                    break
            logger.debug("Processed server page offset=%s: added=%d skipped=%d total_items=%d", server_offset, added_this_page, skipped_this_page, len(items))
            # After processing entire page, if we've reached required count, stop fetching more pages
            if len(items) >= required:
                break

            # next_url handling
            next_url = json_result.get('next_url')
            if not next_url:
                exhausted = True
                break
            next_match = re.match(r'.+offset=(\d+)', next_url)
            if next_match:
                next_server_offset = int(next_match.group(1))
                if next_server_offset in seen_server_offsets:
                    logger.warning("Next server offset %s already seen; stopping to avoid loop", next_server_offset)
                    exhausted = True
                    break
                server_offset = next_server_offset
            else:
                server_offset = server_offset + consumed
                break

            # Safety cap for MAX_PIXIV_RESULTS
            if consumed and consumed >= self.MAX_PIXIV_RESULTS:
                exhausted = True
                break

        return items, exhausted, (server_offset if not exhausted else None)

    def _expire_global_seen(self, key=None):
        """Expire old entries in the global seen maps.
        If key is None, expire entries for all keys; otherwise expire only for the given key.
        """
        # No-op in flattened mode; retained for compatibility
        return

    def get_pixiv_results(self, offset=0, *, query="", nsfw=False):
        """Return client-logical paginated results using a flattened in-memory cache."""
        # Normalize query to empty string when falsy so we treat None and '' the same
        fkey = (query or "", bool(nsfw))
        try:
            with self._cache_lock:
                entry = self.flattened_cache.get(fkey)
                if entry and time.time() - entry['ts'] < self.page_cache.ttl:
                    items = entry['items']
                    exhausted = entry.get('exhausted', False)
                    next_server_offset = entry.get('next_server_offset')
                    logger.debug("Flattened cache hit for key=%s: items=%d exhausted=%s", fkey, len(items), exhausted)
                else:
                    items = []
                    exhausted = False
                    next_server_offset = None
        except Exception:
            items = []
            exhausted = False
            next_server_offset = None

        required = int(offset) + int(self.RESULTS_PER_QUERY)
        if len(items) < required and not exhausted:
            # Acquire a per-key build lock to avoid concurrent builders causing duplicates
            lock = None
            try:
                with self._cache_lock:
                    lock = self._flatten_locks.get(fkey)
                    if lock is None:
                        lock = threading.Lock()
                        self._flatten_locks[fkey] = lock
                acquired = False
                try:
                    acquired = lock.acquire(timeout=10)
                except Exception:
                    acquired = False
                if not acquired:
                    logger.warning("Could not acquire build lock for key=%s; proceeding without extension", fkey)
                else:
                    # Re-check cache after acquiring lock; another builder may have updated it
                    with self._cache_lock:
                        entry = self.flattened_cache.get(fkey)
                        if entry and time.time() - entry['ts'] < self.page_cache.ttl:
                            items = entry['items']
                            exhausted = entry.get('exhausted', False)
                            next_server_offset = entry.get('next_server_offset')
                    if len(items) < required and not exhausted:
                        try:
                            logger.debug("Extending flattened cache for key=%s from %d to required=%d (next_server_offset=%s)", fkey, len(items), required, next_server_offset)
                            # build on a copy to avoid mutating shared list concurrently
                            new_items, exhausted, next_server_offset = self._build_flattened(fkey, list(items), required, start_next_server_offset=next_server_offset or 0)
                            with self._cache_lock:
                                self.flattened_cache[fkey] = {'items': new_items, 'ts': time.time(), 'exhausted': exhausted, 'next_server_offset': next_server_offset}
                                items = new_items
                            logger.debug("Flattened cache now has %d items (exhausted=%s) next_server_offset=%s", len(items), exhausted, next_server_offset)
                        except Exception:
                            logger.exception("Failed to build flattened pixiv results")
            finally:
                try:
                    if lock is not None and acquired:
                        lock.release()
                except Exception as e:
                    logger.debug("Failed releasing build lock for key=%s: %s", fkey, e, exc_info=True)

        slice_items = items[int(offset):int(offset) + int(self.RESULTS_PER_QUERY)]
        if not slice_items:
            logger.debug("Returning empty slice for offset=%s (available_items=%d)", offset, len(items))
            return [], None
        next_offset = int(offset) + len(slice_items)
        # If exhausted and we've reached the end, return None
        if exhausted and next_offset >= len(items):
            next_offset = None
        logger.debug("Returning items for offset=%s count=%d ids=%s next_offset=%s", offset, len(slice_items), [s.get('id') for s in slice_items], next_offset)
        return slice_items, next_offset
