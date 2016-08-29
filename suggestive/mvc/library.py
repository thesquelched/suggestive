import suggestive.widget as widget
import suggestive.mstat as mstat
import suggestive.util as util
import suggestive.analytics as analytics
import suggestive.signals as signals
from suggestive.buffer import Buffer
from suggestive.action import lastfm_love_track

from suggestive.mvc.base import View, Model, Controller, TrackModel

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

    def __init__(self, albums, tracks=None):
        if tracks is None:
            tracks = {}

        super(LibraryModel, self).__init__()

        self._albums = albums
        self._tracks = tracks

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

    @property
    def tracks(self):
        return self._tracks

    def track_model_for(self, db_track):
        return self.tracks.get(db_track.id)


######################################################################
# Controllers
######################################################################

class LibraryController(Controller):

    def __init__(self, model, conf, loop):
        super(LibraryController, self).__init__(model, conf, loop)

        self._default_orderers = [analytics.BaseOrder()]

        # Connections
        self._mpd = mstat.initialize_mpd(conf)
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

    def album_tracks(self, album):
        return mstat.get_album_tracks(self.conf, album)

    def log_orderers(self):
        logger.debug('Orderers: {}'.format(
            ', '.join(map(repr, self.orderers))))

    def update_model(self):
        """
        Set the model album order, which in turn updates the views
        """
        self.model.albums = self.order_albums()

    def order_albums(self):
        suggestions = self._anl.order_albums(self._orderers)
        return [AlbumModel(s.album, s.order) for s in suggestions]

    def add_orderer(self, orderer_class, *args, **kwArgs):
        orderer = orderer_class(*args, **kwArgs)
        try:
            idx = list([type(o) for o in self._orderers]).index(orderer)
            self._orderers[idx] = orderer
        except ValueError:
            self._orderers.append(orderer)

        self.log_orderers()
        self.update_model()

    def clear_orderers(self):
        self.orderers = [analytics.BaseOrder()]

    def reset_orderers(self):
        """
        Reset orderers to default
        """
        self.orderers = self._default_orderers.copy()

    def set_current_order_as_default(self):
        self._default_orderers = self._orderers.copy()

    # signal_handler
    def enqueue_album(self, view):
        self.enqueue_tracks(self.album_tracks(view.db_album))

    # signal_handler
    def enqueue_track(self, view):
        self.enqueue_tracks([view.db_track])

    # signal_handler
    def play_album(self, view):
        self.play_tracks(self.album_tracks(view.db_album))

    # signal_handler
    def play_track(self, view):
        self.play_tracks([view.db_track])

    # Signal handler
    def love_track(self, view):
        db_track = view.model.db_track
        if not db_track.id:
            logger.error('Can not mark invalid track loved')
            return

        logger.info('Toggle loved for playlist track: {}'.format(
            db_track.name))

        loved = db_track.lastfm_info.loved if db_track.lastfm_info else False

        self.async_run(lastfm_love_track, self.conf, db_track, not loved)
        mstat.db_track_love(self.conf, db_track, loved=not loved)

        new_track = mstat.get_db_track(self.conf, db_track.id)
        view.model.db_track = new_track

        model = self.controller_for('playlist').track_model_for(new_track)
        if model:
            model.db_track = new_track

    # Signal handler
    def ignore_album(self, view):
        db_album = view.model.db_album
        if not db_album.id:
            logger.error('Can not (un)ignore invalid album')
            return

        logger.info('Toggle ignored for playlist album: %s, ignore=%s',
                    db_album.name, not db_album.ignored)

        mstat.db_album_ignore(self.conf, db_album,
                              ignore=not db_album.ignored)

        self.update_model()

    @mstat.mpd_retry
    def mpd_tracks(self, tracks):
        return list(chain.from_iterable(
            self._mpd.listallinfo(track.filename) for track in tracks))

    @mstat.mpd_retry
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

