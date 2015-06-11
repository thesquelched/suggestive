from suggestive.lastfm import LastFM
from suggestive.model import (
    Artist, ArtistCorrection, Album, Scrobble, Session, Base, Track,
    ScrobbleInfo, LastfmTrackInfo)
from suggestive.util import partition

from pylastfm import LastfmError
import logging
from mpd import MPDClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import subqueryload
from datetime import datetime, timedelta
from collections import defaultdict
from itertools import chain
from os.path import basename, dirname
from contextlib import contextmanager
from difflib import get_close_matches
from mpd import MPDError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


######################################################################
# Helper functions
######################################################################

def mpd_retry(func):
    """
    Decorator that reconnects MPD client if the connection is lost
    """
    def wrapper(self, *args, **kwArgs):
        try:
            return func(self, *args, **kwArgs)
        except (MPDError, OSError) as ex:
            logger.warning('Detect MPD connection error; reconnecting...')
            logger.debug(ex)
            self._mpd = initialize_mpd(self.conf)
            return func(self, *args, **kwArgs)
    return wrapper


@contextmanager
def session_scope(conf, commit=True):
    """
    Context manager that yields an SQLAlchemy session object that automatically
    commits/rolls back upon completion, depending on whether or not an
    exception was encountered
    """
    session = initialize_sqlalchemy(conf)
    try:
        yield session
        if commit:
            session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


def get(data, keys, default=None):
    """
    For a nested hash, return the result of evaluating
    data[key_1][key_2]...[key_n]
    """
    if not keys:
        return data

    if not isinstance(data, dict):
        raise TypeError('not a dictionary')

    key, rest = keys[0], keys[1:]
    if key not in data:
        return default

    return get(data[key], rest, default=default)


def last_updated(session):
    """Return the timestamp of the last loaded scrobble"""
    return session.query(func.max(Scrobble.time)).scalar()


def sqlalchemy_url(config):
    """
    Return the SQLAlchemy query string corresponding to the suggestive database
    """
    return 'sqlite:///{}'.format(config.database())


def earliest_scrobble(session):
    """
    Return the timestamp for the earliest loaded scrobble
    """
    return session.query(func.min(Scrobble.time)).scalar()


def get_playlist_track(session, config, index):
    """
    Get the database Track object corresponding to the given index in the
    current playlist
    """
    mpd = initialize_mpd(config)

    tracks_info = mpd.playlistinfo(index)
    if tracks_info:
        info = tracks_info[0]
        return session.query(Track).\
            filter_by(filename=info['file']).\
            first()
    else:
        return None


def database_track_from_mpd(conf, track_info):
    """
    Return the database Track object corresponding to track info from MPD
    """
    tracks = database_tracks_from_mpd(conf, [track_info])
    return tracks[0] if tracks else None


def database_tracks_from_mpd(conf, tracks_info):
    """
    Return the database Track object corresponding to track info from MPD
    """
    with session_scope(conf, commit=False) as session:
        filenames = [info['file'] for info in tracks_info]
        db_tracks = session.query(Track).\
            options(
                subqueryload(Track.album),
                subqueryload(Track.artist),
                subqueryload(Track.lastfm_info)
            ).\
            filter(Track.filename.in_(filenames)).\
            all()

        tracks_by_filename = {t.filename: t for t in db_tracks}
        return [tracks_by_filename[info['file']] for info in tracks_info]


def get_scrobbles(conf, limit, offset=None):
    """
    Get the specified number of scrobbles with an optional offset
    """
    if not limit:
        return []

    with session_scope(conf, commit=False) as session:
        query = session.query(Scrobble).\
            join(Track).\
            options(
                subqueryload('track').subqueryload('*'),
            ).\
            order_by(Scrobble.time.desc()).\
            limit(limit)

        if offset is not None:
            query = query.offset(offset)

        return query.all()


