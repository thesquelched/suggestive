import requests
import json
import logging
from collections import defaultdict
from time import mktime
from hashlib import md5

APIKEY = 'd9d0efb24aec53426d0f8d144c74caa7'

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class LastfmError(Exception):
    pass


class AuthenticationError(LastfmError):
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
    _NO_SIGN = set(['format', 'api_sig'])

    def __init__(self, api_key, session_file, api_secret=None):
        self.key = api_key
        self.secret = api_secret
        self.session_file = session_file
        self.session_key = None
        self.token = None

        if api_secret is not None:
            self.session_key = self.load_session()
            if self.session_key is None:
                self.token = self.get_token()
                self.get_user_permission()
                self.session_key = self.get_session_key()
                self.save_session()

    def get_user_permission(self):
        message = """\
No LastFM session found; to authorize suggestive, visit this URL and click
'Yes, allow access', then return to this window:

    http://www.last.fm/api/auth/?api_key={}&token={}

Press Enter to continue...""".format(self.key, self.token)
        input(message)

    def load_session(self):
        try:
            with open(self.session_file) as handle:
                return handle.read().strip()
        except IOError:
            logger.warn('Could not LastFM session key from file')
            return None

    def save_session(self):
        logger.info('Saving session key to file')
        if self.session_key is None:
            raise IOError("Can't save session key; no session_key found")
        with open(self.session_file, 'w') as handle:
            handle.write(self.session_key)

    def get_session_key(self):
        logger.info('Acquiring new LastFM session')

        resp = self.query('auth.getSession', token=self.token, sign=True)
        if 'error' in resp:
            raise AuthenticationError(resp.get('message', 'Unknown Error'))

        return resp['session']['key']

    def get_token(self):
        logger.info('Acquiring new LastFM API token')
        resp = self.query('auth.getToken', sign=True)
        return resp['token']

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

    def sign(self, **params):
        if self.session_key is not None:
            params.update(sk=self.session_key)

        key_str = ''.join('{}{}'.format(key, params[key])
                          for key in sorted(params)
                          if key not in self._NO_SIGN)
        with_secret = '{}{}'.format(key_str, self.secret)
        return md5(with_secret.encode('UTF-8')).hexdigest()

    def query_params(self, method, sign=False, format='json', **kwArgs):
        params = dict(
            method=method,
            api_key=self.key,
        )
        if format is not None:
            params.update(format=format)
        params.update(kwArgs)

        if sign:
            params.update(api_sig=self.sign(**params), sk=self.session_key)

        return params

    @retry()
    def query(self, method, sign=False, **kwArgs):
        """
        Send a Last.FM query for the given method, returing the parsed JSON
        response
        """
        params = self.query_params(method, sign=sign, **kwArgs)

        try:
            resp = requests.post(self.URL, params=params)
            if not resp.ok:
                logger.debug(resp.content)
                raise ValueError('Response was invalid')
            return json.loads(resp.text)
        except (ValueError, requests.exceptions.RequestException) as error:
            logger.error('Query resulted in an error: {}'.format(error))
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

    def love_track(self, artist, track):
        resp = self.query('track.love', artist=artist, track=track, sign=True)
        if resp.get('status') == 'ok':
            return True
        else:
            logger.error('Unable to love track: {}'.format(
                resp.get('message', 'Unknown Error')))
            return False

    def unlove_track(self, artist, track):
        resp = self.query('track.unlove', artist=artist, track=track,
                          sign=True)
        if resp.get('status') == 'ok':
            return True
        else:
            logger.error('Unable to unlove track: {}'.format(
                resp.get('message', 'Unknown Error')))
            return False
