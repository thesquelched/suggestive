from configparser import ConfigParser
from os.path import expanduser, expandvars
from time import time
import re
import logging


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
            database='%(conf_dir)s/music.db',
            highcolor=True,
            default_buffers='library,playlist',
            orientation='horizontal',
            log='%(conf_dir)s/log.txt',
            verbose=False
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
        playlist=dict(
            status_format='{status}: {artist} - {title} '
                          '[{time_elapsed}/{time_total}]',
        ),
        library=dict(
            ignore_artist_the=True
        ),
    )

    def __init__(self, args=None):
        parser = ConfigParser()
        parser.read_dict(self.DEFAULTS)

        paths = CONFIG_PATHS
        if args and args.config:
            paths = [args.config] + CONFIG_PATHS

        parser.read(map(expand, paths))
        self.parser = self.override_config(parser, args) if args else parser

    @classmethod
    def override_config(cls, parser, args):
        if args.log:
            parser['general']['log'] = args.log

        return parser

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
        return self.parser['lastfm'].getint('scrobble_days')

    def database(self):
        """Return the path to the database file"""
        return expand(self.parser['general']['database'])

    def use_256_colors(self):
        """Return True if the terminal should be set to 256 colors"""
        return self.parser.getboolean('general', 'highcolor')

    def default_buffers(self):
        """Return a list of the default screens to display"""
        raw = self.parser['general']['default_buffers']
        screens = set(re.split(r'\s*,\s*', raw))

        # Always have library
        screens.add('library')

        return screens

    def _palette(self, name, color, bold=False, invert=False):
        if invert:
            bg, fg = color
        else:
            fg, bg = color

        if bold:
            fg = 'bold,' + fg

        if self.use_256_colors():
            return (name, '', '', '', fg, bg)
        else:
            return (name, fg, bg)

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
            self._palette('playing', playlist, bold=True),
            self._palette('playing focus', playlist_focus, bold=True,
                          invert=True),

            self._palette('track', track),
            self._palette('focus track', track_focus),

            self._palette('status', status, bold=True),

            self._palette('footer', footer, bold=True),
            self._palette('footer error', error, bold=True),
        ]

    def orientation(self):
        """Return buffer split orientation"""
        return self.parser['general']['orientation']

    def playlist_status_format(self):
        """Return the format for the playlist status bar"""
        return self.parser['playlist']['status_format']

    def ignore_artist_the(self):
        """Return True if sorting albums should ignore the word 'The' in the
        artist name"""
        return self.parser.getboolean('library', 'ignore_artist_the')

    def log_file(self):
        """Return the log file path"""
        return expand(self.parser['general']['log'])

    def log_level(self):
        """Return the log level"""
        if self.parser.getboolean('general', 'verbose'):
            return logging.DEBUG
        else:
            return logging.INFO
