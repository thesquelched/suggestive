from suggestive.lastfm import LastFM, LastfmError
from suggestive.model import (
    Artist, ArtistCorrection, Album, Scrobble, Session, Base, Track,
    ScrobbleInfo, LastfmTrackInfo)

import mpd
import logging
from sqlalchemy import create_engine, func
from datetime import datetime, timedelta
from collections import defaultdict
from itertools import chain
from os.path import basename, dirname
from contextlib import contextmanager
from difflib import get_close_matches

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


@contextmanager
def session_scope(conf, commit=True):
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
    if not keys:
        return data

    if not isinstance(data, dict):
        raise TypeError('not a dictionary')

    key, rest = keys[0], keys[1:]
    if key not in data:
        return default

    return get(data[key], rest, default=default)


class ScrobbleLoader(object):

    def __init__(self, lastfm, config):
        self.lastfm = lastfm
        self.user = config.lastfm_user()
        self.retention = config.scrobble_retention()

    def scrobble_info(self, session, artist, album, track):

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

    def load_scrobble(self, session, item):
        if not ('artist' in item and 'album' in item and 'name' in item and
                'date' in item):
            return

        artist = item['artist'].get('name')
        album = item['album'].get('#text') or item['album'].get('name')
        track = item['name']

        db_scrobble_info = self.scrobble_info(session, artist, album, track)

        when = datetime.fromtimestamp(int(item['date']['uts']))
        scrobble = Scrobble(time=when)

        db_scrobble_info.scrobbles.append(scrobble)
        session.add(scrobble)

        db_track = session.query(Track).\
            join(Track.artist).\
            join(Track.album).\
            filter(
                Artist.name_insensitive == artist,
                Album.name_insensitive == album,
                Track.name_insensitive == track).\
            first()

        if db_track:
            db_track.scrobbles.append(scrobble)

    def load_recent_scrobbles(self, session):
        start = last_updated(session)
        if not start:
            start = datetime.now() - timedelta(self.retention)

        logger.info('Get scrobbles since {}'.format(
            start.strftime('%Y-%m-%d %H:%M')))

        return self.load_scrobbles(session, start=start)

    def load_scrobbles(self, session, start=None, end=None):
        n_scrobbles = 0
        for item in self.lastfm.scrobbles(self.user, start=start, end=end):
            self.load_scrobble(session, item)
            n_scrobbles += 1

        return n_scrobbles

    def load_scrobbles_from_list(self, session, scrobble_list):
        scrobble_list = list(scrobble_list)
        first, last = scrobble_list[0], scrobble_list[-1]

        logger.info('Loading {} scrobbles from {} to {}'.format(
            len(scrobble_list), first['date']['#text'], last['date']['#text']))

        n_scrobbles = 0
        for item in scrobble_list:
            self.load_scrobble(session, item)
            n_scrobbles += 1

        return n_scrobbles


class MpdLoader(object):

    def __init__(self, mpd):
        self.mpd = mpd

    def load_track(self, session, db_artist, db_album, info):
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
        if deleted:
            logger.info('Deleting {} files from DB that do not exist in '
                        'MPD library'.format(len(deleted)))
            tracks_to_delete = session.query(Track).\
                filter(Track.filename.in_(deleted)).\
                all()

            for track in tracks_to_delete:
                session.delete(track)

        info_to_delete = session.query(LastfmTrackInfo).\
            filter(LastfmTrackInfo.track == None).\
            all()
        logger.debug('Found {} orphaned LastfmTrackInfo objects'.format(
            len(info_to_delete)))

        for info in info_to_delete:
            session.delete(info)

    def remove_duplicates(self, session):
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

        self.remove_duplicates(session)


