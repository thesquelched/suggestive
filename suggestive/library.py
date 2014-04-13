import suggestive.widget as widget
import suggestive.bindings as bindings
import suggestive.mstat as mstat
import suggestive.util as util
import suggestive.analytics as analytics
import suggestive.signals as signals
from suggestive.buffer import Buffer

from mpd import ConnectionError

from suggestive.mvc import View, Model, Controller, TrackModel

import urwid
import logging
from itertools import chain


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


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

class LibraryController(Controller):

    def __init__(self, model, conf, session):
        super(LibraryController, self).__init__(model)
        self._conf = conf

        self._default_orderers = [analytics.BaseOrder()]

        # Connections
        self._mpd = mstat.initialize_mpd(conf)
        self._session = session

        self._anl = analytics.Analytics(conf)

        self._orderers = None
        self.orderers = self._default_orderers.copy()

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
        self.model.albums = self.order_albums()

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

    #signal_handler
    def enqueue_album(self, album):
        self.enqueue_tracks(album.tracks)

    #signal_handler
    def enqueue_track(self, track):
        self.enqueue_tracks([track])

    #signal_handler
    def play_album(self, album):
        self.play_tracks(album.tracks)

    #signal_handler
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

        return sorted(
            track_and_num,
            key=lambda pair: pair[0],
            reverse=True)


######################################################################
# Views
######################################################################

class TrackView(widget.SelectableLibraryItem, View, widget.Searchable):

    FORMAT = '{number} - {name}{suffix}'

    def __init__(self, model, conf):
        View.__init__(self, model)

        self.content = model.db_track
        self._icon = urwid.SelectableIcon(self.text)

        super(TrackView, self).__init__(
            urwid.AttrMap(self._icon, 'track', 'focus track'))

    @property
    def text(self):
        model = self.model
        if model.loved:
            suffix = ' [L]'
        elif model.banned:
            suffix = ' [B]'
        else:
            suffix = ''

        return self.FORMAT.format(
            number=model.number,
            name=model.name,
            suffix=suffix)

    @property
    def canonical_text(self):
        model = self.model
        return self.FORMAT.format(
            number=model.number,
            name=model.name,
            suffix='')


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
    def canonical_text(self):
        album = self.db_album
        return '{} - {}'.format(album.artist.name, album.name)

    @property
    def text(self):
        if self.show_score:
            return '{} ({:.4g})'.format(self.canonical_text, self.score)
        else:
            return self.canonical_text

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
                    signals.ENQUEUE,
                    self._controller.enqueue_album)
                urwid.connect_signal(
                    view,
                    signals.PLAY,
                    self._controller.play_album)
                urwid.connect_signal(
                    view,
                    signals.EXPAND,
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
            model = TrackModel(track, track_no)
            track_view = TrackView(model, self._conf)

            urwid.connect_signal(
                track_view,
                signals.ENQUEUE,
                self._controller.enqueue_track)
            urwid.connect_signal(
                track_view,
                signals.PLAY,
                self._controller.play_track)
            urwid.connect_signal(
                track_view,
                signals.EXPAND,
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


######################################################################
# Buffer
######################################################################

class LibraryBuffer(Buffer):
    signals = Buffer.signals + ['update_playlist']

    def __init__(self, conf, session):
        self.conf = conf
        self.model = LibraryModel([])
        self.controller = LibraryController(self.model, conf, session)
        self.view = LibraryView(self.model, self.controller, conf)

        super(LibraryBuffer, self).__init__(self.view)

        # Set up default orderers
        self.init_default_orderers(conf)
        self.controller.set_current_order_as_default()

        self.update_status('Library')

    def search(self, searcher):
        self.view.search(searcher)

    def next_search(self):
        self.view.next_search_item()

    def orderer_command(self, orderer, defaults):
        if not defaults:
            return orderer

        def orderer_func(*args, **kwArgs):
            kwArgs.update(defaults)
            return orderer(*args, **kwArgs)
        return orderer_func

    def orderer_func(self, orderer):
        def add_func(*args, **kwArgs):
            self.add_orderer(orderer, *args, **kwArgs)
        return add_func

    def init_default_orderers(self, conf):
        order_commands = conf.default_orderers()
        logger.debug('Initializing default orders: {}'.format(order_commands))
        for cmd in order_commands:
            self.execute_command(cmd)

    def init_custom_orderers(self, conf):
        orderers = {}
        for name, cmds in conf.custom_orderers().items():
            def orderer_cmd(cmds=cmds):
                for cmd in cmds:
                    logger.debug('order: {}'.format(cmd))
                    self.execute_command(cmd)
            orderers[name] = orderer_cmd

        return orderers

    def setup_orderers(self):
        return {
            ('artist', 'ar'): (analytics.ArtistFilter, None),
            ('album', 'al'): (analytics.AlbumFilter, None),
            ('sort',): (analytics.SortOrder, {
                'ignore_artist_the': self.conf.ignore_artist_the()
            }),
            ('loved', 'lo'): (analytics.FractionLovedOrder, None),
            ('banned', 'bn'): (analytics.BannedOrder, None),
            ('pc', 'playcount'): (analytics.PlaycountOrder, None),
            ('mod', 'modified'): (analytics.ModifiedOrder, None),
        }

    def setup_commands(self):
        init_orderers = self.setup_orderers()
        orderers = dict(
            chain.from_iterable(
                ((command, self.orderer_command(func, defaults))
                    for command in commands)
                for commands, (func, defaults) in init_orderers.items()
            )
        )

        commands = self.init_custom_orderers(self.conf)
        commands.update({
            'reset': self.controller.reset_orderers,
            'unorder': self.controller.clear_orderers,
            'unordered': self.controller.clear_orderers,
        })

        commands.update({
            name: self.orderer_func(orderer)
            for name, orderer in orderers.items()
        })

        return commands

    def setup_bindings(self):
        keybinds = super(LibraryBuffer, self).setup_bindings()

        if self.conf.esc_resets_orderers():
            keybinds.update({
                'esc': lambda: self.controller.reset_orderers(),
            })

        return keybinds

    def add_orderer(self, orderer_class, *args, **kwArgs):
        logger.debug('Adding orderer: {}'.format(orderer_class.__name__))
        self.controller.add_orderer(orderer_class, *args, **kwArgs)
