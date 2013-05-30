from lastfm import LastFM, APIKEY
from model import Artist, AlbumCorrection, ArtistCorrection, Album, Scrobble, Session, Base

import mpd
from sqlalchemy import create_engine

from collections import defaultdict
from itertools import chain
import logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

def initialize_sqlalchemy():
  engine = create_engine('sqlite:///:memory:', echo=False)
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
  logger.info('Attempting to find a correction for {}'.format(name))

  resp = lastfm.query('artist.getCorrection', artist=name)
  if 'corrections' in resp and isinstance(resp['corrections'], dict):
    correct = resp['corrections']['correction']
    if 'artist' in correct:
      artist = Artist(name=correct['artist']['name'])
      corrected = ArtistCorrection(name=name)

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
  logger.info('Attempt to find a correction for {}'.format(name))

  likely_album = most_likely_album(name, artist, lastfm)
  if likely_album:
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
    for album in resp['albums']['album']:
      if 'artist' in album:
        artist_name = album['artist']['name']
      else:
        artist_name = 'Unknown'

      artist = session.query(Artist).filter_by(name=artist_name).first()
      if artist is None:
        artist = Artist(artist_name)
        session.add(artist)

      album = Album(
        name = album['name'],
        playcount = album['playcount'],
      )

      artist.albums.append(album)
      session.add(album)

  session.commit()

def initialize_database(session, mpdclient, lastfm, user):
  insert_lastfm_albums(session, lastfm, user)
  insert_mpd_albums(session, mpdclient, lastfm)

def run():
  session = initialize_sqlalchemy()
  mpdclient = initialize_mpd()
  lastfm = initialize_lastfm()

  user = 'thesquelched'

  initialize_database(session, mpdclient, lastfm, user)
