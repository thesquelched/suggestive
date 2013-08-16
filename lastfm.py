import requests
import json
import logging
from collections import defaultdict
from time import mktime

APIKEY = 'd9d0efb24aec53426d0f8d144c74caa7'

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class LastfmError(Exception):
    pass


def get(data, keys, default=None):
    if not keys:
        return data

    if not isinstance(data, dict):
        raise TypeError('not a dictionary')

    key, rest = keys[0], keys[1:]
    if key not in data:
        return default

    return get(data[key], rest, default=default)


def retry(attempts=2):
    def retry_dec(func):
        def wrapper(self, *args, **kwArgs):
            last_error = ValueError('No attempts made')
            for attempt in range(attempts):
                try:
                    return func(self, *args, **kwArgs)
                except LastfmError as error:
                    last_error = error

            raise last_error
        return wrapper
    return retry_dec


class LastFM(object):

    """
    Helper class for communicating with Last.FM servers
    """

    URL = 'http://ws.audioscrobbler.com/2.0/'

    def __init__(self, api_key):
        self.key = api_key

    def query_all(self, method, *keys, **kwArgs):
        resp = self.query(method, **kwArgs)

        data = resp
        for key in keys:
            if key in data:
                data = data[key]
            else:
                break

        attrs = data.get('@attr', {})
        n_pages = int(attrs.get('totalPages', 1))

        logger.debug('Query pages: {}'.format(n_pages))

        # Start to yield responses
        yield resp

        for pageno in range(1, n_pages):
            kwArgs.update({'page': pageno})
            yield self.query(method, **kwArgs)

    @retry()
    def query(self, method, **kwArgs):
        """
        Send a Last.FM query for the given method, returing the parsed JSON
        response
        """
        params = dict(
            method=method,
            api_key=self.key,
            format='json',
        )
        params.update(kwArgs)

        try:
            resp = requests.post(self.URL, params=params)
            if not resp.ok:
                raise ValueError('Response was invalid')
            return json.loads(resp.text)
        except (ValueError, requests.exceptions.RequestException) as error:
            logger.error('Query resulted in an error: {}', error)
            raise LastfmError("Query '{}' failed".format(method))

    def scrobbles(self, user, start=None, end=None):
        for batch in self.scrobble_batches(user, start=start, end=end):
            for scrobble in batch:
                yield scrobble

    def scrobble_batches(self, user, start=None, end=None):
        args = {
            'limit': 200,
            'user': user,
            'extended': 1
        }

        if start:
            args['from'] = int(mktime(start.timetuple()))
        if end:
            args['to'] = int(mktime(end.timetuple()))

        for resp in self.query_all('user.getRecentTracks', 'recenttracks',
                                   **args):
            if 'recenttracks' not in resp:
                continue

            recent = resp['recenttracks']
            if 'track' not in recent or not isinstance(recent['track'], list):
                continue

            yield recent['track']

    def loved_tracks(self, user):
        for resp in self.query_all('user.getLovedTracks', 'lovedtracks',
                                   user=user):
            if 'lovedtracks' not in resp:
                continue

            loved = resp['lovedtracks']
            if 'track' not in loved or not isinstance(loved['track'], list):
                continue

            for track in loved['track']:
                yield track

    def banned_tracks(self, user):
        for resp in self.query_all('user.getBannedTracks', 'bannedtracks',
                                   user=user):
            if 'bannedtracks' not in resp:
                continue

            banned = resp['bannedtracks']
            if 'track' not in banned or not isinstance(banned['track'], list):
                continue

            for track in banned['track']:
                yield track

    def artist_correction(self, artist):
        resp = self.query('artist.getCorrection', artist=artist)

        if 'error' in resp or 'corrections' not in resp:
            return None

        corrections = resp['corrections']

        if not isinstance(corrections, dict):
            return None

        return get(corrections, ['correction', 'artist', 'name'])

    def album_corrections(self, album, artist):
        resp = self.query('album.search', album=album)

        try:
            albums = get(resp, ['results', 'albummatches', 'album'])
        except TypeError:
            return []

        if not isinstance(albums, list):
            return []

        albums_by_artist = defaultdict(list)
        for item in albums:
            if isinstance(item, dict):
                albums_by_artist[item['artist']].append(item['name'])

        if artist.name in albums_by_artist:
            return albums_by_artist[artist.name]
        elif artist.correction:
            return albums_by_artist[artist.correction.name]
        else:
            return []