def get_album_tracks(conf, album):
    with session_scope(conf, commit=False) as session:
        return session.query(Track).\
            options(
                subqueryload(Track.album),
                subqueryload(Track.artist),
                subqueryload(Track.lastfm_info)
            ).\
            filter(Track.album_id == album.id).\
            all()


######################################################################
# Loader Classes
######################################################################

class ScrobbleLoader(object):
    """
    Loads scrobbles from LastFM and attempts to correlate them with tracks
    already in the suggestive database
    """

    def __init__(self, lastfm, config):
        self.lastfm = lastfm
        self.user = config.lastfm_user
        self.retention = config.scrobble_retention()

    @classmethod
    def check_duplicates(cls, session):
        logger.debug('Checking for duplicate scrobbles')

        return session.query(Scrobble).\
            group_by(Scrobble.time, Scrobble.scrobble_info_id).\
            having(func.min(Scrobble.id) != func.max(Scrobble.id)).\
            count()

    @classmethod
    def delete_duplicates(cls, session):
        n_duplicates = cls.check_duplicates(session)
        if not n_duplicates:
            return

        ids = session.query(func.min(Scrobble.id).label('scrobble_id')).\
            group_by(Scrobble.time, Scrobble.scrobble_info_id).\
            subquery('ids')

        duplicates = session.query(Scrobble).\
            outerjoin(ids, ids.c.scrobble_id == Scrobble.id).\
            filter(ids.c.scrobble_id.is_(None)).\
            all()

        # The two duplicate check queries should match
        assert len(duplicates) == n_duplicates

        logger.info('Deleting {} duplicate scrobbles'.format(n_duplicates))

        for item in duplicates:
            session.delete(item)

    def scrobble_info(self, session, artist, album, track):
        """
        Return for scrobble information for the given track. If none is found,
        insert and return a new scrobble record
        """

        db_scrobble_info = session.query(ScrobbleInfo).\
            filter(
                ScrobbleInfo.title_insensitive == track,
                ScrobbleInfo.artist_insensitive == artist,
                ScrobbleInfo.album_insensitive == album).\
            first()

        if not db_scrobble_info:
            db_scrobble_info = ScrobbleInfo(
                title=track,
                artist=artist,
                album=album
            )
            session.add(db_scrobble_info)

        return db_scrobble_info

    def db_scrobble(self, session, when, db_scrobble_info):
        return session.query(Scrobble).\
            filter(
                Scrobble.time == when,
                Scrobble.scrobble_info == db_scrobble_info).\
            first()

    def load_scrobble(self, session, track):
        """
        Load a raw scrobble from the LastFM API
        """
        if not (track.artist_name and track.album_name and track.name and
                track.date):
            logger.debug('Invalid scrobble: %s - %s - %s @ %s',
                         track.artist_name, track.album_name, track.name,
                         track.date)
            return

        db_scrobble_info = self.scrobble_info(session, track.artist_name,
                                              track.album_name, track.name)
        scrobble = self.db_scrobble(session, track.date, db_scrobble_info)
        if scrobble is None:
            scrobble = Scrobble(time=track.date)
            db_scrobble_info.scrobbles.append(scrobble)
            session.add(scrobble)

        if scrobble.track:
            return

        db_track = session.query(Track).\
            join(Track.artist).\
            join(Track.album).\
            filter(
                Artist.name_insensitive == track.artist_name,
                Album.name_insensitive == track.album_name,
                Track.name_insensitive == track.name).\
            first()

        if db_track:
            db_track.scrobbles.append(scrobble)

    def load_recent_scrobbles(self, session):
        """
        Load scrobbles that were added since the last check
        """
        start = last_updated(session)
        if not start:
            start = datetime.now() - timedelta(self.retention)

        logger.info('Get scrobbles since %s',
                    start.strftime('%Y-%m-%d %H:%M'))

        return self.load_scrobbles(session, start=start)

    def load_scrobbles(self, session, start=None, end=None):
        """
        Load scrobbles that took place between the start and end dates
        """
        n_scrobbles = 0
        for item in self.lastfm.scrobbles(self.user, start=start, end=end):
            self.load_scrobble(session, item)
            n_scrobbles += 1

        logger.debug('Checking for duplicate scrobbles')
        self.delete_duplicates(session)

        return n_scrobbles

    def load_scrobbles_from_list(self, session, scrobbles):
        """
        Load scrobbles from a list generated by the LastFM API
        """
        if not len(scrobbles):
            return 0

        first = next(scrobbles)
        self.load_scrobble(session, first)

        track = None  # Necessary if there was only one scrobble total
        for track in scrobbles:
            self.load_scrobble(session, track)

        last = track or first
        logger.info('Loaded %d scrobbles from %s to %s'.format(
            len(scrobbles), first.date, last.date))

        return len(scrobbles)


