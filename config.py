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


def palette(name, color):
    return (name, color[0], color[1], '', color[0], color[1])


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
        ),
        lastfm=dict(
            scrobble_days=180,
            # user
            # api_key
        ),
        appearance=dict(
          album_fg='black',
          album_bg='white',
          album_focus_fg='white',
          album_focus_bg='light blue',
          status_fg='bold,white',
          status_bg='black',
          header_fg='bold,black',
          header_bg='light green',
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

    def palette(self):
        """Return the terminal color palette"""
        colors = self.parser['appearance']

        album = (colors['album_fg'], colors['album_bg'])
        album_focus = (colors['album_focus_fg'], colors['album_focus_bg'])
        header = (colors['header_fg'], colors['header_bg'])
        status = (colors['status_fg'], colors['status_bg'])

        return [
            palette(None, album),
            palette('album', album),
            palette('focus album', album_focus),
            palette('status', status),
            palette('header', header),
        ]
