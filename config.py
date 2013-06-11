from configparser import ConfigParser
from os.path import expanduser, expandvars


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
    general = dict(
      database = '$HOME/.suggestive/music.db',
    ),
    mpd = dict(
      host = 'localhost',
      port = 6600,
    ),
    lastfm = dict(
      scrobble_days = 180,
      # user
    ),
  )

  def __init__(self, path = None):
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

  def lastfm(self):
    """Return (user, scrobble_days)"""
    lastfm = sef.parser['lastfm']
    return (
      lastfm['user'],
      lastfm.getint('scrobble_days'),
    )

  def database(self):
    """Return the path to the database file"""
    return expand(self.parser['general']['database'])
