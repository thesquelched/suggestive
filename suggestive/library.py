import suggestive.widget as widget
import suggestive.bindings as bindings
import suggestive.mstat as mstat
import suggestive.util as util
import suggestive.analytics as analytics

import urwid
import logging
from itertools import chain


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


ENQUEUE = 'enqueue'
PLAY = 'play'


######################################################################
# Models
######################################################################

class AlbumModel(object):

    def __init__(self, db_album, score):
        self._db_album = db_album
        self._score = score

    @property
    def score(self):
        return self._score

    @property
    def db_album(self):
        return self._db_album


class TrackModel(object):

    def __init__(self, track):
        self._track = track

    @property
    def name(self):
        return self._track.name


class LibraryModel(object):

    def __init__(self, albums):
        self._albums = sorted(albums, key=lambda album: album.score)

    @property
    def albums(self):
        return self._albums

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

    def __init__(self, conf, session):
        self._conf = conf

        # Connections
        self._mpd = mstat.initialize_mpd(conf)
        self._session = session

        self._orderers = [analytics.BaseOrder()]
        self._anl = analytics.Analytics(conf)

        self._model = self.load_model()
        self._views = []

    def register(self, view):
        self._views.append(view)

    def update(self):
        logger.debug('Updating LibraryController views')
        for view in self.views:
            view.update()

    def load_model(self):
        suggestions = self._anl.order_albums(self._session, self._orderers)
        albums = [AlbumModel(s.album, s.order) for s in suggestions]
        return LibraryModel(albums)

    def add_orderer(self, orderer_class, *args, **kwArgs):
        orderer = orderer_class(*args, **kwArgs)
        try:
            idx = list([type(o) for o in self._orderers]).index(orderer)
            self._orderers[idx] = orderer
        except ValueError:
            self._orderers.append(orderer)

        logger.debug('Orderers: {}'.format(
            ', '.join(map(repr, self._orderers))))

        self.model = self.load_model()

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, newmodel):
        self._model = newmodel
        self.update()

    @property
    def views(self):
        return self._views

    @signal_handler
    def enqueue_album(self, album):
        self.enqueue_tracks(album.tracks)

    @signal_handler
    def enqueue_track(self, track):
        self.enqueue_tracks([track])

    @signal_handler
    def play_album(self, album):
        self.play_tracks(album.tracks)

    @signal_handler
    def play_track(self, track):
        self.play_tracks([track])

    def enqueue_tracks(self, tracks):
        mpd_tracks = list(chain.from_iterable(
            self._mpd.listallinfo(track.filename) for track in tracks))

        for i, track in enumerate(mpd_tracks):
            track['track'] = util.track_num(track.get('track', i))

        sorted_tracks = sorted(mpd_tracks, key=lambda track: track['track'])
        return [self._mpd.addid(track['file']) for track in sorted_tracks]

    def play_tracks(self, tracks):
        ids = self.enqueue_tracks(tracks)
        if ids:
            self._mpd.playid(ids[0])


######################################################################
# Views
######################################################################

class AlbumView(widget.SelectableLibraryItem):

    def __init__(self, model, conf):
        self._model = model
        self._show_score = conf.show_score()

        icon = urwid.SelectableIcon(self.text)
        super(AlbumView, self).__init__(
            urwid.AttrMap(icon, 'album', 'focus album'))

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


class LibraryView(widget.SuggestiveListBox):
    def __init__(self, controller, conf):
        self._controller = controller
        self._conf = conf

        walker = self.create_walker()
        super(LibraryView, self).__init__(walker)

        # Set command map after super so bindings don't get overwritten
        self._command_map = bindings.AlbumListCommands

        # Register view with controller
        controller.register(self)

    def update(self):
        logger.debug('Updating LibraryView')
        walker = self.body
        walker[:] = self.library_items()

    def library_items(self):
        if not self._controller.model.albums:
            body = [urwid.AttrMap(urwid.Text('No albums found'), 'album')]
        else:
            body = []
            for album_m in self._controller.model.albums:
                view = AlbumView(album_m, self._conf)

                urwid.connect_signal(
                    view,
                    ENQUEUE,
                    self._controller.enqueue_album)
                urwid.connect_signal(
                    view,
                    PLAY,
                    self._controller.play_album)

                # TODO: AttrMap here or inside of view?
                body.append(view)

        return body

    def create_walker(self):
        body = self.library_items()
        return urwid.SimpleFocusListWalker(body)

    def sort_tracks(self, tracks):
        pass
        #track_and_num = []
        #mpd = mstat.initialize_mpd(self.app.conf)

        #for i, track in enumerate(tracks):
        #    try:
        #        mpd_track = mpd.listallinfo(track.filename)
        #    except MpdCommandError:
        #        continue

        #    if not mpd_track:
        #        continue

        #    trackno = track_num(mpd_track[0].get('track', i))

        #    track_and_num.append((int(trackno), track))

        #return sorted(track_and_num, key=lambda pair: pair[0])

    def expand_album(self, album_widget):
        pass
        #current = self.focus_position
        #album = album_widget.original_widget.album

        #sorted_tracks = self.sort_tracks(album.tracks)
        #for track_no, track in reversed(sorted_tracks):
        #    track_widget = SelectableTrack(
        #        album_widget, track, track_no)

        #    urwid.connect_signal(track_widget, 'enqueue',
        #                         self.app.enqueue_track)
        #    urwid.connect_signal(track_widget, 'play', self.app.play_track)

        #    item = urwid.AttrMap(track_widget, 'track', 'focus track')
        #    self.body.insert(current + 1, item)

        #album_widget.original_widget.expanded = True
        #self.set_focus_valign('top')

    def collapse_album(self, album_widget):
        pass
        #current = self.focus_position
        #album_index = self.body.index(album_widget, 0, current + 1)

        #logger.debug('Album index: {}'.format(album_index))

        #album = album_widget.original_widget.album
        #for i in range(len(album.tracks)):
        #    track_widget = self.body[album_index + 1]
        #    if isinstance(track_widget.original_widget, SelectableTrack):
        #        self.body.pop(album_index + 1)
        #    else:
        #        logger.error('Item #{} is not a track'.format(i))

        #album_widget.original_widget.expanded = False

    def toggle_expand(self):
        pass
        #widget = self.focus

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
        cmd = self._command_map[key]
        if cmd == 'expand':
            self.toggle_expand()
        else:
            return super(LibraryView, self).keypress(size, key)

        # Necessary to get list focus to redraw
        super(LibraryView, self).keypress(size, None)

        return True
