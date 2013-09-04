from sqlalchemy import (func, Column, Integer, String,
                        ForeignKey, DateTime, Boolean)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property, Comparator

Base = declarative_base()
Session = sessionmaker()


class CaseInsensitiveComparator(Comparator):

    def __eq__(self, other):
        return func.lower(self.__clause_element__()) == func.lower(other)


class LoadStatus(Base):
    __tablename__ = 'load_status'

    scrobbles_initialized = Column(Boolean, default=False, primary_key=True)


class Artist(Base):
    __tablename__ = 'artist'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    correction = relationship(
        "ArtistCorrection", uselist=False, backref="artist")

    @hybrid_property
    def name_insensitive(self):
        return self.name.lower()

    @name_insensitive.comparator
    def name_insensitive(cls):
        return CaseInsensitiveComparator(cls.name)


class Album(Base):
    __tablename__ = 'album'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    artist_id = Column(Integer, ForeignKey('artist.id'))

    artist = relationship('Artist', backref=backref('albums', order_by=id))

    @hybrid_property
    def name_insensitive(self):
        return self.name.lower()

    @name_insensitive.comparator
    def name_insensitive(cls):
        return CaseInsensitiveComparator(cls.name)


class LastfmTrackInfo(Base):
    __tablename__ = 'lastfm_track_info'

    id = Column(Integer, primary_key=True)
    loved = Column(Boolean, default=False)
    banned = Column(Boolean, default=False)

    track_id = Column(Integer, ForeignKey('track.id'))


class Track(Base):
    __tablename__ = 'track'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    filename = Column(String, nullable=False, unique=True)
    lastfm_info = relationship(
        "LastfmTrackInfo", uselist=False, backref="track")
    album_id = Column(Integer, ForeignKey('album.id'))
    artist_id = Column(Integer, ForeignKey('artist.id'))

    album = relationship('Album', backref=backref('tracks', order_by=id))
    artist = relationship('Artist', backref=backref('tracks', order_by=id))

    @hybrid_property
    def name_insensitive(self):
        return self.name.lower()

    @name_insensitive.comparator
    def name_insensitive(cls):
        return CaseInsensitiveComparator(cls.name)


class ScrobbleInfo(Base):
    __tablename__ = 'scrobble_info'

    id = Column(Integer, primary_key=True)
    title = Column(String)
    album = Column(String)
    artist = Column(String)

    @hybrid_property
    def title_insensitive(self):
        return self.title.lower()

    @title_insensitive.comparator
    def title_insensitive(cls):
        return CaseInsensitiveComparator(cls.title)

    @hybrid_property
    def artist_insensitive(self):
        return self.artist.lower()

    @artist_insensitive.comparator
    def artist_insensitive(cls):
        return CaseInsensitiveComparator(cls.artist)

    @hybrid_property
    def album_insensitive(self):
        return self.album.lower()

    @album_insensitive.comparator
    def album_insensitive(cls):
        return CaseInsensitiveComparator(cls.album)


class Scrobble(Base):
    __tablename__ = 'scrobble'

    id = Column(Integer, primary_key=True)
    time = Column(DateTime())
    loved = Column(Boolean, default=False)
    track_id = Column(Integer, ForeignKey('track.id'))
    scrobble_info_id = Column(Integer, ForeignKey('scrobble_info.id'))

    track = relationship('Track', backref=backref('scrobbles', order_by=id))
    scrobble_info = relationship(
        'ScrobbleInfo', backref=backref('scrobbles', order_by=id))


class ArtistCorrection(Base):
    __tablename__ = 'artist_correction'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    artist_id = Column(Integer, ForeignKey('artist.id'))

    @hybrid_property
    def name_insensitive(self):
        return self.name.lower()

    @name_insensitive.comparator
    def name_insensitive(cls):
        return CaseInsensitiveComparator(cls.name)


class AlbumCorrection(Base):
    __tablename__ = 'album_correction'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    album_id = Column(Integer, ForeignKey('album.id'))

    album = relationship('Album', backref=backref('corrections', order_by=id))

    @hybrid_property
    def name_insensitive(self):
        return self.name.lower()

    @name_insensitive.comparator
    def name_insensitive(cls):
        return CaseInsensitiveComparator(cls.name)
