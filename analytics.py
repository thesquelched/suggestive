from model import Album, Track, Scrobble, LastfmTrackInfo
from sqlalchemy import func


class Suggestion(object):
    def __init__(self, album):
        self.album = album
        self.loved = [
            track for track in album.tracks
            if track.lastfm_info and track.lastfm_info.loved
        ]


def choose(n, k):
    if 0 <= k <= n:
        ntok = 1
        ktok = 1
        for t in range(1, min(k, n - k) + 1):
            ntok *= n
            ktok *= k
            n -= 1
        return ntok
    else:
        return 0


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
        p_loved = self.p_loved()

        results = self.session.query(Album).\
            join(Track).\
            outerjoin(LastfmTrackInfo).\
            add_columns(func.count(Track.id), func.count(LastfmTrackInfo.id)).\
            group_by(Album.id).\
            all()

        p_love_album = list()
        for album, n_tracks, n_loved in results:
            p_loved = (1 - choose(n_tracks, n_loved) * p_loved ** n_loved
                       * (1 - p_loved) ** (n_tracks - n_loved))

            p_love_album.append((album, p_loved))

        ordered = sorted(p_love_album, key=lambda p: p[1])
        return [Suggestion(album) for album, _prob in ordered]

    def p_loved(self):
        n_tracks = self.session.query(Track).count()
        n_loved = self.session.query(LastfmTrackInfo).\
            filter_by(loved=True).\
            count()

        return n_loved / n_tracks
