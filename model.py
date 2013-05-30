from sqlalchemy import create_engine, func, Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property, Comparator
import lastfm

Base = declarative_base()
engine = create_engine('sqlite:///:memory:', echo=False)
Session = sessionmaker()

class CaseInsensitiveComparator(Comparator):
  def __eq__(self, other):
    return func.lower(self.__clause_element__()) == func.lower(other)

class Artist(Base):
  __tablename__ = 'artist'

  id = Column(Integer, primary_key=True)
  name = Column(String, nullable=False, unique=True)

  def __init__(self, name):
    self.name = name

  @hybrid_property
  def name_insensitive(self):
    return self.name.lower()

  @name_insensitive.comparator
  def name_insensitive(cls):
    return CaseInsensitiveComparator(cls.name)

class Album(Base):
  __tablename__ = 'album'

  id = Column(Integer, primary_key=True)
  name = Column(String, nullable=False, unique=True)
  playcount = Column(Integer)
  artist_id = Column(Integer, ForeignKey('artist.id'))

  artist = relationship('Artist', backref=backref('albums', order_by=id))

  @hybrid_property
  def name_insensitive(self):
    return self.name.lower()

  @name_insensitive.comparator
  def name_insensitive(cls):
    return CaseInsensitiveComparator(cls.name)

class ArtistCorrection(Base):
  __tablename__ = 'artist_correction'

  id = Column(Integer, primary_key=True)
  name = Column(String)
  artist_id = Column(Integer, ForeignKey('artist.id'))

  artist = relationship('Artist', backref=backref('corrections', order_by=id))

class AlbumCorrection(Base):
  __tablename__ = 'album_correction'

  id = Column(Integer, primary_key=True)
  name = Column(String)
  album_id = Column(Integer, ForeignKey('album.id'))

  album = relationship('Album', backref=backref('corrections', order_by=id))

class Scrobble(Base):
  __tablename__ = 'scrobble'

  id = Column(Integer, primary_key=True)
  time = Column(DateTime())
  album_id = Column(Integer, ForeignKey('album.id'))

  album = relationship('Album', backref=backref('scrobbles', order_by=id))
