import re
from types import SimpleNamespace
import datetime

import pytest
from mockito import mock, expect

from custompixivpy import CustomPixivPy


def make_illust(id_, sanity):
    return {'id': id_, 'type': 'illust', 'sanity_level': sanity, 'image_urls': {'large': f'https://i.example/{id_}.jpg', 'medium': f'https://i.example/{id_}_m.jpg'}, 'title': f'Title {id_}', 'user': {'name': f'User{id_}', 'id': id_}}


def test_get_pixiv_results_accumulates_and_preserves_offsets():
    api = CustomPixivPy()
    # Use small page size for testing
    api.RESULTS_PER_QUERY = 3

    # Page 1: server items [SFW, NSFW, SFW]
    page1 = {
        'illusts': [make_illust(1, 0), make_illust(2, 6), make_illust(3, 0)],
        'next_url': 'https://pixiv.net/?offset=3'
    }
    # Page 2: server items [SFW, SFW]
    page2 = {
        'illusts': [make_illust(4, 0), make_illust(5, 0)],
        'next_url': 'https://pixiv.net/?offset=5'
    }

    with expect(api, times=1).illust_ranking('day', 0).thenReturn(page1):
        with expect(api, times=1).illust_ranking('day', 3).thenReturn(page2):
            visible, next_offset = api.get_pixiv_results(0, query="", nsfw=False)

            # We requested 3 visible items; ensure we got 3 SFW items
            assert len(visible) == 3
            # Items returned should be ids 1,3,4 in that order
            assert [v['id'] for v in visible] == [1, 3, 4]
            # With flattened cache, next_offset is the client logical index: returned 3 items => next_offset = 3
            assert next_offset == 3


def test_login_sets_refresh_token():
    cp = CustomPixivPy()

    # Replace aapi and papi with mockito mocks
    aapi = mock()
    papi = mock()
    cp.aapi = aapi
    cp.papi = papi

    before = datetime.datetime.now()
    # Expect both auth methods to be called with the token
    with expect(aapi, times=1).auth(refresh_token='my-refresh-token').thenReturn(None):
        with expect(papi, times=1).auth(refresh_token='my-refresh-token').thenReturn(None):
            res = cp.login('my-refresh-token')
    after = datetime.datetime.now()

    assert res is cp
    assert cp.refresh_token == 'my-refresh-token'

    # last_auth should be set to a recent timestamp
    assert before <= cp.last_auth <= after

def test_get_pixiv_results_filters_sfw():
    cp = CustomPixivPy()
    # Make tests deterministic and small
    cp.RESULTS_PER_QUERY = 2

    # Prepare a single server page with three server items: two SFW, one NSFW
    server_page = {
        "illusts": [
            {
                "id": 1,
                "type": "illust",
                "image_urls": {"large": "http://pixiv/1_large.jpg", "medium": "http://pixiv/1_med.jpg"},
                "title": "Art 1",
                "user": {"name": "Alice", "id": 101},
                "sanity_level": "1",
            },
            {
                "id": 2,
                "type": "illust",
                "image_urls": {"large": "http://pixiv/2_large.jpg", "medium": "http://pixiv/2_med.jpg"},
                "title": "Art 2",
                "user": {"name": "Bob", "id": 102},
                "sanity_level": "0",
            },
            {
                "id": 3,
                "type": "illust",
                "image_urls": {"large": "http://pixiv/3_large.jpg", "medium": "http://pixiv/3_med.jpg"},
                "title": "Art 3",
                "user": {"name": "Eve", "id": 103},
                "sanity_level": "6",
            },
        ],
        "next_url": "https://api.pixiv.net/?offset=3",
    }

    with expect(cp, times=1).illust_ranking('day', 0).thenReturn(server_page):
        results, next_offset = cp.get_pixiv_results(0, nsfw=False)

        # Should return only the two SFW items and stop when RESULTS_PER_QUERY reached
        assert len(results) == 2
        assert results[0]["id"] == 1
        assert results[1]["id"] == 2

        # consumed should be 2 (two server items processed until limit reached)
        assert next_offset == 2

        # Ensure the ranking mode used for SFW is 'day' (expect verifies this)
        pass

def test_get_pixiv_results_with_query_and_nsfw_true():
    cp = CustomPixivPy()
    cp.RESULTS_PER_QUERY = 1

    # Prepare server page with a single NSFW item
    server_page = {
        "illusts": [
            {
                "id": 11,
                "type": "illust",
                "image_urls": {"large": "http://pixiv/11_large.jpg", "medium": "http://pixiv/11_med.jpg"},
                "title": "NSFW Art",
                "user": {"name": "Zoe", "id": 201},
                "sanity_level": "6",
            },
        ],
        "next_url": "https://api.pixiv.net/?offset=1",
    }

    with expect(cp, times=1).search_illust('cats', offset=0).thenReturn(server_page):
        results, next_offset = cp.get_pixiv_results(0, query="cats", nsfw=True)

        assert len(results) == 1
        assert results[0]['id'] == 11
        assert results[0]['user_name'] == 'Zoe'
        assert next_offset == 1

        # expect verifies the call
        pass