class MpdLoader(object):

    """
    Synchronizes the MPD and suggestive databases
    """

    def __init__(self, mpd):
        self.mpd = mpd

    def load_track(self, session, db_artist, db_album, info):
        """
        Atempt to load a track into the suggestive database
        """
        filename = info['file']
        if not session.query(Track).filter_by(filename=filename).first():
            title = info.get('title', basename(filename))

            db_track = Track(
                name=title,
                filename=filename,
            )
            db_album.tracks.append(db_track)
            db_artist.tracks.append(db_track)
            session.add(db_track)

    def load_artist_albums(self, session, db_artist, albums):
        """
        Load albums from a given artist
        """
        for album, info_list in albums.items():
            # ignore missing albums
            if not album:
                continue

            logger.debug("Loading {} tracks from '{} - {}'".format(
                len(info_list), db_artist.name, album))

            db_album = session.query(Album).\
                filter(Album.name_insensitive == album).\
                filter(Album.artist == db_artist).\
                first()
            if not db_album:
                db_album = Album(name=album)
                db_artist.albums.append(db_album)
                session.add(db_album)

            for info in info_list:
                self.load_track(session, db_artist, db_album, info)

    def load_by_artist_album(self, session, by_artist_album):
        """
        Load albums from a dict of artist-albums pairs
        """
        for artist, albums in by_artist_album.items():
            # ignore missing artists
            if not artist:
                logger.error('No artist found')
                continue

            logger.debug("Loading {} albums from artist '{}'".format(
                len(albums), artist))

            db_artist = session.query(Artist).filter_by(
                name_insensitive=artist).first()
            if not db_artist:
                db_artist = Artist(name=artist)
                session.add(db_artist)

            self.load_artist_albums(session, db_artist, albums)

    def delete_orphaned(self, session, deleted):
        """
        Deleted any tracks that are in the suggestive database, but not in MPD
        """
        if deleted:
            logger.info('Deleting {} files from DB that do not exist in '
                        'MPD library'.format(len(deleted)))
            for tracks in partition(deleted, 100):
                tracks_to_delete = session.query(Track).\
                    filter(Track.filename.in_(tracks)).\
                    all()

                for track in tracks_to_delete:
                    session.delete(track)

        info_to_delete = session.query(LastfmTrackInfo).\
            filter(LastfmTrackInfo.track_id.is_(None)).\
            all()
        logger.debug('Found {} orphaned LastfmTrackInfo objects'.format(
            len(info_to_delete)))

        for info in info_to_delete:
            session.delete(info)

    def delete_empty_albums(self, session):
        empty = session.query(Album).\
            outerjoin(Track).\
            group_by(Album.id).\
            having(func.count(Track.id) == 0).\
            all()

        logger.info('Found {} albums with no tracks; deleting'.format(
            len(empty)))

        for album in empty:
            session.delete(album)

        logger.debug('Deleted {} empty albums'.format(len(empty)))

    def check_duplicates(self, session):
        """
        Check for albums with duplicate tracks
        """
        albums_with_dups = session.query(Album).\
            join(Track, Track.album_id == Album.id).\
            group_by(Album.name, Track.name).\
            having(func.count(Track.id) > 1).\
            all()

        logger.info('Found {} albums with duplicate tracks'.format(
            len(albums_with_dups)))

        for album in albums_with_dups:
            mpd_info = self.mpd.find('album', album.name)
            dirs = set(dirname(info['file']) for info in mpd_info)

            if len(dirs) > 1:
                logger.warn(
                    "Album '{} - {}' contains tracks in multiple "
                    "directories: {}".format(
                        album.artist.name, album.name, ', '.join(dirs)))

    def segregate_track_info(self, missing_info):
        """
        Segregate a list of tracks from MPD into a nested dict with
        artist -> album -> track
        """
        by_artist = defaultdict(list)
        for info in missing_info:
            artist = info.get('albumartist', info.get('artist'))
            if isinstance(artist, (list, tuple)):
                artist = artist[0]

            by_artist[artist].append(info)

        by_artist_album = defaultdict(lambda: defaultdict(list))
        for artist, info_list in by_artist.items():
            for info in info_list:
                by_artist_album[artist][info.get('album')].append(info)

        for artist, by_album in by_artist_album.items():
            for album, tracks in by_album.items():
                track_txt = 'Tracks:\n  {}'.format(
                    '\n  '.join(info['file'] for info in tracks))
                logger.debug('Tracks for {} - {}:\n  '.format(
                    artist, album, track_txt))

        return by_artist_album

    def load(self, session):
        """
        Synchronize MPD and suggestive databases
        """
        files_in_mpd = set(self.mpd.list('file'))
        files_in_db = set(item.filename for item in session.query(
            Track.filename).all())

        self.delete_orphaned(session, files_in_db - files_in_mpd)

        missing = files_in_mpd - files_in_db
        if missing:
            logger.info('Found {} files in mpd library that are missing '
                        'from suggestive database'.format(len(missing)))
            logger.debug('Missing files:\n  {}'.format(
                '\n  '.join(missing)))
            missing_info = list(
                chain.from_iterable(self.mpd.listallinfo(path)
                                    for path in missing))

            by_artist_album = self.segregate_track_info(missing_info)
            self.load_by_artist_album(session, by_artist_album)

        self.check_duplicates(session)
        self.delete_empty_albums(session)


