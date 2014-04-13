import suggestive.widget as widget
import suggestive.bindings as bindings
import suggestive.mstat as mstat
from suggestive.mvc import View, Model, Controller, TrackModel

from mpd import ConnectionError

import urwid
from math import floor, log10
import logging


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


SIGNAL_ENQUEUE = 'enqueue'
SIGNAL_PLAY = 'play'
SIGNAL_EXPAND = 'expand'
SIGNAL_DELETE = 'delete'
SIGNAL_MOVE = 'move'
SIGNAL_LOVE = 'love'
SIGNAL_PROMPT_DONE = 'prompt_done'
SIGNAL_UPDATE_INDEX = 'update_index'


######################################################################
# Models
######################################################################

class PlaylistModel(Model):

    def __init__(self, tracks):
        super(PlaylistModel, self).__init__()
        self.tracks = tracks

    def __repr__(self):
        return '<PlaylistModel>'

    @property
    def tracks(self):
        return self._tracks

    @tracks.setter
    def tracks(self, newtracks):
        self._tracks = newtracks
        self.update()


######################################################################
# Controllers
######################################################################

class PlaylistController(Controller):

    def __init__(self, model, conf, session):
        super(PlaylistController, self).__init__(model)
        self._conf = conf

        # Connections
        self._mpd = mstat.initialize_mpd(conf)
        self._lastfm = mstat.initialize_lastfm(conf)
        self._session = session

        # Initialize
        self.update_model()

    @property
    def playlist_size(self):
        return len(self.model.tracks)

    # TODO: Move to mpd module
    def mpd_retry(func):
        """
        Decorator that reconnects MPD client if the connection is lost
        """
        def wrapper(self, *args, **kwArgs):
            try:
                return func(self, *args, **kwArgs)
            except ConnectionError:
                logger.warning('Detect MPD connection error; reconnecting...')
                self._mpd = mstat.initialize_mpd(self._conf)
                return func(self, *args, **kwArgs)
        return wrapper

    # Signal handler
    @mpd_retry
    def play_track(self, view):
        logger.info('Play playlist track: {}'.format(view.canonical_text))
        self._mpd.play(view.model.number)

    # Signal handler
    @mpd_retry
    def delete_track(self, view):
        logger.info('Delete playlist track: {}'.format(view.canonical_text))
        self._mpd.delete(view.model.number)
        self.update_model()

    # Signal handler
    def love_track(self, view):
        logger.info('Toggle loved for playlist track: {}'.format(
            view.canonical_text))

        db_track = view.model.db_track
        loved = db_track.lastfm_info.loved if db_track.lastfm_info else False
        mstat.set_track_loved(
            self._session,
            self._lastfm,
            db_track,
            loved=not loved)

        self._session.commit()

        view.update()

    @mpd_retry
    def clear(self):
        self._mpd.stop()
        self._mpd.clear()
        self.update_model()

    @mpd_retry
    def load_playlist(self, name):
        self._mpd.stop()
        self._mpd.clear()
        self._mpd.load(name)

    @mpd_retry
    def save_playlist(self, name):
        self._mpd.rm(name)
        self._mpd.save(name)

    @mpd_retry
    def mpd_playlist(self):
        return self._mpd.playlistinfo()

    @mpd_retry
    def now_playing(self):
        current = self._mpd.currentsong()
        if current and 'pos' in current:
            return int(current['pos'])
        else:
            return None

    def playlist_tracks(self):
        playlist = self.mpd_playlist()

        models = []
        for position, track in enumerate(playlist):
            db_track = mstat.database_track_from_mpd(self._session, track)
            models.append(TrackModel(db_track, position))

        return models

    def update_model(self):
        logger.debug('Updating PlaylistController model')
        self.model.tracks = self.playlist_tracks()


######################################################################
# Views
######################################################################

