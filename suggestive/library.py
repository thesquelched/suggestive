import suggestive.widget as widget
import suggestive.bindings as bindings
import suggestive.mstat as mstat
import suggestive.util as util
import suggestive.analytics as analytics

from mpd import ConnectionError

from suggestive.mvc import View, Model

import urwid
import logging
from itertools import chain


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


SIGNAL_ENQUEUE = 'enqueue'
SIGNAL_PLAY = 'play'
SIGNAL_EXPAND = 'expand'


######################################################################
# Models
######################################################################

class AlbumModel(Model):

    def __init__(self, db_album, score):
        super(AlbumModel, self).__init__()
        self._db_album = db_album
        self._score = score

    @property
    def score(self):
        return self._score

    @property
    def db_album(self):
        return self._db_album


class TrackModel(Model):

    def __init__(self, db_track):
        super(TrackModel, self).__init__()
        self._db_track = db_track

    @property
    def db_track(self):
        return self._db_track

    @property
    def name(self):
        return self.db_track.name


class LibraryModel(Model):

    def __init__(self, albums):
        super(LibraryModel, self).__init__()
        self.albums = albums

    def __repr__(self):
        return '<LibraryModel>'

    @property
    def albums(self):
        return self._albums

    @albums.setter
    def albums(self, newalbums):
        self._albums = sorted(
            newalbums,
            key=lambda album: album.score,
            reverse=True)
        self.update()


######################################################################
# Controllers
######################################################################

def signal_handler(func):
    """
    Signal handler callback, for when the signalling widget should be ignored
    """

    def handler(self, signalling_widget, *args):
        return func(self, *args)

    return handler


class LibraryController(object):

    def __init__(self, model, conf, session):
        self._model = model
        self._conf = conf

        self._default_orderers = [analytics.BaseOrder()]

        # Connections
        self._mpd = mstat.initialize_mpd(conf)
        self._session = session

        self._anl = analytics.Analytics(conf)

        self._orderers = None
        self.orderers = self._default_orderers.copy()

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, newmodel):
        self._model = newmodel

    @property
    def orderers(self):
        return self._orderers

    @orderers.setter
    def orderers(self, neworderers):
        if self._orderers != neworderers:
            self._orderers = neworderers

            self.log_orderers()
            self.update_model()

    def log_orderers(self):
        logger.debug('Orderers: {}'.format(
            ', '.join(map(repr, self.orderers))))

    def update_model(self):
        """
        Set the model album order, which in turn updates the views
        """
        self._model.albums = self.order_albums()

    def order_albums(self):
        suggestions = self._anl.order_albums(self._session, self._orderers)
        return [AlbumModel(s.album, s.order) for s in suggestions]

    def add_orderer(self, orderer_class, *args, **kwArgs):
        orderer = orderer_class(*args, **kwArgs)
        try:
            idx = list([type(o) for o in self._orderers]).index(orderer)
            self._orderers[idx] = orderer
        except ValueError:
            self._orderers.append(orderer)

        self.update_model()

    def clear_orderers(self):
        self.orderers = [analytics.BaseOrder()]

    def reset_orderers(self):
        """
        Reset orderers to default
        """
        self.orderers = self._default_orderers

    def set_current_order_as_default(self):
        self._default_orderers = self._orderers.copy()

    #@signal_handler
    def enqueue_album(self, album):
        self.enqueue_tracks(album.tracks)

    #@signal_handler
    def enqueue_track(self, track):
        self.enqueue_tracks([track])

    #@signal_handler
    def play_album(self, album):
        self.play_tracks(album.tracks)

    #@signal_handler
    def play_track(self, track):
        self.play_tracks([track])

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

    @mpd_retry
    def mpd_tracks(self, tracks):
        return list(chain.from_iterable(
            self._mpd.listallinfo(track.filename) for track in tracks))

    @mpd_retry
    def add_mpd_track(self, track):
        return self._mpd.addid(track['file'])

    def enqueue_tracks(self, tracks):
        mpd_tracks = self.mpd_tracks(tracks)

        for i, track in enumerate(mpd_tracks):
            track['track'] = util.track_num(track.get('track', i))

        sorted_tracks = sorted(mpd_tracks, key=lambda track: track['track'])
        return [self.add_mpd_track(t) for t in sorted_tracks]

    def play_tracks(self, tracks):
        ids = self.enqueue_tracks(tracks)
        if ids:
            self._mpd.playid(ids[0])

    def sort_tracks(self, tracks):
        track_and_num = []
        mpd_tracks = self.mpd_tracks(tracks)

        for i, mpd_track in enumerate(mpd_tracks):
            if not mpd_track:
                continue

            trackno = util.track_num(mpd_track.get('track', i))
            track_and_num.append((int(trackno), tracks[i]))

        return sorted(track_and_num, key=lambda pair: pair[0])


