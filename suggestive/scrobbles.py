import suggestive.mstat as mstat
import suggestive.widget as widget
from suggestive.buffer import Buffer
import logging
from mpd import CommandError as MpdCommandError


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


class ScrobbleBuffer(Buffer):

    def __init__(self, conf, event_loop):
        self.conf = conf

        self.scrobble_list = self.create_scrobble_list()
        self.current_song_id = None
        self.plays = []

        super(ScrobbleBuffer, self).__init__(self.scrobble_list)

        self.update_status('Scrobbles')

    def session(self, **kwArgs):
        return mstat.session_scope(self.conf, **kwArgs)

    def create_scrobble_list(self, previous=None, plays=None):
        with self.session(commit=False) as session:
            walker = widget.ScrobbleListWalker(
                self.conf,
                session,
                previous,
                plays)
        return widget.SuggestiveListBox(walker)

    def update(self, *args):
        mpd = mstat.initialize_mpd(self.conf)
        status = mpd.status()

        songid = status.get('songid')
        if songid != self.current_song_id:
            try:
                info = mpd.playlistid(songid)[0]
                db_track = mstat.database_track_from_mpd(
                    self.conf,
                    info)
                self.plays.insert(0, db_track)
                logger.debug('Plays: {}'.format(self.plays))
            except (MpdCommandError, IndexError):
                pass

        self.current_song_id = songid

        self.scrobble_list = self.create_scrobble_list(
            self.scrobble_list, self.plays)
        self.set_body(self.scrobble_list)

    def search(self, searcher):
        self.scrobble_list.search(searcher)

    def next_search(self):
        self.scrobble_list.next_search_item()