class TrackInfoLoader(object):

    """
    Synchronizes database with LastFM track information, e.g. loved and banned
    """

    def __init__(self, lastfm, config):
        self.lastfm = lastfm
        self.user = config.lastfm_user

    def update_track_info(self, session, db_track, loved, banned):
        """
        Attempt to update the loved/banned status of a track. If the track does
        not have a corresponding LastFM info record, insert that record into
        the database
        """
        logger.debug('update_track_info: {}, {}, {}'.format(
            db_track.name, loved, banned))
        db_track_info = db_track.lastfm_info
        if not db_track_info:
            logger.debug('New track info')
            db_track_info = LastfmTrackInfo()
            db_track.lastfm_info = db_track_info
            session.add(db_track_info)

        db_track_info.loved = loved
        db_track_info.banned = banned

    def find_track(self, session, artist, track):
        """
        Find a database record for a track
        """
        return session.query(Track).\
            join(Artist).\
            filter(
                Track.name_insensitive == track,
                Artist.name_insensitive == artist).\
            first()

    def find_artist(self, session, artist):
        """
        Find a record for an artist
        """
        return session.query(Artist).\
            filter(Artist.name_insensitive == artist).\
            first()

    def find_closest_track(self, session, db_artist, track):
        """
        If a track has no exact duplicate in the database, look for the one
        that most likely matches
        """
        logger.debug('Looking for closest track for artist {}'.format(
            db_artist.name))
        matches = get_close_matches(
            track, [t.name for t in db_artist.tracks])
        if matches:
            logger.debug('Track {} matches: {}'.format(
                track, matches))
            for match in matches:
                db_track = self.find_track(
                    session, db_artist.name, match)
                if db_track:
                    return db_track
        else:
            logger.debug('Track {} had no matches'.format(track))

    def db_artists_from_lastfm(self, session, artist_names, artist):
        """
        Generator that yields the artist database objects corresponding to
        LastFM API track information
        """
        db_artist = self.find_artist(session, artist)
        if db_artist:
            yield db_artist
            return

        artist_matches = get_close_matches(artist, artist_names)
        if artist_matches:
            logger.debug("Artist '{}' matches: {}".format(
                artist, artist_matches))
            for match in artist_matches:
                db_artist = self.find_artist(
                    session, match)
                if db_artist:
                    yield db_artist

    def db_track_from_lastfm(self, session, artist_names, artist, track):
        """
        Generator that yields the track database objects corresponding to
        LastFM API track information
        """
        db_track = self.find_track(session, artist, track)
        if db_track:
            return db_track

        db_artists = self.db_artists_from_lastfm(
            session, artist_names, artist)

        if db_artists:
            for db_artist in db_artists:
                db_track = self.find_closest_track(
                    session, db_artist, track)
                if db_track:
                    return db_track

    def load_track_info(self, session, artist, loved_tracks, banned_tracks):
        """
        Load loved/banned tracks into the database
        """
        artist_names = [a.name for a in session.query(Artist).all()]
        all_tracks = loved_tracks.union(banned_tracks)

        for track in all_tracks:
            db_track = self.db_track_from_lastfm(
                session, artist_names, artist, track)

            if db_track:
                self.update_track_info(
                    session,
                    db_track,
                    track in loved_tracks,
                    track in banned_tracks
                )
            else:
                logger.error('Could not find database entry for LastFM item: '
                             '{} - {}'.format(artist, track))

    def get_loved_tracks(self):
        """
        Query LastFM for a list of loved tracks
        """
        loved_tracks = defaultdict(set)

        for track in self.lastfm.loved_tracks(self.user):
            if not (track.name and track.artist_name):
                logger.error('Malformed LastFM loved info: %s - %s',
                             track.artist_name, track.name)
                continue
            loved_tracks[track.artist_name].add(track.name)

        return loved_tracks

    def get_banned_tracks(self):
        """
        Query LastFM for a list of banned tracks
        """
        banned_tracks = defaultdict(set)

        for track in self.lastfm.banned_tracks(self.user):
            if not (track.name and track.artist_name):
                logger.error('Malformed LastFM banned info: %s - %s',
                             track.artist_name, track.name)
                continue
            banned_tracks[track.artist_name].add(track.name)

        return banned_tracks

    def load(self, session):
        """
        Synchronize LastFM track information with suggestive database
        """
        loved_tracks = self.get_loved_tracks()
        banned_tracks = self.get_banned_tracks()

        all_artists = set(loved_tracks.keys()).union(set(banned_tracks.keys()))

        for artist in all_artists:
            self.load_track_info(
                session,
                artist,
                loved_tracks[artist],
                banned_tracks[artist]
            )