######################################################################
# Views
######################################################################

class TrackView(widget.SelectableLibraryItem, View):

    def __init__(self, model, conf):
        View.__init__(self, model)

        self.content = model.db_track
        self._icon = urwid.SelectableIcon(self.text)

        super(TrackView, self).__init__(
            urwid.AttrMap(self._icon, 'track', 'focus track'))

    @property
    def text(self):
        return self.model.name


class AlbumView(widget.SelectableLibraryItem, View):

    def __init__(self, model, conf):
        View.__init__(self, model)

        self.content = model.db_album
        self._expanded = False

        self._show_score = conf.show_score()
        self._icon = urwid.SelectableIcon(self.text)

        super(AlbumView, self).__init__(
            urwid.AttrMap(self._icon, 'album', 'focus album'))

    @property
    def score(self):
        return self._model.score

    @property
    def db_album(self):
        return self._model.db_album

    @property
    def show_score(self):
        return self._show_score

    @property
    def text(self):
        album = self.db_album
        album_text = '{} - {}'.format(album.artist.name, album.name)
        if self.show_score:
            return '{} ({:.4g})'.format(album_text, self.score)
        else:
            return album_text

    @property
    def expanded(self):
        return self._expanded

    @expanded.setter
    def expanded(self, value):
        self._expanded = value


class LibraryView(widget.SuggestiveListBox, View):
    def __init__(self, model, controller, conf):
        View.__init__(self, model)

        self._model = model
        self._controller = controller
        self._conf = conf

        walker = self.create_walker()
        super(LibraryView, self).__init__(walker)

        # Set command map after super so bindings don't get overwritten
        self._command_map = bindings.AlbumListCommands

        self._model.register(self)

    def update(self):
        logger.debug('Updating LibraryView')
        walker = self.body
        walker[:] = self.library_items(self.model)

    def library_items(self, model):
        if not model.albums:
            body = [urwid.AttrMap(urwid.Text('No albums found'), 'album')]
        else:
            body = []
            for album_m in model.albums:
                view = AlbumView(album_m, self._conf)

                urwid.connect_signal(
                    view,
                    SIGNAL_ENQUEUE,
                    self._controller.enqueue_album)
                urwid.connect_signal(
                    view,
                    SIGNAL_PLAY,
                    self._controller.play_album)
                urwid.connect_signal(
                    view,
                    SIGNAL_EXPAND,
                    self.toggle_expand)

                # TODO: AttrMap here or inside of view?
                body.append(view)

        return body

    def create_walker(self):
        body = self.library_items(self._controller.model)
        return urwid.SimpleFocusListWalker(body)

    def expand_album(self, view):
        album = view.db_album
        current = self.focus_position

        sorted_tracks = self._controller.sort_tracks(album.tracks)
        for track_no, track in sorted_tracks:
            model = TrackModel(track)
            track_view = TrackView(model, self._conf)

            urwid.connect_signal(
                track_view,
                SIGNAL_ENQUEUE,
                self._controller.enqueue_track)
            urwid.connect_signal(
                track_view,
                SIGNAL_PLAY,
                self._controller.play_track)

            self.body.insert(current + 1, track_view)

        view.expanded = True
        #self.set_focus_valign('top')

    def collapse_album(self, view):
        current = self.focus_position
        album_index = self.body.index(view, 0, current + 1)

        logger.debug('Album index: {}'.format(album_index))

        album = view.db_album
        for i in range(len(album.tracks)):
            self.body.pop(album_index + 1)
            #track_view = self.body[album_index + 1]
            #if isinstance(track_widget.original_widget, SelectableTrack):
            #    self.body.pop(album_index + 1)
            #else:
            #    logger.error('Item #{} is not a track'.format(i))

        view.expanded = False
        #album_widget.original_widget.expanded = False

    def toggle_expand(self, view):
        logger.debug('Toggle: {}'.format(view))

        if view.expanded:
            self.collapse_album(view)
        else:
            self.expand_album(view)

        #if isinstance(widget.original_widget, SelectableTrack):
        #    widget = widget.original_widget.parent

        #if widget.original_widget.expanded:
        #    self.collapse_album(widget)
        #else:
        #    self.expand_album(widget)

        #album = widget.original_widget.album

        #logger.info('Expand: {} ({} tracks)'.format(
        #    album_text(album),
        #    len(album.tracks)))

    def keypress(self, size, key):
        #cmd = self._command_map[key]
        #if cmd == 'expand':
        #    self.toggle_expand()
        #else:
        #    return super(LibraryView, self).keypress(size, key)
        return super(LibraryView, self).keypress(size, key)

        # Necessary to get list focus to redraw
        #super(LibraryView, self).keypress(size, None)

        #return True
