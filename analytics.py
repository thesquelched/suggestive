from mstat import run
from model import Album, Track, Scrobble
from sqlalchemy import func, desc, asc


class Suggestion(object):
  def __init__(self, album, reasons):
    self.album = album
    self.reasons = set(reasons)

class Reason(object):
  def __str__(self):
    return self.__class__.__doc__

class NotPlayedRecently(Reason):
  """Album was not played recently"""
  pass

class HasLovedTracks(Reason):
  """Album has loved tracks"""
  pass

NOT_PLAYED_RECENTLY = NotPlayedRecently()
HAS_LOVED_TRACKS = HasLovedTracks()

class Analytics(object):
  def __init__(self, session):
    self.session = session

  def not_recently_played(self):
    return self.session.query(Album).\
      outerjoin(Album.tracks).\
      outerjoin(Track.scrobbles).\
      group_by(Album.id).\
      having(func.count(Scrobble.id) == 0)

  def suggest_albums(self, n_albums = None):
    not_played = self.not_recently_played()

    if n_albums is None:
      albums = not_played.all()
    else:
      albums = not_played.limit(n_albums).all()

    return [Suggestion(album, [NOT_PLAYED_RECENTLY]) for album in albums]
