from mstat import run
from model import Album, Track, Scrobble
from sqlalchemy import func, desc, asc

class Analytics(object):
  def __init__(self, session):
    self.session = session

  def not_recently_played(self):
    return self.session.query(Album).outerjoin(Track, Scrobble).\
      group_by(Album.playcount, Album.id).\
      order_by(asc(Album.playcount)).\
      having(func.count(Scrobble.id) == 0)

  def suggest_albums(self, n_albums):
    not_played = self.not_recently_played()
    return not_played.limit(n_albums).all()