######################################################################
# Initialization functions
######################################################################

def initialize_sqlalchemy(config, echo=False):
    """
    Return a SQLAlchemy session object. Also create database if it doesn't
    already exist
    """
    path = sqlalchemy_url(config)
    engine = create_engine(path, echo=bool(echo))
    Session.configure(bind=engine)

    Base.metadata.create_all(engine)

    return Session()


def initialize_mpd(config):
    """
    Return a MPD client connection
    """
    host, port = config.mpd()

    client = MPDClient()
    client.connect(host, port)

    return client


def initialize_lastfm(config):
    """
    Return a LastFM client connection
    """
    return LastFM(config)


def correct_artist(name, lastfm):
    """
    Deprecated

    Use the LastFM corrections database to attempt to correct an artist name
    """
    logger.info('Attempting to find a correction for {}'.format(name))

    resp = lastfm.query('artist.getCorrection', artist=name)
    if 'corrections' in resp and isinstance(resp['corrections'], dict):
        correct = resp['corrections']['correction']
        if 'artist' in correct:
            info = correct['artist']
            artist = Artist(
                name=info['name'],
                mbid=info.get('mbid'),
            )
            corrected = ArtistCorrection(name=name)

            logger.info("Corrected '{}' to '{}'".format(name, artist.name))
            return (artist, corrected)

    artist = Artist(name=name)
    return (artist, None)


