from configparser import ConfigParser
from os.path import expanduser, expandvars
from time import time


SECONDS_IN_DAY = 24 * 3600
CONFIG_PATHS = [
    '$HOME/.suggestive.conf',
    '/etc/suggestive.conf',
]


def expand(path):
    """Expand a unix path"""
    return expanduser(expandvars(path))


class Config(object):

    """Suggestive configuration object"""

    DEFAULTS = dict(
        general=dict(
            conf_dir='$HOME/.suggestive',
            database='$HOME/.suggestive/music.db',
            highcolor=True,
        ),
        mpd=dict(
            host='localhost',
            port=6600,
            client='ncmpcpp',
        ),
        lastfm=dict(
            scrobble_days=180,
            # user
            # api_key
        ),
        appearance=dict(
            album_fg='#000',
            album_bg='#fff',
            album_focus_fg='#000',
            album_focus_bg='#0ff',

            playlist_fg='#000',
            playlist_bg='#fff',
            playlist_focus_fg='#000',
            playlist_focus_bg='#0ff',

            track_fg='#000',
            track_bg='#ccc',
            track_focus_fg='#000',
            track_focus_bg='#0ff',

            footer_fg='#000',
            footer_bg='#00f',
            footer_error_fg='#000',
            footer_error_bg='#f00',

            status_fg='#000',
            status_bg='#08f',
        ),
    )

    def __init__(self, path=None):
        parser = ConfigParser()
        parser.read_dict(self.DEFAULTS)

        paths = CONFIG_PATHS
        if path:
            paths = [path] + CONFIG_PATHS

        parser.read(map(expand, paths))

        self.parser = parser

    def mpd(self):
        """Return (host, port)"""
        mpd = self.parser['mpd']
        return (
            mpd['host'],
            mpd.getint('port'),
        )

    def mpd_client(self):
        """Return mpd client program"""
        return self.parser['mpd']['client']

    def lastfm_user(self):
        """Return LastFM user name"""
        return self.parser['lastfm']['user']

    def lastfm_apikey(self):
        """Return LastFM API key"""
        return self.parser['lastfm']['api_key']

    def scrobble_retention(self):
        """Return seconds to keep LastFM scrobbles"""
        ret = self.parser['lastfm'].getint('scrobble_days') * SECONDS_IN_DAY
        return int(time() - ret)

    def database(self):
        """Return the path to the database file"""
        return expand(self.parser['general']['database'])

    def use_256_colors(self):
        """Return True if the terminal should be set to 256 colors"""
        return self.parser.getboolean('general', 'highcolor')

    def _palette(self, name, color, bold=False):
        if self.use_256_colors():
            return (name, '', '', '', 'bold,' + color[0], color[1])
        else:
            return (name, 'bold,' + color[0], color[1])

    def palette(self):
        """Return the terminal color palette"""
        colors = self.parser['appearance']

        album = (colors['album_fg'], colors['album_bg'])
        album_focus = (colors['album_focus_fg'], colors['album_focus_bg'])
        playlist = (colors['playlist_fg'], colors['playlist_bg'])
        playlist_focus = (colors['playlist_focus_fg'],
                          colors['playlist_focus_bg'])
        track = (colors['track_fg'], colors['track_bg'])
        track_focus = (colors['track_focus_fg'], colors['track_focus_bg'])
        status = (colors['status_fg'], colors['status_bg'])

        footer = (colors['footer_fg'], colors['footer_bg'])
        error = (colors['footer_error_fg'], colors['footer_error_bg'])

        return [
            self._palette(None, ('white', 'white')),
            self._palette('album', album),
            self._palette('focus album', album_focus),
            self._palette('playlist', playlist),
            self._palette('focus playlist', playlist_focus),
            self._palette('track', track),
            self._palette('focus track', track_focus),
            self._palette('status', status, bold=True),

            self._palette('footer', footer, bold=True),
            self._palette('footer error', error, bold=True),
        ]
