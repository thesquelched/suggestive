from lastfm import LastFM, APIKEY
from model import Artist, Album, Scrobble, Session, Base

import mpd
from sqlalchemy import create_engine

from collections import defaultdict
from itertools import chain

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

def insert_mpd_albums(session, client):
  # TODO: Correct mpd names?
  for artist_name in client.list('artist'):
    artist = session.query(Artist).filter_by(name=artist_name).first()
    if artist is None:
      artist = Artist(artist_name)
      session.add(artist)

    for album_name in client.list('album', 'artist', artist_name):
      album = session.query(Album).join(Artist).\
                      filter(Album.name==album_name).first()
      if album is None:
        album = Album(name=album_name, playcount=0)
        artist.albums.append(album)
        session.add(album)

  session.commit()

def insert_lastfm_albums(session, lastfm, user):
  for resp in lastfm.query_all('library.getAlbums', 'albums', user=user):
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
  insert_mpd_albums(session, mpdclient)

def run():
  session = initialize_sqlalchemy()
  mpdclient = initialize_mpd()
  lastfm = initialize_lastfm()

  user = 'thesquelched'

  initialize_database(session, mpdclient, lastfm, user)
