from suggestive.lastfm import LastFM
from unittest import TestCase

from os import unlink
from os.path import isfile
import json


KEY = 'abcdefg1234567'
SESSION_FILE = 'test.session'


class TestSession(TestCase):

    def tearDown(self):
        try:
            unlink(SESSION_FILE)
        except IOError:
            pass

    def test_session(self):
        fm = LastFM(KEY, SESSION_FILE)
        fm.session_key = 'sessionkey'

        fm._save_session()
        self.assertTrue(isfile(SESSION_FILE))
        self.assertEqual('sessionkey', fm._load_session())

    def test_missing_session(self):
        fm = LastFM(KEY, SESSION_FILE)
        self.assertIsNone(fm._load_session())


class MockResponse(object):
    ok = True

    def __init__(self, text):
        self.text = text


def post_data(data):
    def mock_poster(self, *args, **kwArgs):
        return MockResponse(json.dumps(data))
    return mock_poster


class TestScrobbles(TestCase):

    def test_empty(self):
        data = {
            'recenttracks': {
                'perPage': '200',
                'user': 'thesquelched',
                'total': '0',
                'page': '0',
                '#text': '\n',
                'totalPages': '0'
            }
        }

        fm = LastFM(KEY, SESSION_FILE)
        fm._post = post_data(data)

        scrobbles = list(fm.scrobbles('myuser'))
        self.assertEqual(0, len(scrobbles))

    def test_single_page(self):
        data = {
            'recenttracks': {
                '@attr': {
                    'totalPages': '1',
                    'page': '1',
                    'total': '2',
                    'user': 'myuser',
                    'perPage': '200'
                },
                'track': [
                    {
                        'streamable': '1',
                        'artist': {
                            'name': 'artist1',
                            'mbid': 'artist1_mbid',
                            'url': 'artist1_url'
                        },
                        'url': 'url1',
                        'date': {
                            '#text': '3 Mar 2014, 21:10',
                            'uts': '1393881052'
                        },
                        'name': 'name1',
                        'mbid': 'mbid1',
                        'album': {
                            '#text': 'album_1',
                            'mbid': 'album1_mbid'
                        },
                        'loved': '1'
                    },
                    {
                        'streamable': '1',
                        'artist': {
                            'name': 'artist1',
                            'mbid': 'artist1_mbid',
                            'url': 'artist1_url'
                        },
                        'url': 'url2',
                        'date': {
                            '#text': '3 Mar 2014, 21:11',
                            'uts': '1393881053'
                        },
                        'name': 'name2',
                        'mbid': 'mbid2',
                        'album': {
                            '#text': 'album_1',
                            'mbid': 'album1_mbid'
                        },
                        'loved': '0'
                    },
                ]
            }
        }

        fm = LastFM(KEY, SESSION_FILE)
        fm._post = post_data(data)

        scrobbles = list(fm.scrobbles('myuser'))
        self.assertEqual(2, len(scrobbles))

        s1, s2 = scrobbles
        self.assertEqual('mbid1', s1['mbid'])
        self.assertEqual('url1', s1['url'])
        self.assertEqual('1', s1['streamable'])
        self.assertEqual('name1', s1['name'])
        self.assertEqual('1', s1['loved'])
        self.assertEqual('artist1', s1['artist']['name'])
        self.assertEqual('artist1_mbid', s1['artist']['mbid'])
        self.assertEqual('artist1_url', s1['artist']['url'])
