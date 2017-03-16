import logging
from collections import defaultdict, OrderedDict
from datetime import datetime, timedelta
from difflib import get_close_matches
from itertools import chain
from mpd import MPDClient
from mpd import MPDError
from os.path import basename, dirname
from pylastfm import LastfmError
from sqlalchemy import func
from sqlalchemy.orm import subqueryload

from suggestive.lastfm import LastFM
from suggestive.db.session import session_scope
from suggestive.db.model import (
    Artist, ArtistCorrection, Album, Scrobble, Track,
    ScrobbleInfo, LastfmTrackInfo)
from suggestive.util import partition


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


def get_unknown_track(info):
    """Create a mock Track for a MPD track not in the database"""
    filename = info['file']
    title = info.get('title', basename(filename))

    artist = Artist(name='Unknown')
    return Track(
        name=title,
        filename=filename,
        album=Album(name='Unknown', artist=artist),
        artist=artist,
    )


def database_tracks_from_mpd(conf, tracks_info):
    """
    Return the database Track object corresponding to track info from MPD
    """
    track_filenames = [info['file'] for info in tracks_info]
    info_by_filename = OrderedDict((info['file'], info)
                                   for info in tracks_info)

    def _get_db_tracks(session, chunk):
        return (session.query(Track).
                options(subqueryload(Track.album),
                        subqueryload(Track.artist),
                        subqueryload(Track.lastfm_info)).
                filter(Track.filename.in_(chunk)).
                all())

    with session_scope(conf, commit=False) as session:
        tracks_by_filename = {}
        missing = []

        chunk_size = 128
        for chunk in partition(info_by_filename.keys(), chunk_size):
            db_tracks = _get_db_tracks(session, chunk)
            by_filename = {t.filename: t for t in db_tracks}

            if len(db_tracks) != chunk_size:
                missing.extend((filename for filename in chunk
                                if filename not in by_filename))

            tracks_by_filename.update(by_filename)

        if missing:
            logger.info(
                'Updating database with %d missing track%s in playlist',
                len(missing), 's' if len(missing) > 1 else '')

            MpdLoader(conf).load_mpd_tracks(session, missing)
            for chunk in partition(missing, chunk_size):
                db_tracks = _get_db_tracks(session, chunk)
                by_filename = {t.filename: t for t in db_tracks}
                tracks_by_filename.update(by_filename)

        filename_and_info = ((filename, info_by_filename[filename])
                             for filename in track_filenames)
        return [tracks_by_filename.get(filename, get_unknown_track(info))
                for filename, info in filename_and_info]


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
        self.user = config.lastfm.user
        self.retention = config.lastfm.scrobble_days
        self._track_mapping = {}

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

        db_scrobble_info = (session.query(ScrobbleInfo)
                            .filter(ScrobbleInfo.title_insensitive == track,
                                    ScrobbleInfo.artist_insensitive == artist,
                                    ScrobbleInfo.album_insensitive == album)
                            .first())

        if not db_scrobble_info:
            logger.debug('Creating scrobble info for %s - %s - %s',
                         artist, album, track)

            db_scrobble_info = ScrobbleInfo(
                title=track,
                artist=artist,
                album=album
            )
            session.add(db_scrobble_info)

        return db_scrobble_info

    def db_scrobble(self, session, when, db_scrobble_info):
        scrobble = (session.query(Scrobble)
                    .filter(Scrobble.time == when, Scrobble.scrobble_info == db_scrobble_info)
                    .first())
        if not scrobble:
            logger.debug('Creating scrobble: %s - %s - %s @ %s',
                         db_scrobble_info.artist, db_scrobble_info.album, db_scrobble_info.title,
                         when)

            scrobble = Scrobble(time=when)
            db_scrobble_info.scrobbles.append(scrobble)
            session.add(scrobble)

        return scrobble

    def load_scrobble(self, session, fm_track):
        """
        Load a raw scrobble from the LastFM API
        """
        if not (fm_track.artist_name and fm_track.album_name and fm_track.name and
                fm_track.date):
            logger.debug('Invalid scrobble: %s - %s - %s @ %s',
                         fm_track.artist_name, fm_track.album_name, fm_track.name,
                         fm_track.date)
            return

        closest_track = self.find_closest_track(session, fm_track)
        if closest_track:
            artist_name = closest_track.artist.name
            album_name = closest_track.album.name
            track_name = closest_track.name
        else:
            artist_name = fm_track.artist_name
            album_name = fm_track.album_name
            track_name = fm_track.name

        db_scrobble_info = self.scrobble_info(session, artist_name, album_name, track_name)
        scrobble = self.db_scrobble(session, fm_track.date, db_scrobble_info)
        if scrobble is None:
            logger.debug('Creating scrobble: %s - %s - %s @ %s',
                         artist_name, album_name, track_name, fm_track.date)

            scrobble = Scrobble(time=fm_track.date)
            db_scrobble_info.scrobbles.append(scrobble)
            session.add(scrobble)

        # If this scrobble is already assigned to a track in the database, we know it's already
        # been loaded and can therefore ignore it
        if scrobble.track:
            return

        if closest_track:
            closest_track.scrobbles.append(scrobble)

    def track_mapping(self, session):
        """
        Return dict in which the values are Track object and the keys are strings in the form of
        'artist\x01album\x01track'.  The result is cached.
        """
        if not self._track_mapping:
            result = (session.query(Track, Artist.name, Album.name, Track.name)
                      .filter(Artist.id == Track.artist_id, Album.id == Track.album_id)
                      .all())
            self._track_mapping = OrderedDict(
                ('\x01'.join(pieces[1:]), pieces[0]) for pieces in result
                if not any(piece is None for piece in pieces))

        return self._track_mapping

    def find_closest_track(self, session, track):
        exact_match = (session.query(Track)
                       .join(Track.artist)
                       .join(Track.album)
                       .filter(
                           Artist.name_insensitive == track.artist_name,
                           Album.name_insensitive == track.album_name,
                           Track.name_insensitive == track.name)
                       .first())
        if exact_match:
            return exact_match

        mapping = self.track_mapping(session)
        track_string = '\x01'.join((track.artist_name, track.album_name, track.name))

        closest_matches = get_close_matches(track_string, mapping.keys(), n=20, cutoff=0.8)
        if not closest_matches:
            return None

        closest_track_mapping = OrderedDict((mapping[match].name, mapping[match])
                                            for match in closest_matches)
        closest_track_name = get_close_matches(track.name, closest_track_mapping.keys(), n=1)
        if not closest_track_name:
            return None

        return closest_track_mapping[closest_track_name[0]]

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
        if not scrobbles:
            return 0

        n_scrobbles = len(scrobbles)

        first = scrobbles[0]
        self.load_scrobble(session, first)

        track = None  # Necessary if there was only one scrobble total
        for track in scrobbles[1:]:
            self.load_scrobble(session, track)

        last = track or first
        logger.info('Loaded %d scrobbles from %s to %s', n_scrobbles, first.date, last.date)

        return n_scrobbles


