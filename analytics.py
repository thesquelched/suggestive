import mstat
from model import Album, Track, Scrobble, LastfmTrackInfo
from sqlalchemy import func, Integer, distinct
import logging
from itertools import repeat
from collections import defaultdict
from operator import itemgetter
import re
import sys
from datetime import datetime


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Suggestion(object):

    def __init__(self, album):
        self.album = album
        #self.loved = [
        #    track for track in album.tracks
        #    if track.lastfm_info and track.lastfm_info.loved
        #]


def choose(N, k):
    if (k > N) or (N < 0) or (k < 0):
        return 0
    N, k = (int(N), int(k))
    top = N
    val = 1
    while (top > (N - k)):
        val *= top
        top -= 1
    n = 1
    while (n < k + 1):
        val /= n
        n += 1
    return val


class OrderDecorator(object):

    TRUTHY = (True, 'True', 'TRUE', 'true', 1, 'yes')
    NONE = (None, 'None', 'null', '')

    def __repr__(self):
        return '<{}()>'.format(self.__class__.__name__)

    def order(self, albums, session, mpd):
        raise NotImplementedError


class BaseOrder(OrderDecorator):

    """Initialize all albums with unity order"""

    def order(self, albums, session, mpd):
        return defaultdict(
            lambda: 1.0,
            zip(session.query(Album).all(), repeat(1.0))
        )


class AlbumFilter(OrderDecorator):
    def __init__(self, *name_pieces):
        name = ' '.join(name_pieces)
        self.name = name
        self.name_rgx = re.compile(name, re.I)

    def __repr__(self):
        return '<AlbumFilter({})>'.format(self.name)

    def order(self, albums, session, mpd):
        return {
            album: order for album, order in albums.items()
            if re.search(self.name_rgx, album.name) is not None
        }


class ArtistFilter(OrderDecorator):
    def __init__(self, *name_pieces):
        name = ' '.join(name_pieces)
        self.name = name
        self.name_rgx = re.compile(name, re.I)

    def __repr__(self):
        return '<ArtistFilter({})>'.format(self.name)

    def order(self, albums, session, mpd):
        return {
            album: order for album, order in albums.items()
            if re.search(self.name_rgx, album.artist.name) is not None
        }


class SortOrder(OrderDecorator):

    """Sort by 'Artist - Album'"""

    def __init__(self, ignore_artist_the=True):
        self.ignore_artist_the = bool(ignore_artist_the)

    def _format(self, album):
        artist = album.artist.name
        if self.ignore_artist_the and artist.lower().startswith('the '):
            artist = artist[4:] + ', ' + artist[:3]

        return '{} - {}'.format(artist, album.name)

    def order(self, albums, session, mpd):
        sorted_albums = sorted(albums, key=self._format, reverse=True)
        return {album: i for i, album in enumerate(sorted_albums, 1)}


class ModifiedOrder(OrderDecorator):

    """Sort by modified date"""

    FMT = '%Y-%m-%dT%H:%M:%SZ'

    @classmethod
    def get_date(cls, album, mpd):
        track_info = mpd.search('album', album.name)
        if not track_info:
            return None

        dates = [datetime.strptime(info['last-modified'], cls.FMT)
                 for info in track_info]
        return sorted(dates)[0]

    def order(self, albums, session, mpd):
        sorted_albums = sorted(
            albums,
            key=lambda album: self.get_date(album, mpd))
        return {album: i for i, album in enumerate(sorted_albums, 1)}


class BannedOrder(OrderDecorator):

    """Remove or demote albums with banned tracks"""

    def __init__(self, remove_banned=True):
        self.remove = remove_banned in self.TRUTHY

    def __repr__(self):
        return '<BannedOrder({})>'.format(self.remove)

    def order(self, albums, session, mpd):
        results = session.query(Album).\
            join(Track).\
            outerjoin(LastfmTrackInfo).\
            add_columns(func.count(Track.id),
                        func.sum(LastfmTrackInfo.banned, type_=Integer)).\
            group_by(Album.id).\
            all()

        neworder = defaultdict(lambda: 1.0, albums.items())

        for album, n_tracks, n_banned in results:
            if album not in neworder or n_tracks == 0:
                continue

            if n_banned and self.remove:
                del neworder[album]
            elif n_banned:
                # Banned albums are equally worthless
                neworder[album] *= 0.0

        return neworder


