from suggestive.library import TrackModel
import suggestive.widget as widget
import suggestive.bindings as bindings
import suggestive.mstat as mstat

from mpd import ConnectionError

from suggestive.mvc import View, Model, Controller

import urwid
import logging


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


SIGNAL_ENQUEUE = 'enqueue'
SIGNAL_PLAY = 'play'
SIGNAL_EXPAND = 'expand'
SIGNAL_DELETE = 'delete'
SIGNAL_MOVE = 'move'
SIGNAL_LOVE = 'love'


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

    # Signal handler
    def move_track(self, view):
        logger.info('Move playlist track: {}'.format(view.canonical_text))
        pass

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
        #items = []

        #for position, track in enumerate(playlist):
        #    pieces = [self.format_track(track)]
        #    if self.show_numbers and digits:
        #        # Mark current position as 'C'
        #        if position == self.playlist.focus_position:
        #            position = 'C'

        #        number = str(position).ljust(digits + 1, ' ')
        #        pieces.insert(0, ('bumper', number))

        #    text = widget.PlaylistItem(pieces)
        #    if position == now_playing:
        #        styles = ('playing', 'focus playing')
        #    else:
        #        styles = ('playlist', 'focus playlist')

        #    items.append(urwid.AttrMap(text, *styles))

        #return items

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
class TrackView(urwid.WidgetWrap, View):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['play', 'delete', 'move', 'love']

    TRACK_FORMAT = '{artist} - {album} - {title}{suffix}'

    def __init__(self, model, conf, playing=False):
        View.__init__(self, model)

        self.content = model.db_track
        self._icon = urwid.SelectableIcon(self.text)

        if playing:
            styles = ('playing', 'focus playing')
        else:
            styles = ('playlist', 'focus playlist')

        super(TrackView, self).__init__(
            urwid.AttrMap(self._icon, *styles))

    @property
    def text(self):
        model = self.model
        if model.loved:
            suffix = ' [L]'
        elif model.banned:
            suffix = ' [B]'
        else:
            suffix = ''

        return self.TRACK_FORMAT.format(
            artist=model.db_artist.name,
            album=model.db_album.name,
            title=model.name,
            suffix=suffix)

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

    def update(self):
        logger.debug('Updating PlaylistView')

        current_position = self.focus_position
        walker = self.body

        walker[:] = self.track_views()

        try:
            self.set_focus(current_position)
        except IndexError:
            try:
                self.set_focus(current_position - 1)
            except IndexError:
                pass

    def track_views(self):
        current = self.controller.now_playing()

        if not self.model.tracks:
            body = [urwid.AttrMap(urwid.Text('Playlist is empty'), 'track')]
        else:
            body = []
            for track_m in self.model.tracks:
                view = TrackView(
                    track_m,
                    self._conf,
                    playing=(track_m.number == current))

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
                    SIGNAL_MOVE,
                    self.controller.move_track)
                urwid.connect_signal(
                    view,
                    SIGNAL_LOVE,
                    self.controller.love_track)

                body.append(view)

        return body

    def create_walker(self):
        body = self.track_views()
        return urwid.SimpleFocusListWalker(body)

    def expand_album(self, view):
        album = view.db_album
        current = self.focus_position

        sorted_tracks = self.controller.sort_tracks(album.tracks)
        for track_no, track in sorted_tracks:
            model = TrackModel(track, track_no)
            track_view = TrackView(model, self._conf)

            urwid.connect_signal(
                track_view,
                SIGNAL_ENQUEUE,
                self._controller.enqueue_track)
            urwid.connect_signal(
                track_view,
                SIGNAL_PLAY,
                self._controller.play_track)
            urwid.connect_signal(
                track_view,
                SIGNAL_EXPAND,
                self.collapse_album_from_track,
                view)

            self.body.insert(current + 1, track_view)

        view.expanded = True
        self.set_focus_valign('top')

    def album_index(self, view):
        current = self.focus_position
        return self.body.index(view, 0, current + 1)

    def collapse_album(self, view):
        album_index = self.album_index(view)

        album = view.db_album
        for i in range(len(album.tracks)):
            self.body.pop(album_index + 1)

        view.expanded = False
        self.body.set_focus(album_index)

    def collapse_album_from_track(self, track_view, album_view):
        """
        Collapse album when a track is in focus
        """
        self.collapse_album(album_view)

    def toggle_expand(self, view):
        """
        Toggle album track display
        """
        logger.debug('Toggle: {}'.format(view))

        if view.expanded:
            self.collapse_album(view)
        else:
            self.expand_album(view)
