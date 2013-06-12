from configparser import ConfigParser
from os.path import expanduser, expandvars
from time import time


SECONDS_IN_DAY = 24*3600
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
      # api_key
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
