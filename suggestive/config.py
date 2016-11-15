from configparser import ConfigParser
from os.path import expanduser, expandvars
import re
import logging
from figgis import Config as FiggisConfig, Field, ValidationError


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


SECONDS_IN_DAY = 24 * 3600
CONFIG_PATHS = [
    '$HOME/.suggestive.conf',
    '/etc/suggestive.conf',
]
VALID_BUFFERS = frozenset(('library', 'playlist', 'scrobbles'))
VALID_ORIENTATIONS = frozenset(('horizontal', 'vertical'))


def interpolate(value, config):
    if not isinstance(value, str):
        return value

    # Convert to python3 format syntax
    converted = re.sub(r'%\((\w+)\)[a-z]', r'{\1}', value)

    return converted.format(**config)


def expand(path):
    """Expand a unix path"""
    return expanduser(expandvars(path))


def CSV(value):
    if isinstance(value, list):
        return value

    return re.split(r'\s*,\s*', value) if value else []


def valid_buffers(buffers):
    valid = []

    for buf in (item.lower() for item in buffers):
        if buf in VALID_BUFFERS:
            valid.append(buf)
        else:
            logger.warn('{} is not a valid buffer', buf)

    return valid


def non_negative(value):
    return max(value, 0)


def color(raw):
    value = str(raw)
    if re.match(r'^#[0-9a-f]{3,6}$', value, re.I) is None:
        raise ValidationError('Invalid color: {}'.format(value))

    return value


def commands(value):
    if not value:
        return []
    elif isinstance(value, list):
        return value

    return re.split(r'\s*;\s*', value)


def parse_custom_orders(value):
    return {name: commands(value) for name, value in value.items()}


class GeneralConfig(FiggisConfig):

    conf_dir = Field(expand, default='$HOME/.suggestive')
    database = Field(expand, default='{conf_dir}/music.db')
    highcolor = Field(bool, default=True)
    default_buffers = Field(CSV, valid_buffers, default=['library', 'playlist'])
    orientation = Field(default='horizontal', choices=VALID_ORIENTATIONS)
    log = Field(expand, default='{conf_dir}/log.txt')
    verbose = Field(bool, default=False)
    log_sql_queries = Field(bool, default=False)
    session_file = Field(expand, default='{conf_dir}/session')
    update_on_startup = Field(bool, default=False)

    @property
    def colormode(self):
        return 256 if self.highcolor else 88

    @property
    def log_level(self):
        return logging.DEBUG if self.verbose else logging.INFO

    @property
    def sqlalchemy_url(self):
        return 'sqlite:///{}'.format(self.database)


class MpdConfig(FiggisConfig):

    host = Field(default='localhost')
    port = Field(int, default=6600)


class LastfmConfig(FiggisConfig):

    scrobble_days = Field(int, non_negative, default=180)
    user = Field(default='')
    api_key = Field(default='')
    api_secret = Field(default='')
    log_responses = Field(bool, default=False)
    url = Field(default='http://ws.audioscrobbler.com/2.0')


