from lastfm import LastFM, APIKEY
from config import Config
from model import (Artist, AlbumCorrection, ArtistCorrection, Album,
  Scrobble, Session, Base, LoadStatus, Track, ScrobbleInfo)

import mpd
from sqlalchemy import create_engine, func

from datetime import datetime
from time import time
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

def most_likely_album(name, artist, lastfm):
  resp = lastfm.query('album.search', album=name)

  try:
    albums = get(resp, 'results', 'albummatches', 'album')
  except TypeError:
    return None

  if not isinstance(albums, list):
    return None

  albums_by_artist = defaultdict(list)
  for album in albums:
    if isinstance(album, dict):
      albums_by_artist[album['artist']].append(album['name'])

  if artist.name in albums_by_artist:
    return min(albums_by_artist[artist.name], key = lambda alb: len(alb))

def correct_album(name, artist, lastfm, session):
  logger.debug('Attempt to find a correction for {}'.format(name))

  likely_album = most_likely_album(name, artist, lastfm)
  if likely_album:
    logger.info("Corrected '{}' to '{}'".format(name, likely_album))
    album = session.query(Album).filter_by(name=likely_album).first()
    if album:
      corrected = None
    else:
      album = Album(name=likely_album, playcount=0)
      corrected = AlbumCorrection(name=likely_album)
  else:
    album = Album(name=name, playcount=0)
    corrected = None

  return (album, corrected)

def insert_mpd_albums(session, mpdclient, lastfm):
  for artist_name in mpdclient.list('artist'):
    artist = session.query(Artist).\
                     filter_by(name_insensitive = artist_name).\
                     first()
    if artist is None:
      artist = session.query(ArtistCorrection).\
               filter_by(name_insensitive = artist_name).first()
      if artist is None:
        artist, correction = correct_artist(artist_name, lastfm)
        session.add(artist)
        if correction:
          artist.corrections.append(correction)
          session.add(correction)

    for album_name in mpdclient.list('album', 'artist', artist_name):
      # Look in database
      album = session.query(Album).join(Artist).\
                      filter(Album.name==album_name).first()
      if album is None:
        # try to find an existing correction for this name
        correction = session.query(AlbumCorrection).\
                     filter_by(name=album_name).first()
        if correction is None:
          # Try to find a correction from LastFM
          album, correction = correct_album(album_name, artist, lastfm, session)
          session.add(album)
          if correction:
            album.corrections.append(correction)
            session.add(correction)

          artist.albums.append(album)

  session.commit()

def insert_lastfm_albums(session, lastfm, config):
  user = config.lastfm_user()
  for resp in lastfm.query_all('library.getAlbums', 'albums', user=user):
    if 'albums' not in resp:
      continue
    for album_resp in resp['albums']['album']:
      if 'artist' in album_resp:
        artist_name = album_resp['artist']['name']
        mbid = album_resp['artist'].get('mbid')
      else:
        artist_name = 'Unknown'
        mbid = None

      artist = session.query(Artist).filter_by(name=artist_name).first()
      if artist is None:
        artist = Artist(
          name = artist_name,
          mbid = mbid,
        )
        session.add(artist)

      album_name = album_resp['name']
      album_plays = album_resp['playcount']

      album = session.query(Album).join(Artist).\
                      filter(Album.name==album_name).first()
      if album:
        album.playcount = album_plays
      else:
        album = Album(
          name = album_resp['name'],
          playcount = album_resp['playcount'],
        )
        artist.albums.append(album)

      session.add(album)

  session.commit()

def delete_old_scrobbles(session, config):
  delete_before = datetime.fromtimestamp(config.scrobble_retention())
  session.query(Scrobble).filter(Scrobble.date < delete_before).delete()

def last_updated(session):
  status = session.query(LoadStatus).first()
  if status:
    return int(status.last_updated.timestamp())
  else:
    return None

def insert_recent_scrobbles(session, lastfm, config):
  user = config.lastfm_user()

  last_upd = last_updated(session)
  if not last_upd:
    last_upd = config.scrobble_retention()

  logger.debug('Get scrobbles since {}'.format(
    datetime.fromtimestamp(last_upd).strftime('%Y-%m-%d %H:%M')
  ))

  for item in lastfm.scrobbles(user, last_updated = last_upd):
    artist = session.query(Artist).filter(
      Artist.mbid == item['artist'].get('mbid') or
      Artist.name_insensitive == item['artist']['name']).first()
    if not artist:
      continue

    album_name = item['album'].get('#text') or item['album'].get('name')
    album = session.query(Album).filter(
      Album.mbid == item['album'].get('mbid') or
      Album.name_insensitive == album_name).first()
    if not album:
      continue

    track = session.query(Track).filter(
      Track.mbid == item.get('mbid') or
      Track.name_insensitive == item['name']).first()
    if not track:
      track = Track(
        name=item['name'],
        mbid=item.get('mbid'),
        loved=bool(int(item['loved']))
      )
      artist.tracks.append(track)
      album.tracks.append(track)
      session.add(track)

    when = datetime.fromtimestamp(int(item['date']['uts']))
    scrobble = Scrobble(time=when)

    track.scrobbles.append(scrobble)
    session.add(scrobble)

  session.commit()

  set_last_updated(session)

def set_last_updated(session):
  session.query(LoadStatus).delete()
  session.add(LoadStatus(last_updated = datetime.now()))

  session.commit()

def initialize_database(session, mpdclient, lastfm, config):
  artists_start = session.query(Artist).count()
  albums_start = session.query(Album).count()

  #insert_lastfm_albums(session, lastfm, config)
  
  artists_after_lastfm = session.query(Artist).count()
  albums_after_lastfm = session.query(Album).count()
  logging.info('Inserted {} artists with {} albums from LastFM'.format(
    artists_after_lastfm - artists_start,
    albums_after_lastfm - albums_start
  ))

  insert_mpd_albums(session, mpdclient, lastfm)

  artists_after_mpd = session.query(Artist).count()
  albums_after_mpd = session.query(Album).count()
  logging.info('Inserted {} artists with {} albums from local machine'.format(
    artists_after_mpd - artists_after_lastfm,
    albums_after_mpd - albums_after_lastfm
  ))

  insert_recent_scrobbles(session, lastfm, config)

def run():
  parser = argparse.ArgumentParser(description='Suggest lastfm stuff')
  parser.add_argument('--config', '-c', help='Configuration file')

  args = parser.parse_args()

  config = configuration(path = args.config)

  session = initialize_sqlalchemy(config)
  mpdclient = initialize_mpd(config)
  lastfm = initialize_lastfm(config)

  initialize_database(session, mpdclient, lastfm, config)

  return session

def init_logging():
  logging.basicConfig(level=logging.DEBUG)
  logging.getLogger('mpd').setLevel(logging.ERROR)
  logging.getLogger('requests').setLevel(logging.ERROR)

if __name__ == '__main__':
  init_logging()
  run()
