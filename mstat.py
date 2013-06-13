from lastfm import LastFM, APIKEY
from config import Config
from model import (Artist, AlbumCorrection, ArtistCorrection, Album,
  Scrobble, Session, Base, LoadStatus, Track, ScrobbleInfo)

import mpd
from sqlalchemy import create_engine, func

from datetime import datetime
from time import time, mktime
from collections import defaultdict
from itertools import chain
import logging
import argparse

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

def get(data, *keys, default = None):
  if not keys:
    return data

  if not isinstance(data, dict):
    raise TypeError('not a dictionary')

  key, rest = keys[0], keys[1:]
  if key not in data:
    return default
  
  return get(data[key], rest, default = default)

class ScrobbleLoader(object):
  def __init__(self, lastfm, config):
    self.lastfm = lastfm
    self.user = config.lastfm_user()
    self.retention = config.scrobble_retention()

  def scrobble_info(self, session, artist, album, track):

    db_scrobble_info = session.query(ScrobbleInfo).\
      filter(
        ScrobbleInfo.title == track and
        ScrobbleInfo.artist == artist and
        ScrobbleInfo.album == album).\
      first()

    if not db_scrobble_info:
      db_scrobble_info = ScrobbleInfo(
        title = track,
        artist = artist,
        album = album
      )
      session.add(db_scrobble_info)

    return db_scrobble_info

  def load_scrobble(self, session, item):
    if not ('artist' in item and 'album' in item and 'name' in item and
            'date' in item):
      return

    artist = item['artist'].get('name')
    album = item['album'].get('#text') or item['album'].get('name')
    track = item['name']

    db_scrobble_info = self.scrobble_info(session, artist, album, track)

    when = datetime.fromtimestamp(int(item['date']['uts']))
    scrobble = Scrobble(time = when)

    db_scrobble_info.scrobbles.append(scrobble)
    session.add(scrobble)

    db_track = session.query(Track).\
      join(Artist, Album).\
      filter(Artist.name_insensitive == artist).\
      filter(Album.name_insensitive == album).\
      filter(Track.name_insensitive == track).\
      first()

    if db_track:
      db_track.scrobbles.append(scrobble)

  def load_recent_scrobbles(self, session):
    user = self.user

    last_upd = last_updated(session)
    if not last_upd:
      last_upd = self.retention

    logger.debug('Get scrobbles since {}'.format(
      datetime.fromtimestamp(last_upd).strftime('%Y-%m-%d %H:%M')
    ))

    for item in self.lastfm.scrobbles(user, last_updated = last_upd):
      self.load_scrobble(session, item)

    session.commit()

    set_last_updated(session)

class MpdLoader(object):
  def __init__(self, mpd):
    self.mpd = mpd

  def load_track(self, session, db_artist, db_album, info):
    filename = info['file']
    if not session.query(Track).filter_by(filename = filename).first():
      if 'title' not in info:
        return

      db_track = Track(
        name = info['title'],
        filename = filename,
      )
      db_album.tracks.append(db_track)
      db_artist.tracks.append(db_track)
      session.add(db_track)

  def load_album(self, session, db_artist, album):
    db_album = session.query(Album).filter_by(name = album).first()
    if not db_album:
      db_album = Album(name = album)
      db_artist.albums.append(db_album)
      session.add(db_album)

    for info in self.mpd.search('artist', db_artist.name, 'album', album):
      self.load_track(session, db_artist, db_album, info)

  def load_artist(self, session, artist):
    db_artist = session.query(Artist).filter_by(name = artist).first()
    if not db_artist:
      db_artist = Artist(name = artist)
      session.add(db_artist)

    for album in self.mpd.list('album', 'artist', artist):
      self.load_album(session, db_artist, album)

  def load(self, session):
    for artist in self.mpd.list('artist'):
      self.load_artist(session, artist)

    session.commit()

def configuration(path = None):
  return Config(path = path)

def initialize_sqlalchemy(config, echo = False):
  path = 'sqlite:///{}'.format(config.database())
  engine = create_engine(path, echo=bool(echo))
  Session.configure(bind=engine)

  Base.metadata.create_all(engine)

  return Session()

def initialize_mpd(config):
  host, port = config.mpd()

  client = mpd.MPDClient()
  client.connect(host, port)

  return client

def initialize_lastfm(config):
  return LastFM(config.lastfm_apikey())

def correct_artist(name, lastfm):
  logger.debug('Attempting to find a correction for {}'.format(name))

  resp = lastfm.query('artist.getCorrection', artist=name)
  if 'corrections' in resp and isinstance(resp['corrections'], dict):
    correct = resp['corrections']['correction']
    if 'artist' in correct:
      info = correct['artist']
      artist = Artist(
        name = info['name'],
        mbid = info.get('mbid'),
      )
      corrected = ArtistCorrection(name=name)

      logger.info("Corrected '{}' to '{}'".format(name, artist.name))
      return (artist, corrected)

  artist = Artist(name=name)
  return (artist, None)

def delete_old_scrobbles(session, config):
  delete_before = datetime.fromtimestamp(config.scrobble_retention())
  session.query(Scrobble).filter(Scrobble.date < delete_before).delete()

def last_updated(session):
  status = session.query(LoadStatus).first()
  if status:
    #return int(status.last_updated.timestamp())
    return int(mktime(status.last_updated.timetuple()))
  else:
    return None

def set_last_updated(session):
  session.query(LoadStatus).delete()
  session.add(LoadStatus(last_updated = datetime.now()))

  session.commit()

def update_database(session, mpdclient, lastfm, config):
  artists_start = session.query(Artist).count()
  albums_start = session.query(Album).count()
  tracks_start = session.query(Track).count()

  mpd_loader = MpdLoader(mpdclient)
  mpd_loader.load(session)

  new_artists = session.query(Artist).count() - artists_start
  new_albums = session.query(Album).count() - albums_start
  new_tracks = session.query(Track).count() - tracks_start

  logger.info('Inserted {} artists'.format(new_artists))
  logger.info('Inserted {} albums'.format(new_albums))
  logger.info('Inserted {} tracks'.format(new_tracks))

  # TODO: delete old scrobbles here
  scrobbles_start = session.query(Scrobble).count()

  scrobble_loader = ScrobbleLoader(lastfm, config)
  scrobble_loader.load_recent_scrobbles(session)

  new_scrobbles = session.query(Scrobble).count() - scrobbles_start

  logger.info('Inserted {} scrobbles'.format(new_scrobbles))

def main():
  parser = argparse.ArgumentParser(description='Suggest lastfm stuff')
  parser.add_argument('--config', '-c', help='Configuration file')

  args = parser.parse_args()

  run(args.config)

def run(config_path = None):
  config = configuration(path = config_path)

  session = initialize_sqlalchemy(config)
  mpdclient = initialize_mpd(config)
  lastfm = initialize_lastfm(config)

  update_database(session, mpdclient, lastfm, config)

  return session

def init_logging():
  logging.basicConfig(level=logging.DEBUG)
  logging.getLogger('mpd').setLevel(logging.ERROR)
  logging.getLogger('requests').setLevel(logging.ERROR)

if __name__ == '__main__':
  init_logging()
  main()
