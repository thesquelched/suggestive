from configparser import ConfigParser
from os.path import expanduser, expandvars
import re
import logging


# TODO: Use properties


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
            verbose=False,
            log_sql_queries=False,
            session_file='%(conf_dir)s/session',
            update_on_startup=False,
        ),
        mpd=dict(
            host='localhost',
            port=6600,
        ),
        lastfm=dict(
            scrobble_days=180,
            user='',
            api_key='',
            api_secret='',
            log_responses=False,
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

            scrobble_fg='#000',
            scrobble_bg='#fff',
            scrobble_focus_fg='#000',
            scrobble_focus_bg='#0ff',
            scrobble_date_fg='#222',
            scrobble_date_bg='#ff0',

            bumper_fg='#ded',
            bumper_bg='#777',

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
            save_playlist_on_close=False,
            playlist_save_name='suggestive.state',
        ),
        library=dict(
            ignore_artist_the=True,
            default_order='loved; playcount; banned remove_banned=true',
            show_score=False,
            esc_resets_orderers=True,
        ),
        scrobbles=dict(
            initial_load=50,
        ),
        custom_orderers=dict(
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

    def check_config(self):
        conf_url = 'https://github.com/thesquelched/suggestive#configuration'
        if not self.lastfm_apikey():
            return 'Could not determine LastFM API key; see {}'.format(
                conf_url)
        if not self.lastfm_user():
            return 'Could not determine LastFM user; see {}'.format(
                conf_url)

        return None

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

    def lastfm_secret_key(self):
        """Return LastFM secret key"""
        return self.parser['lastfm'].get('api_secret', None)

    def lastfm_session_file(self):
        """Return LastFM session file"""
        return expand(self.parser['general']['session_file'])

    def lastfm_log_responses(self):
        """Return True if responses from LastFM should be logged"""
        return self.parser['lastfm'].getboolean('log_responses')

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
            #return (name, fg, bg)
            return (name, 'default', 'default')

    def palette(self):
        """Return the terminal color palette"""
        colors = self.parser['appearance']

        album = (colors['album_fg'], colors['album_bg'])
        album_focus = (colors['album_focus_fg'], colors['album_focus_bg'])

        playlist = (colors['playlist_fg'], colors['playlist_bg'])
        playlist_focus = (colors['playlist_focus_fg'],
                          colors['playlist_focus_bg'])

        scrobble = (colors['scrobble_fg'], colors['scrobble_bg'])
        scrobble_focus = (
            colors['scrobble_focus_fg'],
            colors['scrobble_focus_bg'])
        scrobble_date = (
            colors['scrobble_date_fg'],
            colors['scrobble_date_bg'])

        track = (colors['track_fg'], colors['track_bg'])
        track_focus = (colors['track_focus_fg'], colors['track_focus_bg'])
        status = (colors['status_fg'], colors['status_bg'])

        footer = (colors['footer_fg'], colors['footer_bg'])
        error = (colors['footer_error_fg'], colors['footer_error_bg'])

        bumper = (colors['bumper_fg'], colors['bumper_bg'])

        return [
            self._palette(None, ('white', 'white')),

            self._palette('album', album),
            self._palette('focus album', album_focus),

            self._palette('scrobble', scrobble),
            self._palette('focus scrobble', scrobble_focus),
            self._palette('scrobble date', scrobble_date),

            self._palette('playlist', playlist),
            self._palette('focus playlist', playlist_focus),
            self._palette('playing', playlist, bold=True),
            self._palette('focus playing', playlist_focus, bold=True,
                          invert=True),

            self._palette('track', track),
            self._palette('focus track', track_focus),

            self._palette('status', status, bold=True),

            self._palette('footer', footer, bold=True),
            self._palette('footer error', error, bold=True),

            self._palette('bumper', bumper)
        ]

    def orientation(self):
        """Return buffer split orientation"""
        return self.parser['general']['orientation']

    def playlist_status_format(self):
        """Return the format for the playlist status bar"""
        return self.parser['playlist']['status_format']

    def save_playlist_on_close(self):
        """Return true if the playlist should be saved on close"""
        return self.parser.getboolean('playlist', 'save_playlist_on_close')

    def playlist_save_name(self):
        """Return the name of the state save playlist"""
        return self.parser['playlist']['playlist_save_name']

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

    def log_sql_queries(self):
        return self.parser.getboolean('general', 'log_sql_queries')

    def default_orderers(self):
        """Return the default orderers"""
        raw = self.parser['library']['default_order']
        return [cmd.strip() for cmd in re.split(r'\s*;\s*', raw)]

    def show_score(self):
        """Return True if the library should show album order scores"""
        return self.parser.getboolean('library', 'show_score')

    def esc_resets_orderers(self):
        """Return True if the escape key should clear library orderers"""
        return self.parser.getboolean('library', 'esc_resets_orderers')

    def custom_orderers(self):
        """Return a dict of custom orderer combinations"""
        orderers = {}
        for name, raw in self.parser['custom_orderers'].items():
            orderer = [cmd.strip() for cmd in re.split(r'\s*;\s*', raw)]
            orderers[name] = orderer

        return orderers

    def initial_scrobbles(self):
        """Return the initial number of scrobbles to load"""
        return self.parser.getint('scrobbles', 'initial_load')

    def update_on_startup(self):
        """Return True if we should do a DB update on startup"""
        return self.parser.getboolean('general', 'update_on_startup')