class MpdLoader(object):

    """
    Synchronizes the MPD and suggestive databases
    """

    def __init__(self, conf):
        self._conf = conf
        self._mpd = initialize_mpd(conf)

    @property
    def mpd(self):
        return self._mpd

    @property
    def conf(self):
        return self._conf

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

            logger.debug("Loading %d tracks from '%s - %s'",
                         len(info_list), db_artist.name, album)

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

            logger.debug("Loading %d albums from artist '%s'", len(albums), artist)

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
            logger.info('Deleting %d files from DB that do not exist in MPD library', len(deleted))
            for tracks in partition(deleted, 100):
                tracks_to_delete = session.query(Track).\
                    filter(Track.filename.in_(tracks)).\
                    all()

                for track in tracks_to_delete:
                    session.delete(track)

        info_to_delete = session.query(LastfmTrackInfo).\
            filter(LastfmTrackInfo.track_id.is_(None)).\
            all()
        logger.debug('Found %d orphaned LastfmTrackInfo objects', len(info_to_delete))

        for info in info_to_delete:
            session.delete(info)

    def delete_empty_albums(self, session):
        empty = session.query(Album).\
            outerjoin(Track).\
            group_by(Album.id).\
            having(func.count(Track.id) == 0).\
            all()

        logger.info('Found %d albums with no tracks; deleting', len(empty))

        for album in empty:
            session.delete(album)

        logger.debug('Deleted %d empty albums', len(empty))

    @mpd_retry
    def check_duplicates(self, session):
        """
        Check for albums with duplicate tracks
        """
        albums_with_dups = session.query(Album).\
            join(Track, Track.album_id == Album.id).\
            group_by(Album.name, Track.name).\
            having(func.count(Track.id) > 1).\
            all()

        logger.info('Found %d albums with duplicate tracks', len(albums_with_dups))

        for album in albums_with_dups:
            mpd_info = self.mpd.find('album', album.name)
            dirs = set(dirname(info['file']) for info in mpd_info)

            if len(dirs) > 1:
                logger.warn("Album '%s - %s' contains tracks in multiple directories: %s",
                            album.artist.name, album.name, ', '.join(dirs))

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
                logger.debug('Tracks for %s - %s:\n  %s', artist, album, track_txt)

        return by_artist_album

    @mpd_retry
    def _list_mpd_files(self):
        return self.mpd.list('file')

    @mpd_retry
    def _mpd_info(self, path):
        return self.mpd.listallinfo(path)

    def load_mpd_tracks(self, session, filenames):
        if not filenames:
            return

        missing_info = list(
            chain.from_iterable(self._mpd_info(path) for path in filenames))

        by_artist_album = self.segregate_track_info(missing_info)
        self.load_by_artist_album(session, by_artist_album)

    def load(self, session):
        """
        Synchronize MPD and suggestive databases
        """
        files_in_mpd = set(self._list_mpd_files())
        files_in_db = set(item.filename for item in session.query(
            Track.filename).all())

        self.delete_orphaned(session, files_in_db - files_in_mpd)

        missing = files_in_mpd - files_in_db
        if missing:
            logger.info('Found %d files in mpd library that are missing from suggestive database',
                        len(missing))
            logger.debug('Missing files:\n  %s', '\n  '.join(missing))
            self.load_mpd_tracks(session, missing)

        self.check_duplicates(session)
        self.delete_empty_albums(session)