@widget.signal_map({
    'd': 'delete',
    'enter': 'play',
    'm': 'move',
    'L': 'love'
})
class TrackView(urwid.WidgetWrap, View, widget.Searchable):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['play', 'delete', 'move', 'love']

    TRACK_FORMAT = '{artist} - {album} - {title}{suffix}'

    def __init__(self,
                 model,
                 controller,
                 conf,
                 playing=False,
                 show_bumper=False,
                 focused=False):
        View.__init__(self, model)

        self._controller = controller

        self._show_bumper = show_bumper

        self.content = model.db_track
        self._icon = urwid.SelectableIcon(self.text)

        styles = self.styles(playing, focused)

        super(TrackView, self).__init__(
            urwid.AttrMap(self._icon, *styles))

    def styles(self, playing, focused):
        if focused and playing:
            return ('focus playing',)
        elif focused:
            return ('focus playlist',)
        elif playing:
            return ('playing', 'focus playing')
        else:
            return ('playlist', 'focus playlist')

    @property
    def controller(self):
        return self._controller

    def add_bumper(self, text):
        size = self.controller.playlist_size
        digits = (floor(log10(size)) + 1) if size else 0

        bumper = str(self.model.number)

        return [
            ('bumper', bumper.ljust(digits + 1, ' ')),
            text
        ]

    @property
    def text(self):
        model = self.model
        if model.loved:
            suffix = ' [L]'
        elif model.banned:
            suffix = ' [B]'
        else:
            suffix = ''

        text = self.TRACK_FORMAT.format(
            artist=model.db_artist.name,
            album=model.db_album.name,
            title=model.name,
            suffix=suffix)

        if self._show_bumper:
            return self.add_bumper(text)
        else:
            return text

    @property
    def canonical_text(self):
        model = self.model
        return self.TRACK_FORMAT.format(
            artist=model.db_artist.name,
            album=model.db_album.name,
            title=model.name,
            suffix='')

    def update(self):
        self._w.original_widget.set_text(self.text)


class PlaylistView(widget.SuggestiveListBox, View):
    def __init__(self, model, controller, conf):
        View.__init__(self, model)

        self._controller = controller
        self._conf = conf

        walker = self.create_walker()
        super(PlaylistView, self).__init__(walker)

        # Set command map after super so bindings don't get overwritten
        self._command_map = bindings.AlbumListCommands

        self.model.register(self)

    @property
    def controller(self):
        return self._controller

    def update(self, show_bumper=False):
        logger.debug('Updating PlaylistView')

        previous_position = self.focus_position
        walker = self.body

        walker[:] = self.track_views(show_bumper=show_bumper)

        self.focus_remembered_position(previous_position)

    def focus_remembered_position(self, position):
        if len(self.body) == 0:
            return

        try:
            # Try to focus on the same position in the playlist before we
            # updated
            self.set_focus(position)
        except IndexError:
            # If that failed, the playlist probably shrunk due to a deletion,
            # and we were on the last position before the delete.  Therefore,
            # we should be able to focus on the position before the last
            self.set_focus(position - 1)

    def track_views(self, show_bumper=False):
        current = self.controller.now_playing()
        focus = self.focus_position if show_bumper else None

        if not self.model.tracks:
            body = [urwid.AttrMap(urwid.Text('Playlist is empty'), 'track')]
        else:
            body = []
            for track_m in self.model.tracks:
                view = TrackView(
                    track_m,
                    self.controller,
                    self._conf,
                    playing=(track_m.number == current),
                    show_bumper=show_bumper,
                    focused=(track_m.number == focus))

                urwid.connect_signal(
                    view,
                    SIGNAL_PLAY,
                    self.controller.play_track)
                urwid.connect_signal(
                    view,
                    SIGNAL_DELETE,
                    self.controller.delete_track)
                urwid.connect_signal(
                    view,
                    SIGNAL_LOVE,
                    self.controller.love_track)

                body.append(view)

        return body

    def create_walker(self):
        body = self.track_views()
        return urwid.SimpleFocusListWalker(body)

    def move_update_index(self, current, index):
        try:
            items = self.body
            n_items = len(items)

            if index >= n_items:
                raise IndexError

            logger.debug('Temporary move from {} to {}'.format(
                current, index))

            if index > current:
                focus = items[current]
                items.insert(index + 1, focus)
                items.pop(current)
            elif index < current:
                focus = items.pop(current)
                items.insert(index, focus)
        except IndexError:
            logger.error('Index out of range')

    def keypress(self, size, key):
        if key == 'c':
            self.controller.clear()
            super(PlaylistView, self).keypress(size, None)
            return True

        return super(PlaylistView, self).keypress(size, key)