class TrackInfoLoader(object):

    def __init__(self, lastfm, config):
        self.lastfm = lastfm
        self.user = config.lastfm_user()

    def update_track_info(self, session, db_track, loved, banned):
        logger.debug('update_track_info: {}, {}, {}'.format(
            db_track.name, loved, banned))
        db_track_info = db_track.lastfm_info
        if not db_track_info:
            logger.debug('New track info')
            db_track_info = LastfmTrackInfo()
            db_track.lastfm_info = db_track_info
            session.add(db_track_info)
        else:
            logger.debug('Already had: {} {}'.format(
                db_track_info.loved, db_track_info.banned))

        db_track_info.loved = loved
        db_track_info.banned = banned

    def find_track(self, session, artist, track):
        return session.query(Track).\
            join(Artist).\
            filter(
                Track.name_insensitive == track,
                Artist.name_insensitive == artist).\
            first()

    def find_artist(self, session, artist):
        return session.query(Artist).\
            filter(Artist.name_insensitive == artist).\
            first()

    def find_closest_track(self, session, db_artist, track):
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

    def get_loved_tracks(self, session):
        loved_track_info = list(self.lastfm.loved_tracks(self.user))
        loved_tracks = defaultdict(set)

        for info in loved_track_info:
            if not('name' in info and 'artist' in info
                   and 'name' in info['artist']):
                logger.error('Malformed LastFM loved info: {}'.format(info))
                continue
            loved_tracks[info['artist']['name']].add(info['name'])

        return loved_tracks

    def get_banned_tracks(self, session):
        banned_track_info = list(self.lastfm.banned_tracks(self.user))
        banned_tracks = defaultdict(set)

        for info in banned_track_info:
            if not('name' in info and 'artist' in info
                   and 'name' in info['artist']):
                logger.error('Malformed LastFM banned info: {}'.format(info))
                continue
            banned_tracks[info['artist']['name']].add(info['name'])

        return banned_tracks

    def load(self, session):
        loved_tracks = self.get_loved_tracks(session)
        banned_tracks = self.get_banned_tracks(session)

        all_artists = set(loved_tracks.keys()).union(set(banned_tracks.keys()))

        for artist in all_artists:
            self.load_track_info(
                session,
                artist,
                loved_tracks[artist],
                banned_tracks[artist]
            )


def sqlalchemy_url(config):
    return 'sqlite:///{}'.format(config.database())


def initialize_sqlalchemy(config, echo=False):
    path = sqlalchemy_url(config)
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
    return LastFM(
        config.lastfm_apikey(),
        config.lastfm_session_file(),
        api_secret=config.lastfm_secret_key(),
        log_responses=config.lastfm_log_responses(),
    )


def correct_artist(name, lastfm):
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


def last_updated(session):
    return session.query(func.max(Scrobble.time)).scalar()
    #if last_date:
    #    return int(mktime(last_date.timetuple()))
    #else:
    #    return None


def update_mpd(config):
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
    update_mpd(config)

    try:
        update_lastfm(config)
    except LastfmError as err:
        logger.error('Could not contact LastFM server during database update')
        logger.debug(err)


def earliest_scrobble(session):
    return session.query(func.min(Scrobble.time)).scalar()


def load_scrobble_batch(session, lastfm, conf, batch):
    if not batch:
        return 0

    loader = ScrobbleLoader(lastfm, conf)

    return loader.load_scrobbles_from_list(session, batch)


def set_track_loved(session, lastfm, track, loved=True):
    db_track_info = track.lastfm_info
    if db_track_info is None:
        db_track_info = LastfmTrackInfo()
        track.lastfm_info = db_track_info
        session.add(db_track_info)

    # Mark loved in DB
    db_track_info.loved = bool(loved)

    # Mark loved in LastFM
    method = lastfm.love_track if loved else lastfm.unlove_track
    success = method(track.artist.name, track.name)
    logger.info("Marking '{} - {}' {}... {}".format(
        track.artist.name,
        track.name,
        'loved' if loved else 'unloved',
        'successful' if success else 'failed'))
    return success


def set_track_unloved(session, lastfm, track):
    set_track_loved(session, lastfm, track, loved=False)


def get_playlist_track(session, config, index):
    mpd = initialize_mpd(config)

    tracks_info = mpd.playlistinfo(index)
    if tracks_info:
        info = tracks_info[0]
        return session.query(Track).\
            filter_by(filename=info['file']).\
            first()
    else:
        return None


def database_track_from_mpd(session, track_info):
    return session.query(Track).filter_by(filename=track_info['file']).first()

def get_scrobbles(session, limit, offset=None):
    if not limit:
        return []

    query = session.query(Scrobble).\
        order_by(Scrobble.time.desc()).\
        limit(limit)

    if offset is not None:
        query = query.offset(offset)

    return query.all()
