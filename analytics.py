from model import Album, Track, Scrobble, LastfmTrackInfo
from sqlalchemy import func, Integer
import logging
from itertools import repeat
from collections import defaultdict
from operator import itemgetter
import re


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

    def __init__(self, next=None):
        self.next = next

    def order(self, albums, session):
        raise NotImplementedError


class BaseOrder(OrderDecorator):

    """Initialize all albums with unity order"""

    def order(self, albums, session):
        return defaultdict(
            lambda: 1.0,
            zip(session.query(Album).all(), repeat(1.0))
        )


class AlbumFilter(OrderDecorator):
    def __init__(self, name):
        self.name_rgx = re.compile(name, re.I)

    def order(self, albums, session):
        return {
            album: order for album, order in albums.items()
            if re.search(self.name_rgx, album.name) is not None
        }


class ArtistFilter(OrderDecorator):
    def __init__(self, name):
        self.name_rgx = re.compile(name, re.I)

    def order(self, albums, session):
        return {
            album: order for album, order in albums.items()
            if re.search(self.name_rgx, album.artist.name) is not None
        }


class SortOrder(OrderDecorator):
    @classmethod
    def _format(cls, album):
        return '{} - {}'.format(album.artist.name, album.name)

    def order(self, albums, session):
        sorted_albums = sorted(albums, key=self._format, reverse=True)
        return {album: i for i, album in enumerate(sorted_albums, 1)}


class BannedOrder(OrderDecorator):

    """Remove or demote albums with banned tracks"""

    def __init__(self, remove_banned=True):
        self.remove = remove_banned

    def order(self, albums, session):
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

    def __init__(self, minimum=None, maximum=None, penalize_unloved=False):
        super(FractionLovedOrder, self).__init__()
        self.penalize = penalize_unloved

        if minimum is None:
            minimum = 0
        if maximum is None:
            maximum = 1

        minimum, maximum = float(minimum), float(maximum)

        if minimum > maximum:
            minimum, maximum = maximum, minimum

        min_ = min(max(minimum, 0), 1)
        self.f_max = max(min(maximum, 1), min_)
        self.f_min = min(max(minimum, 0), self.f_max)

    def order(self, albums, session):
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

    def __init__(self, minimum=None, maximum=None):
        if minimum is None:
            minimum = 0
        if maximum is None:
            maximum = 1

        minimum, maximum = float(minimum), float(maximum)

        if minimum > maximum:
            minimum, maximum = maximum, minimum

        self.plays_min = max(0, minimum)
        self.plays_max = max(self.plays_min, maximum)

    def order(self, albums, session):
        results = session.query(Album).\
            join(Track).\
            outerjoin(Scrobble).\
            add_columns(func.count(Track.id), func.count(Scrobble.id)).\
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

    def __init__(self, session):
        self.session = session

    def not_recently_played(self):
        return self.session.query(Album).\
            outerjoin(Album.tracks).\
            outerjoin(Track.scrobbles).\
            group_by(Album.id).\
            having(func.count(Scrobble.id) == 0)

    def suggest_albums(self, n_albums=None):
        not_played = self.not_recently_played()

        if n_albums is None:
            albums = not_played.all()
        else:
            albums = not_played.limit(n_albums).all()

        return [Suggestion(album) for album in albums]

    def loved_order(self):
        album_orderer = FractionLovedOrder()

        ordered = album_orderer.order({}, self.session)
        albums = [album for album, order in sorted(
            ordered.items(),
            reverse=True,
            key=itemgetter(1))
        ]

        return [Suggestion(album) for album in albums]

    def order_albums(self, orderers=None):
        if orderers is None:
            orderers = [BaseOrder()]

        ordered = {}
        for album_orderer in orderers:
            ordered = album_orderer.order(ordered, self.session)

        albums = [album for album, order in sorted(
            ordered.items(),
            reverse=True,
            key=itemgetter(1))
        ]

        return [Suggestion(album) for album in albums]

    #def loved_order(self):
    #    pct_loved = self.p_loved()

    #    results = self.session.query(Album).\
    #        join(Track).\
    #        outerjoin(LastfmTrackInfo).\
    #        add_columns(func.count(Track.id),
    #                    func.count(LastfmTrackInfo.id)).\
    #        group_by(Album.id).\
    #        all()

    #    p_love_album = list()
    #    handle = open('loved.csv', 'w')
    #    for album, n_tracks, n_loved in results:
    #        p_loved = (choose(n_tracks, n_loved) * pct_loved ** n_loved
    #                   * (1 - pct_loved) ** (n_tracks - n_loved))
    #        handle.write('"{} - {}",{},{},{}\n'.format(
    #            album.artist.name, album.name, n_tracks, n_loved, p_loved))

    #        p_love_album.append((album, p_loved))

    #    handle.close()
    #    ordered = sorted(p_love_album, key=lambda p: p[1])

    #    # TODO: Remove this
    #    #with open('ordered.csv', 'w') as handle:
    #    #    for album, prob in ordered:
    #    #        handle.write('"{} - {}",{}\n'.format(
    #    #            album.artist.name, album.name, prob))

    #    return [Suggestion(album) for album, _prob in ordered]

    #def p_loved(self):
    #    n_tracks = self.session.query(Track).count()
    #    n_loved = self.session.query(LastfmTrackInfo).\
    #        filter_by(loved=True).\
    #        count()

    #    return n_loved / n_tracks