class AppearanceConfig(FiggisConfig):

    album_fg = Field(color, default='#000')
    album_bg = Field(color, default='#fff')
    album_focus_fg = Field(color, default='#000')
    album_focus_bg = Field(color, default='#0ff')
    playlist_fg = Field(color, default='#000')
    playlist_bg = Field(color, default='#fff')
    playlist_focus_fg = Field(color, default='#000')
    playlist_focus_bg = Field(color, default='#0ff')
    scrobble_fg = Field(color, default='#000')
    scrobble_bg = Field(color, default='#fff')
    scrobble_focus_fg = Field(color, default='#000')
    scrobble_focus_bg = Field(color, default='#0ff')
    scrobble_date_fg = Field(color, default='#222')
    scrobble_date_bg = Field(color, default='#ff0')
    bumper_fg = Field(color, default='#ded')
    bumper_bg = Field(color, default='#777')
    track_fg = Field(color, default='#000')
    track_bg = Field(color, default='#ccc')
    track_focus_fg = Field(color, default='#000')
    track_focus_bg = Field(color, default='#0ff')
    footer_fg = Field(color, default='#000')
    footer_bg = Field(color, default='#00f')
    footer_error_fg = Field(color, default='#000')
    footer_error_bg = Field(color, default='#f00')
    status_fg = Field(color, default='#000')
    status_bg = Field(color, default='#08f')

    def _palette(self, name, color, bold=False, invert=False):
        if invert:
            bg, fg = color
        else:
            fg, bg = color

        if bold:
            fg = 'bold,' + fg

        if self.parent.general.highcolor:
            return (name, '', '', '', fg, bg)
        else:
            (name, 'default', 'default')

    @property
    def palette(self):
        """Return the terminal color palette"""
        album = (self.album_fg, self.album_bg)
        album_focus = (self.album_focus_fg, self.album_focus_bg)

        playlist = (self.playlist_fg, self.playlist_bg)
        playlist_focus = (self.playlist_focus_fg, self.playlist_focus_bg)

        scrobble = (self.scrobble_fg, self.scrobble_bg)
        scrobble_focus = (self.scrobble_focus_fg, self.scrobble_focus_bg)
        scrobble_date = (self.scrobble_date_fg, self.scrobble_date_bg)

        track = (self.track_fg, self.track_bg)
        track_focus = (self.track_focus_fg, self.track_focus_bg)
        status = (self.status_fg, self.status_bg)

        footer = (self.footer_fg, self.footer_bg)
        error = (self.footer_error_fg, self.footer_error_bg)

        bumper = (self.bumper_fg, self.bumper_bg)

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
            self._palette('focus playing', playlist_focus, bold=True, invert=True),

            self._palette('track', track),
            self._palette('focus track', track_focus),

            self._palette('status', status, bold=True),

            self._palette('footer', footer, bold=True),
            self._palette('footer error', error, bold=True),

            self._palette('bumper', bumper)
        ]


class PlaylistConfig(FiggisConfig):

    __nointerpolate__ = {'status_format'}

    status_format = Field(default='{status}: {artist} - {title} [{time_elapsed}/{time_total}]')
    save_playlist_on_close = Field(bool, default=False)
    playlist_save_name = Field(default='suggestive.state')


class LibraryConfig(FiggisConfig):

    ignore_artist_the = Field(bool, default=True)
    default_order = Field(commands, default=['loved', 'playcount'])
    show_score = Field(bool, default=False, read_only=False)
    esc_resets_orderers = Field(bool, default=True)


class ScrobblesConfig(FiggisConfig):
    initial_load = Field(int, non_negative, default=50)


class Config(FiggisConfig):

    general = Field(GeneralConfig)
    mpd = Field(MpdConfig)
    lastfm = Field(LastfmConfig)
    appearance = Field(AppearanceConfig)
    playlist = Field(PlaylistConfig)
    library = Field(LibraryConfig)
    scrobbles = Field(ScrobblesConfig)
    custom_orderers = Field(parse_custom_orders, default={})

    def __init__(self, args=None, configuration=None):
        if configuration:
            super().__init__(configuration)
            return

        parser = ConfigParser()
        paths = CONFIG_PATHS
        if args and args.config:
            paths = [args.config] + CONFIG_PATHS

        # Make sure all sections are present
        parser.read([expand(path) for path in paths])
        for section in self._fields:
            if not parser.has_section(section):
                parser.add_section(section)

        # Override from CLI
        data = self._override_config(parser, args)

        # Parse config without interpolation first, then do interpolation afterward.  This prevents
        # fields with defaults from not being interpolated properly
        first_pass_conf = Config(configuration=data)
        first_pass = first_pass_conf.to_dict()

        # Do string interpolation
        for section, settings in first_pass.items():
            nointerpolate = getattr(getattr(first_pass_conf, section), '__nointerpolate__', [])
            for key, value in settings.items():
                settings[key] = value if key in nointerpolate else interpolate(value, settings)

        super().__init__(first_pass)

    def _override_config(self, parser, args):
        if args:
            if args.log:
                parser['general']['log'] = args.log

        return parser._sections
