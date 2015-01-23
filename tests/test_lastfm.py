from suggestive.lastfm import LastFM, LastfmError
from requests.exceptions import RequestException
from unittest import TestCase
from unittest.mock import MagicMock

from os import unlink
from os.path import isfile
import json


KEY = 'abcdefg1234567'
SESSION_FILE = 'test.session'

CONF = MagicMock(
    lastfm_apikey=KEY,
    lastfm_session_file=SESSION_FILE,
    lastfm_secret_key=None,
    lastfm_url='http://ws.audioscrobbler.com/2.0',
    lastfm_log_responses=False,
)


class TestSession(TestCase):

    def tearDown(self):
        try:
            unlink(SESSION_FILE)
        except IOError:
            pass

    def test_session(self):
        fm = LastFM(CONF)
        fm.session_key = 'sessionkey'

        fm._save_session()
        self.assertTrue(isfile(SESSION_FILE))
        self.assertEqual('sessionkey', fm._load_session())

    def test_missing_session(self):
        fm = LastFM(CONF)
        self.assertIsNone(fm._load_session())


class MockResponse(object):
    ok = True

    def __init__(self, text):
        self.text = text


class HttpPostMock(object):

    def __init__(self, data):
        self.data = iter(data if isinstance(data, list) else [data])

    def __call__(self, *args, **kwargs):
        data = next(self.data)
        return MockResponse(json.dumps(data))


def mock_scrobble(artist='artist', url='url', name='name', mbid='mbid',
                  album='album', loved=False):
    return {
        'streamable': '1',
        'artist': {
            'name': artist,
            'mbid': artist + '_mbid',
            'url': artist + '_url'
        },
        'url': url,
        'date': {
            '#text': '3 Mar 2014, 21:10',
            'uts': '1393881052'
        },
        'name': name,
        'mbid': mbid,
        'album': {
            '#text': album,
            'mbid': album + 'mbid'
        },
        'loved': '1' if loved else '0',
    }


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

        fm = LastFM(CONF)
        fm._post = HttpPostMock(data)

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
                    mock_scrobble(url='url1', name='name1', mbid='mbid1',
                                  loved=True),
                    mock_scrobble(url='url2', name='name2', mbid='mbid2',
                                  loved=False),
                ]
            }
        }

        fm = LastFM(CONF)
        fm._post = HttpPostMock(data)

        scrobbles = list(fm.scrobbles('myuser'))
        self.assertEqual(2, len(scrobbles))

        s1, s2 = scrobbles

        self.assertEqual('mbid1', s1['mbid'])
        self.assertEqual('url1', s1['url'])
        self.assertEqual('name1', s1['name'])
        self.assertEqual('1', s1['loved'])
        self.assertEqual('artist', s1['artist']['name'])
        self.assertEqual('artist_mbid', s1['artist']['mbid'])
        self.assertEqual('artist_url', s1['artist']['url'])

        self.assertEqual('mbid2', s2['mbid'])
        self.assertEqual('url2', s2['url'])
        self.assertEqual('name2', s2['name'])
        self.assertEqual('0', s2['loved'])
        self.assertEqual('artist', s2['artist']['name'])
        self.assertEqual('artist_mbid', s2['artist']['mbid'])
        self.assertEqual('artist_url', s2['artist']['url'])

    def test_multiple_pages(self):
        data = [
            {
                'recenttracks': {
                    '@attr': {
                        'totalPages': '3',
                        'page': '1',
                        'total': '3',
                        'user': 'myuser',
                        'perPage': '2'
                    },
                    'track': [
                        mock_scrobble(url='url1', name='name1', mbid='mbid1',
                                      loved=True),
                        mock_scrobble(url='url2', name='name2', mbid='mbid2',
                                      loved=False),
                    ]
                }
            },
            {
                'recenttracks': {
                    '@attr': {
                        'totalPages': '3',
                        'page': '2',
                        'total': '3',
                        'user': 'myuser',
                        'perPage': '2'
                    },
                    'track': [
                        mock_scrobble(url='url3', name='name3', mbid='mbid3',
                                      loved=True),
                        mock_scrobble(url='url4', name='name4', mbid='mbid4',
                                      loved=False),
                    ]
                }
            },
            {
                'recenttracks': {
                    '@attr': {
                        'totalPages': '3',
                        'page': '3',
                        'total': '3',
                        'user': 'myuser',
                        'perPage': '2'
                    },
                    'track': [
                        mock_scrobble(url='url5', name='name5', mbid='mbid5',
                                      loved=True),
                        mock_scrobble(url='url6', name='name6', mbid='mbid6',
                                      loved=False),
                    ]
                }
            },
        ]

        fm = LastFM(CONF)
        fm._post = HttpPostMock(data)

        scrobbles = list(fm.scrobbles('myuser'))
        self.assertEqual(6, len(scrobbles))

        for i, s in enumerate(scrobbles, start=1):
            self.assertEqual('mbid{}'.format(i), s['mbid'])
            self.assertEqual('url{}'.format(i), s['url'])
            self.assertEqual('name{}'.format(i), s['name'])
            self.assertEqual('1' if i % 2 else '0', s['loved'])
            self.assertEqual('artist', s['artist']['name'])
            self.assertEqual('artist_mbid', s['artist']['mbid'])
            self.assertEqual('artist_url', s['artist']['url'])

    def test_query_error(self):
        fm = LastFM(CONF)
        fm._post = MagicMock(side_effect=RequestException())

        def get_scrobbles():
            return list(fm.scrobbles('myuser'))

        self.assertRaises(LastfmError, get_scrobbles)
