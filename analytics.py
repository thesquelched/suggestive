from mstat import run
from model import Album, Track, Scrobble
from sqlalchemy import func, desc, asc

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
      return not_played.all()
    else:
      return not_played.limit(n_albums).all()