######################################################################
# Loader helper functions
######################################################################

def update_mpd(config):
    """
    Synchronize the database with MPD via the MpdLoader
    """
    logger.info('Updating database from mpd')

    with session_scope(config) as session:
        artists_start = session.query(Artist).count()
        albums_start = session.query(Album).count()
        tracks_start = session.query(Track).count()

        mpdclient = initialize_mpd(config)
        mpd_loader = MpdLoader(mpdclient)
        mpd_loader.load(session)

        session.commit()

        new_artists = session.query(Artist).count() - artists_start
        new_albums = session.query(Album).count() - albums_start
        new_tracks = session.query(Track).count() - tracks_start

        logger.info('Inserted {} artists'.format(new_artists))
        logger.info('Inserted {} albums'.format(new_albums))
        logger.info('Inserted {} tracks'.format(new_tracks))


def update_lastfm(config):
    """
    Synchronize the database with LastFM via ScrobbleLoader and TrackInfoLoader
    """
    logger.info('Update database from last.fm')

    with session_scope(config) as session:
        scrobbles_start = session.query(Scrobble).count()

        lastfm = initialize_lastfm(config)
        scrobble_loader = ScrobbleLoader(lastfm, config)
        scrobble_loader.load_recent_scrobbles(session)

        new_scrobbles = session.query(Scrobble).count() - scrobbles_start

        logger.info('Inserted {} scrobbles'.format(new_scrobbles))

        info_loader = TrackInfoLoader(lastfm, config)
        info_loader.load(session)

        session.commit()


def update_database(config):
    """
    Synchronize the database with MPD and LastFM
    """
    update_mpd(config)

    try:
        update_lastfm(config)
    except LastfmError as err:
        logger.error('Could not contact LastFM server during database update')
        logger.debug(err)


def load_scrobble_batch(session, lastfm, conf, batch):
    """
    Load a batch of scrobbles from the LastFM API via ScrobbleLoader
    """
    if not batch:
        return 0

    loader = ScrobbleLoader(lastfm, conf)

    return loader.load_scrobbles_from_list(session, batch)


######################################################################
# Action helpers
######################################################################

def get_db_track(conf, track_id):
    with session_scope(conf, commit=False) as session:
        return session.query(Track).\
            options(
                subqueryload(Track.album),
                subqueryload(Track.artist),
                subqueryload(Track.lastfm_info)
            ).\
            get(track_id)


def lastfm_love(lastfm, track, loved):
    method = lastfm.love_track if loved else lastfm.unlove_track
    success = method(track.artist.name, track.name)
    logger.info("Marking '{} - {}' {}... {}".format(
        track.artist.name,
        track.name,
        'loved' if loved else 'unloved',
        'successful' if success else 'failed'))

    if not success:
        logger.warning('Unable to mark track {}'.format(
            'loved' if loved else 'unloved'))


def db_track_love(conf, track, loved=True):
    """
    Mark the track loved (or unloved), then synchronize with LastFM
    """
    with session_scope(conf, commit=True) as session:
        db_track = session.query(Track).get(track.id)

        db_track_info = db_track.lastfm_info
        if db_track_info is None:
            db_track_info = LastfmTrackInfo()
            db_track.lastfm_info = db_track_info
            session.add(db_track_info)

        # Mark loved in DB
        db_track_info.loved = bool(loved)