class TrackInfoLoader(object):

    """
    Synchronizes database with LastFM track information, e.g. loved
    """

    def __init__(self, lastfm, config):
        self.lastfm = lastfm
        self.user = config.lastfm.user

    def update_track_info(self, session, db_track, loved):
        """
        Attempt to update the loved status of a track. If the track does
        not have a corresponding LastFM info record, insert that record into
        the database
        """
        logger.debug('update_track_info: %s, %s', db_track.name, loved)
        db_track_info = db_track.lastfm_info
        if not db_track_info:
            logger.debug('New track info')
            db_track_info = LastfmTrackInfo()
            db_track.lastfm_info = db_track_info
            session.add(db_track_info)

        db_track_info.loved = loved

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
        logger.debug('Looking for closest track for artist %s', db_artist.name)
        matches = get_close_matches(
            track, [t.name for t in db_artist.tracks])
        if matches:
            logger.debug('Track %s matches: %s', track, matches)
            for match in matches:
                db_track = self.find_track(
                    session, db_artist.name, match)
                if db_track:
                    return db_track
        else:
            logger.debug('Track %s had no matches', track)

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
            logger.debug("Artist '%s' matches: %s", artist, artist_matches)
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

    def load_track_info(self, session, artist, loved_tracks):
        """
        Load loved tracks into the database
        """
        artist_names = [a.name for a in session.query(Artist).all()]

        for track in loved_tracks:
            db_track = self.db_track_from_lastfm(
                session, artist_names, artist, track)

            if db_track:
                self.update_track_info(
                    session,
                    db_track,
                    track in loved_tracks,
                )
            else:
                logger.error('Could not find database entry for LastFM item: %s - %s',
                             artist, track)

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

    def load(self, session):
        """
        Synchronize LastFM track information with suggestive database
        """
        loved_tracks = self.get_loved_tracks()

        for artist, tracks in loved_tracks.items():
            self.load_track_info(
                session,
                artist,
                tracks,
            )


######################################################################
# Initialization functions
######################################################################

def initialize_mpd(config):
    """
    Return a MPD client connection
    """
    client = MPDClient()
    client.connect(config.mpd.host, config.mpd.port)

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
    logger.info('Attempting to find a correction for %s', name)

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

            logger.info("Corrected '%s' to '%s'", name, artist.name)
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

        mpd_loader = MpdLoader(config)
        mpd_loader.load(session)

        session.commit()

        new_artists = session.query(Artist).count() - artists_start
        new_albums = session.query(Album).count() - albums_start
        new_tracks = session.query(Track).count() - tracks_start

        logger.info('Inserted %d artists', new_artists)
        logger.info('Inserted %d albums', new_albums)
        logger.info('Inserted %d tracks', new_tracks)


def _update_lastfm(config, session):
    scrobbles_start = session.query(Scrobble).count()

    lastfm = initialize_lastfm(config)
    scrobble_loader = ScrobbleLoader(lastfm, config)
    scrobble_loader.load_recent_scrobbles(session)

    new_scrobbles = session.query(Scrobble).count() - scrobbles_start

    logger.info('Inserted %d scrobbles', new_scrobbles)

    info_loader = TrackInfoLoader(lastfm, config)
    info_loader.load(session)


def update_lastfm(config):
    """
    Synchronize the database with LastFM via ScrobbleLoader and TrackInfoLoader
    """
    logger.info('Update database from last.fm')

    with session_scope(config) as session:
        _update_lastfm(config, session)
        session.commit()


def update_database(config):
    """
    Synchronize the database with MPD and LastFM
    """
    update_mpd(config)

    try:
        update_lastfm(config)
    except LastfmError as exc:
        logger.error('Could not contact LastFM server during database update')
        logger.debug('Encountered exception', exc_info=exc)


def reinitialize_scrobbles(config):
    """
    Delete all existing database scrobbles and re-initialize from LastFM
    """
    with session_scope(config) as session:
        session.query(Scrobble).delete()
        session.query(ScrobbleInfo).delete()
        _update_lastfm(config, session)


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
    logger.info("Marking '%s - %s' %s... %s",
                track.artist.name,
                track.name,
                'loved' if loved else 'unloved',
                'successful' if success else 'failed')

    if not success:
        logger.warning('Unable to mark track %s', 'loved' if loved else 'unloved')


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


def db_album_ignore(conf, album, ignore=True):
    with session_scope(conf, commit=True) as session:
        db_album = session.query(Album).get(album.id)
        db_album.ignored = ignore
