from suggestive.util import retry_function, retry
from suggestive.error import RetryError

import logging
import webbrowser
import pylastfm


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def get(data, keys, default=None):
    if not keys:
        return data

    if not isinstance(data, dict):
        raise TypeError('not a dictionary')

    key, rest = keys[0], keys[1:]
    if key not in data:
        return default

    return get(data[key], rest, default=default)


class LastFM(object):

    """
    Helper class for communicating with Last.FM servers
    """

    def __init__(self, config):
        self.config = config
        self.client = self._initialize_client()

    def _get_user_permission(self, token):
        """Attempt to open up authorization URL in browser.  If this fails, simply
        display a message in the console asking user to manually open URL"""

        url = 'http://www.last.fm/api/auth/?api_key={0}&token={1}'.format(
            self.config.lastfm_apikey, token)

        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass

        message = """\
    No LastFM session found; to authorize suggestive, visit this URL and click
    'Yes, allow access', then return to this window:

    {url}

    Press Enter to continue...""".format(url=url)

        input(message)

    def _save_session(self, session_key):
        """Save session key (in plaintext) to a file"""
        logger.info('Saving session key to file')
        with open(self.config.lastfm_session_file, 'w') as handle:
            handle.write(session_key)

    def _authorize_application(self, client):
        """Go through the LastFM desktop application authorization process, saving
        a session key to a file for future use"""
        token = retry_function(client.auth.get_token)
        self._get_user_permission(token)

        try:
            session_key = retry_function(client.auth.get_session, token)
        except pylastfm.AuthenticationError as exc:
            logger.debug('Unable to get authenticated LastFM session',
                         exc_info=exc)
            raise

        self._save_session(session_key)

    @retry(exceptions=RetryError)
    def _initialize_client(self):
        config = self.config

        client = pylastfm.LastFM(config.lastfm_apikey,
                                 config.lastfm_secret_key,
                                 username=config.lastfm_user,
                                 url=config.lastfm_url,
                                 auth_method='session_key_file',
                                 session_key=config.lastfm_session_file)

        try:
            client.authenticate()
            return client
        except pylastfm.FileError:
            logger.info('Authenticating suggestive with LastFM')
            self._authorize_application(client)
            raise RetryError
        except pylastfm.AuthenticationError as exc:
            logger.debug('Failed to authenticate', exc_info=exc)
            raise
        except pylastfm.LastfmError as exc:
            logger.error(
                'Unable to authenticate to LastFM due to unknown error',
                exc_info=exc)
            raise

    def scrobbles(self, user, start=None, end=None):
        """Get user scrobbles in the given date range"""
        return self.client.user.get_recent_tracks(user, start=start, end=end)

    def loved_tracks(self, user):
        """Get all of the user's loved tracks"""
        return self.client.user.get_loved_tracks(user)

    def banned_tracks(self, user):
        """Get all of the user's banned tracks"""
        return self.client.user.get_banned_tracks(user)

    def love_track(self, artist, track):
        """Mark the given track loved"""
        try:
            self.client.track.love(artist, track)
            return True
        except pylastfm.ApiError as exc:
            logger.error('Unable to love track', exc_info=exc)
            return False

    def unlove_track(self, artist, track):
        """Set the track as not loved"""
        try:
            self.client.track.unlove(artist, track)
            return True
        except pylastfm.ApiError as exc:
            logger.error('Unable to unlove track', exc_info=exc)
            return False