class FractionLovedOrder(OrderDecorator):

    """Order by fraction of tracks loved"""

    def __init__(self, penalize_unloved=False, **kwArgs):
        super(FractionLovedOrder, self).__init__()

        maximum = kwArgs.pop('max', None)
        minimum = kwArgs.pop('min', None)

        if kwArgs:
            arg = list(kwArgs.keys())[0]
            raise TypeError("FractionLovedOrder got an unexpected keyword "
                            "argument '{}'".format(arg))

        self.penalize = penalize_unloved

        if minimum in self.NONE:
            minimum = 0
        if maximum in self.NONE:
            maximum = 1

        try:
            minimum, maximum = float(minimum), float(maximum)
        except (TypeError, ValueError) as err:
            raise TypeError(*err.args)

        if minimum > maximum:
            minimum, maximum = maximum, minimum

        min_ = min(max(minimum, 0), 1)
        self.f_max = max(min(maximum, 1), min_)
        self.f_min = min(max(minimum, 0), self.f_max)

    def __repr__(self):
        return '<FractionLovedOrder({}, {}, {})>'.format(
            self.f_min, self.f_max, self.penalize)

    def order(self, albums, session, mpd):
        results = session.query(Album).\
            join(Track).\
            outerjoin(LastfmTrackInfo).\
            add_columns(func.count(Track.id),
                        func.sum(LastfmTrackInfo.loved, type_=Integer)).\
            group_by(Album.id).\
            all()

        neworder = defaultdict(lambda: 1.0, albums.items())

        for album, n_tracks, n_loved in results:
            if album not in neworder or n_tracks == 0:
                continue

            if n_loved is None:
                n_loved = 0

            f_loved = n_loved / n_tracks
            if not (self.f_min <= f_loved <= self.f_max):
                del neworder[album]
                continue

            neworder[album] *= self._order(n_loved, n_tracks)

        return neworder

    def _order(self, n_loved, n_tracks):
        f_loved = n_loved / n_tracks

        if n_loved > 0:
            return 1 + f_loved
        else:
            return 1.0 / n_tracks if self.penalize else 1.0


class PlaycountOrder(OrderDecorator):

    """Order items based on playcount/scrobbles"""

    def __init__(self, **kwArgs):
        maximum = kwArgs.pop('max', None)
        minimum = kwArgs.pop('min', None)

        if kwArgs:
            arg = list(kwArgs.keys())[0]
            raise TypeError("PlaycountOrder got an unexpected keyword "
                            "argument '{}'".format(arg))

        if minimum in self.NONE:
            minimum = 0
        if maximum in self.NONE:
            maximum = sys.maxsize

        try:
            minimum, maximum = float(minimum), float(maximum)
        except (TypeError, ValueError) as err:
            raise TypeError(*err.args)

        if minimum > maximum:
            minimum, maximum = maximum, minimum

        self.plays_min = max(0, minimum)
        self.plays_max = maximum

    def __repr__(self):
        return '<PlaycountOrder({}, {})>'.format(
            self.plays_min, self.plays_max)

    def order(self, albums, session, mpd):
        results = session.query(Album).\
            join(Track).\
            outerjoin(Scrobble).\
            add_columns(
                func.count(distinct(Track.id)),
                func.count(Scrobble.id)).\
            group_by(Album.id).\
            all()

        neworder = defaultdict(lambda: 1.0, albums.items())

        for album, n_tracks, n_scrobbles in results:
            if album not in neworder or n_tracks == 0:
                continue

            album_plays = n_scrobbles / n_tracks
            if self.plays_min <= album_plays <= self.plays_max:
                neworder[album] *= album_plays
            else:
                if album in neworder:
                    del neworder[album]

        return neworder


class Analytics(object):

    def __init__(self, conf):
        self.conf = conf

    def order_albums(self, session, orderers=None):
        mpd = mstat.initialize_mpd(self.conf)

        if orderers is None:
            orderers = [BaseOrder()]

        ordered = {}
        for album_orderer in orderers:
            ordered = album_orderer.order(ordered, session, mpd)

        albums = [album for album, order in sorted(
            ordered.items(),
            reverse=True,
            key=itemgetter(1))
        ]

        return [Suggestion(album) for album in albums]
