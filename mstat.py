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

def mpd_albums(client):
  return {artist: client.list('album', 'artist', artist)
          for artist in client.list('artist')}

def lastfm_albums(lastfm, user):
  albums = defaultdict(list)
  for resp in lastfm.query_all('library.getAlbums', 'albums', user=user):
    for album in resp['albums']['album']:
      if 'artist' in album:
        artist = album['artist']['name']
        albums[artist].append(album['name'])

  return albums

def initialize_database(session, mpdclient, lastfm, user):
  local_albums = mpd_albums(mpdclient)
  scrobbled_albums = lastfm_albums(lastfm, user)

  for artist, albums in local_albums.items():
    pass

def run():
  session = initialize_sqlalchemy()
  mpdclient = initialize_mpd()
  lastfm = initialize_lastfm()

  initialize_database(session, mpdclient, lastfm)