def test_illust_detail_delegates_to_aapi():
    cp = CustomPixivPy()

    expected = {"illust": {"id": 42, "title": "Meaning of Life", "user": {"id": 9, "name": "Deep"}}}

    # Use mockito to stub aapi.illust_detail and cp.reauth
    aapi = mock()
    cp.aapi = aapi
    with expect(cp, times=1).reauth().thenReturn(None):
        with expect(aapi, times=1).illust_detail(42, True).thenReturn(expected):
            res = cp.illust_detail(42)
            assert res == expected


def test_pagination_no_duplicates_from_fixture():
    """Use the generated fixtures to ensure paginated queries don't return duplicates."""
    import json
    cp = CustomPixivPy()
    # Keep RESULTS_PER_QUERY at a reasonable size to exercise filtering
    cp.RESULTS_PER_QUERY = 20

    with open('tests/fixtures/ranking_pages.json', 'r', encoding='utf-8') as f:
        pages = json.load(f)

    per_page = 50

    # Monkeypatch illust_ranking to return pages sequentially on each call (simulate server pagination)
    call_index = {'i': 0}
    def illust_ranking(mode, offset=0):
        i = call_index['i']
        call_index['i'] += 1
        if i < len(pages):
            return pages[i]
        return {'illusts': [], 'next_url': None}

    cp.illust_ranking = illust_ranking

    seen = set()
    offset = 0
    # Iterate up to number of pages; each get_pixiv_results will consume as many pages as needed
    for _ in range(len(pages)):
        results, next_offset = cp.get_pixiv_results(offset, nsfw=False)
        ids = [r['id'] for r in results]
        # No duplicates within page
        assert len(ids) == len(set(ids)), f"Duplicates in results: {ids}"
        # No duplicates across pages
        assert seen.isdisjoint(ids), f"Duplicates across pages: {set(ids).intersection(seen)}"
        seen.update(ids)
        if not next_offset:
            break
        offset = next_offset



def test_server_duplicate_ids_across_server_pages():
    """If the server returns the same illust in consecutive pages, ensure paginated calls using next_offset do not yield duplicates."""
    cp = CustomPixivPy()
    cp.RESULTS_PER_QUERY = 2

    # Page 1: [1,2]
    p1 = {'illusts': [make_illust(1, 0), make_illust(2, 0)], 'next_url': 'https://pixiv.net/?offset=2'}
    # Page 2: [2,3] - note id 2 is duplicated across server pages
    p2 = {'illusts': [make_illust(2, 0), make_illust(3, 0)], 'next_url': 'https://pixiv.net/?offset=4'}
    call_index = {'i': 0}
    pages = [p1, p2]

    def illust_ranking(mode, offset=0):
        i = call_index['i']
        call_index['i'] += 1
        if i < len(pages):
            return pages[i]
        return {'illusts': [], 'next_url': None}

    cp.illust_ranking = illust_ranking

    seen = set()
    offset = 0
    for _ in range(3):
        results, next_offset = cp.get_pixiv_results(offset, nsfw=False)
        ids = [r['id'] for r in results]
        # No duplicates within page
        assert len(ids) == len(set(ids))
        # No duplicates across pages
        assert seen.isdisjoint(ids), f"Found duplicate across pages: {set(ids).intersection(seen)}"
        seen.update(ids)
        if not next_offset:
            break
        offset = next_offset


def test_cache_respects_results_per_query():
    """Ensure the in-memory cache key includes RESULTS_PER_QUERY so different page sizes don't return stale cached sizes."""
    cp = CustomPixivPy()

    # Single server page with 3 items
    server_page = {'illusts': [make_illust(1, 0), make_illust(2, 0), make_illust(3, 0)], 'next_url': 'https://pixiv.net/?offset=3'}
    call_index = {'i': 0}
    def illust_ranking(mode, offset=0):
        # Always return server_page for offset==0 so repeated calls behave the same
        if offset == 0:
            return server_page
        return {'illusts': [], 'next_url': None}
    cp.illust_ranking = illust_ranking

    # First call with RESULTS_PER_QUERY = 1
    cp.RESULTS_PER_QUERY = 1
    r1, no1 = cp.get_pixiv_results(0, nsfw=False)
    assert len(r1) == 1

    # Second call with RESULTS_PER_QUERY = 2 should return 2 items from the flattened cache
    cp.RESULTS_PER_QUERY = 2
    r2, no2 = cp.get_pixiv_results(0, nsfw=False)
    assert len(r2) == 2