@widget.signal_map({
    'z': signals.EXPAND,
    'enter': signals.PLAY,
    ' ': signals.ENQUEUE,
    'L': signals.LOVE,
})
class TrackView(urwid.WidgetWrap, View, widget.Searchable):
    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.EXPAND, signals.PLAY, signals.ENQUEUE, signals.LOVE]

    FORMAT = '{number} - {name}{suffix}'

    def __init__(self, model, conf):
        View.__init__(self, model)

        self.content = model.db_track
        self._icon = urwid.SelectableIcon(self.text)

        super(TrackView, self).__init__(
            urwid.AttrMap(self._icon, 'track', 'focus track'))

    @property
    def db_track(self):
        return self.model.db_track

    @property
    def text(self):
        model = self.model
        if model.loved:
            suffix = ' [L]'
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

    @property
    def searchable_text(self):
        return self.model.name

    def update(self):
        logger.debug('Updated {}'.format(self))
        self._w.original_widget.set_text(self.text)


@widget.signal_map({
    'z': signals.EXPAND,
    'enter': signals.PLAY,
    ' ': signals.ENQUEUE,
    'i': signals.IGNORE,
})
class AlbumView(urwid.WidgetWrap, View, widget.Searchable):
    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.EXPAND, signals.PLAY, signals.ENQUEUE, signals.IGNORE]

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
    def searchable_text(self):
        return self.canonical_text

    @property
    def text(self):
        if self.db_album.ignored:
            return '{} [I]'.format(self.canonical_text)

        if self.show_score:
            return '{} ({:.4g})'.format(self.canonical_text, self.score)

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

    @property
    def controller(self):
        return self._controller

    def update(self):
        logger.debug('Updating LibraryView')
        walker = self.body
        walker[:] = self.library_items(self.model)

    def library_items(self, model):
        if not model.albums:
            return [urwid.AttrMap(urwid.Text('No albums found'), 'album')]

        body = []
        for album_m in model.albums:
            view = AlbumView(album_m, self._conf)

            urwid.connect_signal(
                view,
                signals.ENQUEUE,
                self.controller.enqueue_album)
            urwid.connect_signal(
                view,
                signals.PLAY,
                self.controller.play_album)
            urwid.connect_signal(
                view,
                signals.EXPAND,
                self.toggle_expand)
            urwid.connect_signal(
                view,
                signals.IGNORE,
                self.controller.ignore_album)

            # TODO: AttrMap here or inside of view?
            body.append(view)

        return body

    def create_walker(self):
        body = self.library_items(self.controller.model)
        return urwid.SimpleFocusListWalker(body)

    def expand_album(self, view):
        album = view.db_album
        current = self.focus_position

        album_tracks = self.controller.album_tracks(album)
        sorted_tracks = self.controller.sort_tracks(album_tracks)
        for track_no, db_track in sorted_tracks:
            model = TrackModel(db_track, track_no)
            track_view = TrackView(model, self._conf)

            urwid.connect_signal(
                track_view,
                signals.ENQUEUE,
                self.controller.enqueue_track)
            urwid.connect_signal(
                track_view,
                signals.PLAY,
                self.controller.play_track)
            urwid.connect_signal(
                track_view,
                signals.EXPAND,
                self.collapse_album_from_track,
                view)
            urwid.connect_signal(
                track_view,
                signals.LOVE,
                self.controller.love_track)

            self.body.insert(current + 1, track_view)
            self.controller.model.tracks[db_track.id] = model

        view.expanded = True
        self.set_focus_valign('top')

    def album_index(self, view):
        current = self.focus_position
        return self.body.index(view, 0, current + 1)

    def collapse_album(self, view):
        album_index = self.album_index(view)

        album_tracks = self.controller.album_tracks(view.db_album)
        for i in range(len(album_tracks)):
            track_view = self.body.pop(album_index + 1)
            del self.controller.model.tracks[track_view.model.db_track.id]

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
        logger.debug('Toggle: {} ({})'.format(view, view.expanded))

        if view.expanded:
            self.collapse_album(view)
        else:
            self.expand_album(view)


######################################################################
# Buffer
######################################################################

class LibraryBuffer(Buffer):

    def __init__(self, conf, loop):
        self.conf = conf
        self.model = LibraryModel([])
        self.controller = LibraryController(self.model, conf, loop)
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
