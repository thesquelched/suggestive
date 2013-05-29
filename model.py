from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, backref
import lastfm

Base = declarative_base()
engine = create_engine('sqlite:///:memory:', echo=False)
Session = sessionmaker()

class Artist(Base):
  __tablename__ = 'artists'

  id = Column(Integer, primary_key=True)
  name = Column(String)

  def __init__(self, name):
    self.name = name

class Album(Base):
  __tablename__ = 'albums'

  id = Column(Integer, primary_key=True)
  name = Column(String)
  playcount = Column(Integer)
  artist_id = Column(Integer, ForeignKey('artists.id'))

  artist = relationship('Artist', backref=backref('albums', order_by=id))

class Scrobble(Base):
  __tablename__ = 'scrobbles'

  id = Column(Integer, primary_key=True)
  time = Column(DateTime())
  album_id = Column(Integer, ForeignKey('albums.id'))

  album = relationship('Album', backref=backref('scrobbles', order_by=id))
