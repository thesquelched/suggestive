from lastfm import LastFM, APIKEY
from model import (Artist, AlbumCorrection, ArtistCorrection, Album,
  Scrobble, Session, Base, LoadStatus, Track)

import mpd
from sqlalchemy import create_engine, func

from datetime import datetime
from time import time
from collections import defaultdict
from itertools import chain
import logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

SQLITE_DB = './music.db'

SCROBBLE_RETENTION_DAYS = 180
SECONDS_IN_DAY = 24*3600

def retention(days):
  return int(time()) - days*SECONDS_IN_DAY

def initialize_sqlalchemy():
  path = 'sqlite:///{}'.format(SQLITE_DB)
  engine = create_engine(path, echo=False)
  Session.configure(bind=engine)

  Base.metadata.create_all(engine)

  return Session()

def initialize_mpd(host=None, port=None):
  if host is None:
    host = 'localhost'
  if port is None:
    port = 6600

  client = mpd.MPDClient()
  client.connect(host, port)

  return client

def initialize_lastfm():
  return LastFM(APIKEY)

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
  if 'results' in resp and 'albummatches' in resp['results']:
    albums = resp['results']['albummatches']['album']

    albums_by_artist = defaultdict(list)
    for album in albums:
      if isinstance(album, dict):
        albums_by_artist[album['artist']].append(album['name'])

    if artist.name in albums_by_artist:
      return min(albums_by_artist[artist.name], key = lambda alb: len(alb))

  return None

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

def insert_lastfm_albums(session, lastfm, user):
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

def delete_old_scrobbles(session):
  delete_before = datetime.fromtimestamp(retention(SCROBBLE_RETENTION_DAYS))
  session.query(Scrobble).filter(Scrobble.date < delete_before).delete()

def insert_recent_scrobbles(session, lastfm, user):
  status = session.query(LoadStatus).first()
  if status:
    since = int(status.last_updated.timestamp())
    logger.info('Last updated: {}'.format(status.last_updated))
  else:
    since = retention(SCROBBLE_RETENTION_DAYS)


  args = {
    'limit': 200,
    'user': user,
    'from': since,
    'extended': 1
  }
  for resp in lastfm.query_all('user.getRecentTracks', 'recenttracks', **args):
    recent = resp['recenttracks']
    if 'track' not in recent or not isinstance(recent['track'], list):
      continue

    for item in recent['track']:
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

  if status:
    status.time = datetime.now()
  else:
    status = LoadStatus(last_updated = datetime.now())

  session.add(status)
  session.commit()

def initialize_database(session, mpdclient, lastfm, user):
  insert_lastfm_albums(session, lastfm, user)

  n_artists = session.query(Artist).count()
  n_albums = session.query(Album).count()
  logging.info('Inserted {} artists with {} albums from LastFM'.format(n_artists, n_albums))

  insert_mpd_albums(session, mpdclient, lastfm)
  insert_recent_scrobbles(session, lastfm, user)

def run():
  session = initialize_sqlalchemy()
  mpdclient = initialize_mpd()
  lastfm = initialize_lastfm()

  user = 'thesquelched'

  initialize_database(session, mpdclient, lastfm, user)

if __name__ == '__main__':
  logging.basicConfig(level=logging.DEBUG)
  logging.getLogger('mpd').setLevel(logging.ERROR)
  logging.getLogger('requests').setLevel(logging.ERROR)
  run()
