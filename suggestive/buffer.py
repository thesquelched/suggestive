from suggestive.command import Commandable
import suggestive.widget as widget
import suggestive.mstat as mstat
from suggestive.util import album_text, track_num
import suggestive.analytics as analytics
from suggestive.error import CommandError
from suggestive.bindings import ENQUEUE, PLAY
from suggestive.library import LibraryController, LibraryView, LibraryModel

import logging
import urwid
from itertools import chain
from mpd import CommandError as MpdCommandError
import re
from math import log10, floor


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


######################################################################
# Buffer list
######################################################################

class BufferList(object):
    def __init__(self):
        self.buffers = []

    def __iter__(self):
        return iter(self.buffers)

    def next_buffer(self):
        logger.debug('Current buffers: {}'.format(self.buffers))

        current = self.focus_position
        indices = chain(
            range(current + 1, len(self.buffers)),
            range(current))

        for idx in indices:
            if self.go_to_buffer_index(idx):
                return

        logger.warn('Could not switch buffers')

    def current_buffer(self):
        return self.buffers[self.focus_position]

    def buffer_index(self, buf):
        return self.buffers.index(buf)

    def go_to_buffer_index(self, idx):
        try:
            buf = self.buffers[idx]
            if buf.will_accept_focus():
                self.focus_position = idx
                return True
        except IndexError:
            pass

        return False

    def go_to_buffer(self, buf):
        if not buf.will_accept_focus():
            return None

        try:
            idx = self.buffer_index(buf)

            self.focus_position = idx
            return self.focus_position
        except ValueError:
            return None

    def new_buffer(self, buf):
        return urwid.AttrMap(
            urwid.Filler(buf, valign='top', height=('relative', 100)),
            'album')

    def add(self, buf, *options):
        self.buffers.append(buf)
        self.contents.append((self.new_buffer(buf), self.options(*options)))

    def remove(self, buf):
        if len(self.buffers) == 1:
            return False

        idx = self.buffer_index(buf)
        self.buffers.remove(buf)
        self.contents.pop(idx)

        return True


class HorizontalBufferList(urwid.Pile, BufferList):

    def __init__(self):
        BufferList.__init__(self)
        urwid.Pile.__init__(self, [])

    def __iter__(self):
        return BufferList.__iter__(self)


class VerticalBufferList(urwid.Columns, BufferList):

    def __init__(self):
        BufferList.__init__(self)
        urwid.Columns.__init__(self, [], dividechars=1)

    def __iter__(self):
        return BufferList.__iter__(self)


######################################################################
# Buffers
######################################################################

class Buffer(urwid.Frame, Commandable):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['set_footer', 'set_focus', 'set_status', 'redraw']

    def __init__(self, *args, **kwArgs):
        super(Buffer, self).__init__(*args, **kwArgs)
        self.bindings = self.setup_bindings()
        self.commands = self.setup_commands()
        self.active = False
        urwid.connect_signal(self, 'set_status', self.update_status)

    def update_status(self, value):
        if isinstance(value, str):
            status = urwid.Text(value)
        else:
            status = value

        footer = urwid.AttrMap(status, 'status')
        self.set_footer(footer)

    def update_focus(self, to_focus):
        urwid.emit_signal(self, 'set_focus', to_focus)

    def update_footer(self, footer, focus=False):
        urwid.emit_signal(self, 'set_footer', footer, focus)

    def redraw(self):
        urwid.emit_signal(self, 'redraw')

    def setup_bindings(self):
        return {}

    def setup_commands(self):
        return {}

    def keypress(self, size, key):
        if not self.dispatch(key):
            return super(Buffer, self).keypress(size, key)

        super(Buffer, self).keypress(size, None)
        return True

    def dispatch(self, key):
        if key in self.bindings:
            func = self.bindings[key]
            func()
            return True
        else:
            return False

    def will_accept_focus(self):
        return True

    def search(self, searcher):
        raise NotImplementedError

    def next_search(self):
        raise NotImplementedError


class ScrobbleBuffer(Buffer):

    def __init__(self, conf, session):
        self.conf = conf
        self.session = session

        self.scrobble_list = self.create_scrobble_list()
        self.current_song_id = None
        self.plays = []

        super(ScrobbleBuffer, self).__init__(self.scrobble_list)

        self.update_status('Scrobbles')

    def create_scrobble_list(self, previous=None, plays=None):
        walker = widget.ScrobbleListWalker(
            self.conf,
            self.session,
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
                db_track = mstat.database_track_from_mpd(self.session, info)
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


class NewLibraryBuffer(Buffer):
    signals = Buffer.signals + ['update_playlist']

    def __init__(self, conf, session):
        self.conf = conf
        self.model = LibraryModel([])
        self.controller = LibraryController(self.model, conf, session)
        self.view = LibraryView(self.model, self.controller, conf)

        # OLD
        #self.show_score = conf.show_score()

        #self.session = session
        #self.commands = self.setup_commands()

        #self.anl = analytics.Analytics(conf)

        #self.orderers = [analytics.BaseOrder()]
        #self.default_orderers = list(self.init_default_orderers(conf))
        #self.searcher = None

        #self.suggestions = []

        #self.search_matches = []
        #self.current_search_index = None

        #self.list_view = self.suggestion_list()

        super(NewLibraryBuffer, self).__init__(self.view)

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
            'love': self.love_selection,
            'unlove': self.unlove_selection,
        })

        commands.update({
            name: self.orderer_func(orderer)
            for name, orderer in orderers.items()
        })

        return commands

    def setup_bindings(self):
        keybinds = super(NewLibraryBuffer, self).setup_bindings()

        if self.conf.esc_resets_orderers():
            keybinds.update({
                'esc': lambda: self.controller.reset_orderers(),
                'L': self.love_selection,
            })

        return keybinds

    def find_track_selection(self, track):
        o_widgets = (w.original_widget for w in self.list_view.body)
        match = (w for w in o_widgets
                 if isinstance(w, widget.SelectableTrack) and w.track == track)
        return next(match, None)

    def love_track(self, track, loved=True):
        selection = self.find_track_selection(track)
        logger.debug('Found: {}'.format(selection))
        self.love_tracks(selection, [track], loved=loved)

    def unlove_track(self, track):
        self.love_track(track, loved=False)

    def love_selection(self):
        current = self.list_view.focus.original_widget
        tracks = current.tracks()

        self.prompt = widget.Prompt(
            'Mark {} tracks loved? [Y/n]: '.format(len(tracks)),
            current,
            tracks)
        urwid.connect_signal(self.prompt, 'prompt_done',
                             self.complete_love_selection)
        footer = urwid.AttrMap(self.prompt, 'footer')
        self.update_footer(footer)
        self.update_focus('footer')

    def complete_love_selection(self, value, selection, tracks):
        urwid.disconnect_signal(self, self.prompt, 'prompt_done',
                                self.complete_love_selection)
        self.update_focus('body')

        if value is None:
            return
        elif value == '':
            value = 'y'

        if value.lower()[0] == 'y':
            self.love_tracks(selection, tracks)

    def love_tracks(self, selection, tracks, loved=True):
        fm = mstat.initialize_lastfm(self.conf)
        for track in tracks:
            mstat.set_track_loved(self.session, fm, track, loved=loved)

        self.session.commit()
        if selection is not None:
            selection.update_text()
        self.redraw()
        urwid.emit_signal(self, 'update_playlist')

    def unlove_selection(self):
        current = self.list_view.focus.original_widget
        tracks = current.tracks()

        self.prompt = widget.Prompt(
            'Mark {} tracks unloved? [Y/n]: '.format(len(tracks)),
            current,
            tracks)
        urwid.connect_signal(self.prompt, 'prompt_done',
                             self.complete_unlove_selection)
        footer = urwid.AttrMap(self.prompt, 'footer')
        self.update_footer(footer)
        self.update_focus('footer')

    def complete_unlove_selection(self, value, selection, tracks):
        urwid.disconnect_signal(self, self.prompt, 'prompt_done',
                                self.complete_love_selection)
        self.update_focus('body')

        if value is None:
            return
        elif value == '':
            value = 'y'

        if value.lower()[0] == 'y':
            self.unlove_tracks(selection, tracks)

    def unlove_tracks(self, selection, tracks):
        self.love_tracks(selection, tracks, loved=False)

    def orderer_func(self, orderer):
        def add_func(*args, **kwArgs):
            self.add_orderer(orderer, *args, **kwArgs)
        return add_func

    def suggestion_list(self):
        body = []
        for suggestion in self.suggestions:
            item = widget.SelectableAlbum(suggestion, self.show_score)

            urwid.connect_signal(item, ENQUEUE, self.enqueue_album)
            urwid.connect_signal(item, PLAY, self.play_album)

            body.append(urwid.AttrMap(item, 'album', 'focus album'))

        if not body:
            body = [urwid.AttrMap(urwid.Text('No albums found'), 'album')]

        albumlist = widget.AlbumList(self, urwid.SimpleFocusListWalker(body))
        urwid.connect_signal(albumlist, 'set_footer', self.update_footer)

        return albumlist

    def update_suggestions(self, *_args):
        logger.info('Update suggestions display')

        last_album = self.last_selected_album()

        logger.debug('Last album before update: {}'.format(last_album))

        self.suggestions = self.get_suggestions()

        self.list_view = self.suggestion_list()
        self.remember_focus(last_album)
        self.set_body(self.view)

    def last_selected_album(self):
        return None
        #if self.view is not None:
        #    try:
        #        idx = self.view.focus_position
        #        return self.suggestions[idx].album
        #    except IndexError:
        #        return None
        #else:
        #    return None

    def remember_focus(self, last_album):
        if last_album is None:
            return

        try:
            albums = (s.album for s in self.suggestions)
            album_idx = next(
                (i for i, album in enumerate(albums)
                 if last_album.id == album.id),
                None
            )
            if album_idx is not None:
                self.list_view.focus_position = album_idx
        except IndexError:
            return

    def get_suggestions(self):
        return self.anl.order_albums(self.session, self.orderers)

    def enqueue_album(self, album):
        self.enqueue_tracks(album.tracks)

    def play_album(self, album):
        self.play_tracks(album.tracks)

    def enqueue_track(self, track):
        self.enqueue_tracks([track])

    def play_track(self, track):
        self.play_tracks([track])

    def enqueue_tracks(self, tracks):
        mpd = mstat.initialize_mpd(self.conf)

        if tracks:
            logger.info('Enqueue {}'.format(album_text(tracks[0].album)))

        mpd_tracks = list(chain.from_iterable(
            mpd.listallinfo(track.filename) for track in tracks))

        for i, track in enumerate(mpd_tracks):
            track['track'] = track_num(track.get('track', i))

        sorted_tracks = sorted(mpd_tracks, key=lambda track: track['track'])
        return [mpd.addid(track['file']) for track in sorted_tracks]

    def play_tracks(self, tracks):
        mpd = mstat.initialize_mpd(self.conf)

        if tracks:
            logger.info('Play: {}'.format(album_text(tracks[0].album)))

        ids = self.enqueue_tracks(tracks)
        if ids:
            mpd.playid(ids[0])

    def add_orderer(self, orderer_class, *args, **kwArgs):
        logger.debug('Adding orderer: {}'.format(orderer_class.__name__))
        self.controller.add_orderer(orderer_class, *args, **kwArgs)

    def reset_orderers(self):
        logger.debug('Clear modes')
        if self.orderers != self.default_orderers:
            self.orderers = list(self.default_orderers)

            self.update_suggestions()
        else:
            logger.debug('Modes are already at default')
            logger.debug('Orderers: {}'.format(
                ', '.join(map(repr, self.orderers))))

        self.update_footer('suggestive')

    def clear_orderers(self):
        logger.debug('Clear all orderers')

        self.orderers = [analytics.BaseOrder()]
        logger.debug('Orderers: {}'.format(
            ', '.join(map(repr, self.orderers))))

        self.update_suggestions()
        self.update_footer('suggestive')


#class LibraryBuffer(Buffer):
#    signals = Buffer.signals + ['update_playlist']
#
#    def __init__(self, conf, session):
#        self.conf = conf
#        self.list_view = None
#
#        self.show_score = conf.show_score()
#
#        self.session = session
#        self.commands = self.setup_commands()
#
#        self.anl = analytics.Analytics(conf)
#
#        self.orderers = [analytics.BaseOrder()]
#        self.default_orderers = list(self.init_default_orderers(conf))
#        self.searcher = None
#
#        self.suggestions = []
#
#        self.search_matches = []
#        self.current_search_index = None
#
#        self.list_view = self.suggestion_list()
#
#        super(LibraryBuffer, self).__init__(self.list_view)
#        self.update_status('Library')
#
#    def search(self, searcher):
#        self.list_view.search(searcher)
#
#    def next_search(self):
#        self.list_view.next_search_item()
#
#    def orderer_command(self, orderer, defaults):
#        if not defaults:
#            return orderer
#
#        def orderer_func(*args, **kwArgs):
#            kwArgs.update(defaults)
#            return orderer(*args, **kwArgs)
#        return orderer_func
#
#    def init_default_orderers(self, conf):
#        order_commands = conf.default_orderers()
#        for cmd in order_commands:
#            self.execute_command(cmd)
#
#        return self.orderers
#
#    def init_custom_orderers(self, conf):
#        orderers = {}
#        for name, cmds in conf.custom_orderers().items():
#            def orderer_cmd(cmds=cmds):
#                for cmd in cmds:
#                    logger.debug('order: {}'.format(cmd))
#                    self.execute_command(cmd)
#            orderers[name] = orderer_cmd
#
#        return orderers
#
#    def setup_orderers(self):
#        return {
#            ('artist', 'ar'): (analytics.ArtistFilter, None),
#            ('album', 'al'): (analytics.AlbumFilter, None),
#            ('sort',): (analytics.SortOrder, {
#                'ignore_artist_the': self.conf.ignore_artist_the()
#            }),
#            ('loved', 'lo'): (analytics.FractionLovedOrder, None),
#            ('banned', 'bn'): (analytics.BannedOrder, None),
#            ('pc', 'playcount'): (analytics.PlaycountOrder, None),
#            ('mod', 'modified'): (analytics.ModifiedOrder, None),
#        }
#
#    def setup_commands(self):
#        init_orderers = self.setup_orderers()
#        orderers = dict(
#            chain.from_iterable(
#                ((command, self.orderer_command(func, defaults))
#                    for command in commands)
#                for commands, (func, defaults) in init_orderers.items()
#            )
#        )
#
#        commands = self.init_custom_orderers(self.conf)
#        commands.update({
#            'reset': self.reset_orderers,
#            'unorder': self.clear_orderers,
#            'unordered': self.clear_orderers,
#            'love': self.love_selection,
#            'unlove': self.unlove_selection,
#        })
#
#        commands.update({
#            name: self.orderer_func(orderer)
#            for name, orderer in orderers.items()
#        })
#
#        return commands
#
#    def setup_bindings(self):
#        keybinds = super(LibraryBuffer, self).setup_bindings()
#
#        if self.conf.esc_resets_orderers():
#            keybinds.update({
#                'esc': lambda: self.reset_orderers(),
#                'L': self.love_selection,
#                'U': self.unlove_selection,
#            })
#
#        return keybinds
#
#    def find_track_selection(self, track):
#        o_widgets = (w.original_widget for w in self.list_view.body)
#        match = (w for w in o_widgets
#                 if isinstance(w, widget.SelectableTrack)
#                 and w.track == track)
#        return next(match, None)
#
#    def love_track(self, track, loved=True):
#        selection = self.find_track_selection(track)
#        logger.debug('Found: {}'.format(selection))
#        self.love_tracks(selection, [track], loved=loved)
#
#    def unlove_track(self, track):
#        self.love_track(track, loved=False)
#
#    def love_selection(self):
#        current = self.list_view.focus.original_widget
#        tracks = current.tracks()
#
#        self.prompt = widget.Prompt(
#            'Mark {} tracks loved? [Y/n]: '.format(len(tracks)),
#            current,
#            tracks)
#        urwid.connect_signal(self.prompt, 'prompt_done',
#                             self.complete_love_selection)
#        footer = urwid.AttrMap(self.prompt, 'footer')
#        self.update_footer(footer)
#        self.update_focus('footer')
#
#    def complete_love_selection(self, value, selection, tracks):
#        urwid.disconnect_signal(self, self.prompt, 'prompt_done',
#                                self.complete_love_selection)
#        self.update_focus('body')
#
#        if value is None:
#            return
#        elif value == '':
#            value = 'y'
#
#        if value.lower()[0] == 'y':
#            self.love_tracks(selection, tracks)
#
#    def love_tracks(self, selection, tracks, loved=True):
#        fm = mstat.initialize_lastfm(self.conf)
#        for track in tracks:
#            mstat.set_track_loved(self.session, fm, track, loved=loved)
#
#        self.session.commit()
#        if selection is not None:
#            selection.update_text()
#        self.redraw()
#        urwid.emit_signal(self, 'update_playlist')
#
#    def unlove_selection(self):
#        current = self.list_view.focus.original_widget
#        tracks = current.tracks()
#
#        self.prompt = widget.Prompt(
#            'Mark {} tracks unloved? [Y/n]: '.format(len(tracks)),
#            current,
#            tracks)
#        urwid.connect_signal(self.prompt, 'prompt_done',
#                             self.complete_unlove_selection)
#        footer = urwid.AttrMap(self.prompt, 'footer')
#        self.update_footer(footer)
#        self.update_focus('footer')
#
#    def complete_unlove_selection(self, value, selection, tracks):
#        urwid.disconnect_signal(self, self.prompt, 'prompt_done',
#                                self.complete_love_selection)
#        self.update_focus('body')
#
#        if value is None:
#            return
#        elif value == '':
#            value = 'y'
#
#        if value.lower()[0] == 'y':
#            self.unlove_tracks(selection, tracks)
#
#    def unlove_tracks(self, selection, tracks):
#        self.love_tracks(selection, tracks, loved=False)
#
#    def orderer_func(self, orderer):
#        def add_func(*args, **kwArgs):
#            self.add_orderer(orderer, *args, **kwArgs)
#        return add_func
#
#    def suggestion_list(self):
#        body = []
#        for suggestion in self.suggestions:
#            item = widget.SelectableAlbum(suggestion, self.show_score)
#
#            urwid.connect_signal(item, ENQUEUE, self.enqueue_album)
#            urwid.connect_signal(item, PLAY, self.play_album)
#
#            body.append(urwid.AttrMap(item, 'album', 'focus album'))
#
#        if not body:
#            body = [urwid.AttrMap(urwid.Text('No albums found'), 'album')]
#
#        albumlist = widget.AlbumList(self, urwid.SimpleFocusListWalker(body))
#        urwid.connect_signal(albumlist, 'set_footer', self.update_footer)
#
#        return albumlist
#
#    def update_suggestions(self, *_args):
#        logger.info('Update suggestions display')
#
#        last_album = self.last_selected_album()
#
#        logger.debug('Last album before update: {}'.format(last_album))
#
#        self.suggestions = self.get_suggestions()
#
#        self.list_view = self.suggestion_list()
#        self.remember_focus(last_album)
#        self.set_body(self.list_view)
#
#    def last_selected_album(self):
#        if self.list_view is not None:
#            try:
#                idx = self.list_view.focus_position
#                return self.suggestions[idx].album
#            except IndexError:
#                return None
#        else:
#            return None
#
#    def remember_focus(self, last_album):
#        if last_album is None:
#            return
#
#        try:
#            albums = (s.album for s in self.suggestions)
#            album_idx = next(
#                (i for i, album in enumerate(albums)
#                 if last_album.id == album.id),
#                None
#            )
#            if album_idx is not None:
#                self.list_view.focus_position = album_idx
#        except IndexError:
#            return
#
#    def get_suggestions(self):
#        return self.anl.order_albums(self.session, self.orderers)
#
#    def enqueue_album(self, album):
#        self.enqueue_tracks(album.tracks)
#
#    def play_album(self, album):
#        self.play_tracks(album.tracks)
#
#    def enqueue_track(self, track):
#        self.enqueue_tracks([track])
#
#    def play_track(self, track):
#        self.play_tracks([track])
#
#    def enqueue_tracks(self, tracks):
#        mpd = mstat.initialize_mpd(self.conf)
#
#        if tracks:
#            logger.info('Enqueue {}'.format(album_text(tracks[0].album)))
#
#        mpd_tracks = list(chain.from_iterable(
#            mpd.listallinfo(track.filename) for track in tracks))
#
#        for i, track in enumerate(mpd_tracks):
#            track['track'] = track_num(track.get('track', i))
#
#        sorted_tracks = sorted(mpd_tracks, key=lambda track: track['track'])
#        return [mpd.addid(track['file']) for track in sorted_tracks]
#
#    def play_tracks(self, tracks):
#        mpd = mstat.initialize_mpd(self.conf)
#
#        if tracks:
#            logger.info('Play: {}'.format(album_text(tracks[0].album)))
#
#        ids = self.enqueue_tracks(tracks)
#        if ids:
#            mpd.playid(ids[0])
#
#    def add_orderer(self, orderer_class, *args, **kwArgs):
#        orderer = orderer_class(*args, **kwArgs)
#        try:
#            idx = list(map(type, self.orderers)).index(orderer)
#            self.orderers[idx] = orderer
#        except ValueError:
#            self.orderers.append(orderer)
#
#        logger.debug('Orderers: {}'.format(
#            ', '.join(map(repr, self.orderers))))
#
#        self.update_suggestions()
#
#    def reset_orderers(self):
#        logger.debug('Clear modes')
#        if self.orderers != self.default_orderers:
#            self.orderers = list(self.default_orderers)
#
#            self.update_suggestions()
#        else:
#            logger.debug('Modes are already at default')
#            logger.debug('Orderers: {}'.format(
#                ', '.join(map(repr, self.orderers))))
#
#        self.update_footer('suggestive')
#
#    def clear_orderers(self):
#        logger.debug('Clear all orderers')
#
#        self.orderers = [analytics.BaseOrder()]
#        logger.debug('Orderers: {}'.format(
#            ', '.join(map(repr, self.orderers))))
#
#        self.update_suggestions()
#        self.update_footer('suggestive')


class PlaylistBuffer(Buffer):
    signals = Buffer.signals + ['love_track', 'unlove_track']
    ITEM_FORMAT = '{artist} - {album} - {title}{suffix}'

    def __init__(self, conf, session):
        self.conf = conf
        self.session = session
        self.status_format = conf.playlist_status_format()
        self.searcher = None
        self.show_numbers = False
        self.move_prompt = None

        self.current_track = None

        self.format_keys = re.findall(r'\{(\w+)\}', self.ITEM_FORMAT)
        items, self.current_track = self.playlist_items()
        walker = urwid.SimpleFocusListWalker(items)
        self.playlist = widget.SuggestiveListBox(walker)
        urwid.connect_signal(self.playlist, 'set_footer', self.update_footer)
        super(PlaylistBuffer, self).__init__(self.playlist)

        self.update_status('Playlist')

    def search(self, searcher):
        self.playlist.search(searcher)

    def next_search(self):
        self.playlist.next_search_item()

    def will_accept_focus(self):
        mpd = mstat.initialize_mpd(self.conf)
        return len(mpd.playlistinfo()) > 0

    def setup_bindings(self):
        keybinds = super(PlaylistBuffer, self).setup_bindings()
        keybinds.update({
            #'c': self.clear_mpd_playlist,
            'd': self.delete_track,
            'enter': self.play_track,
            'm': self.move_track,
            'L': self.love_track,
        })

        return keybinds

    def setup_commands(self):
        return {
            'love': self.love_track,
            'unlove': self.unlove_track,
        }

    def move_track(self):
        self.show_numbers = True
        self.update()
        logger.debug('Start playlist move')

        self.move_prompt = widget.PlaylistMovePrompt(
            self.playlist.focus_position)
        urwid.connect_signal(self.move_prompt, 'prompt_done',
                             self.complete_move)
        urwid.connect_signal(self.move_prompt, 'update_index',
                             self.update_index)

        self.update_footer(urwid.AttrMap(self.move_prompt, 'footer'))
        self.update_focus('footer')

    def complete_move(self, value):
        urwid.disconnect_signal(self, self.move_prompt, 'prompt_done',
                                self.complete_move)
        self.update_focus('body')
        self.show_numbers = False

        try:
            new_index = int(value)
            logger.debug('Moving playlist track from {} to {}'.format(
                self.playlist.focus_position, new_index))

            mpd = mstat.initialize_mpd(self.conf)
            mpd.move(self.playlist.focus_position, new_index)
        except (TypeError, ValueError):
            logger.error('Invalid move index: {}'.format(value))

        self.update()

    def update_index(self, current, index):
        try:
            items = self.playlist.body
            n_items = len(items)

            if index >= n_items:
                raise IndexError

            logger.debug('Temporary move from {} to {}'.format(
                current, index))

            if index > current:
                focus = items[current]
                logger.debug('Current focus: {}'.format(
                    focus.original_widget._w.get_text()))
                items.insert(index + 1, focus)
                items.pop(current)
            elif index < current:
                focus = items.pop(current)
                items.insert(index, focus)
        except IndexError:
            logger.error('Index out of range')

    def delete_track(self):
        try:
            current_position = self.playlist.focus_position
        except IndexError:
            return

        if current_position is not None:
            mpd = mstat.initialize_mpd(self.conf)
            n_items = len(mpd.playlistinfo())
            if n_items:
                self.playlist.body.pop(current_position)
                mpd.delete(current_position)
                if n_items == 1:
                    self.update()

    def play_track(self):
        current_position = self.playlist.focus_position

        if current_position is not None:
            mpd = mstat.initialize_mpd(self.conf)
            mpd.play(current_position)

    def format_track(self, track):
        db_track = mstat.database_track_from_mpd(self.session, track)
        info = db_track.lastfm_info
        if info is None:
            suffix = ''
        elif info.loved:
            suffix = ' [L]'
        elif info.banned:
            suffix = ' [B]'
        else:
            suffix = ''

        replace = {key: 'Unknown' for key in self.format_keys}
        replace.update(track)
        replace.update(suffix=suffix)

        return self.ITEM_FORMAT.format(**replace)

    def now_playing_index(self, mpd):
        current = mpd.currentsong()
        if current and 'pos' in current:
            return int(current['pos'])
        else:
            return None

    def decorated_playlist_items(self, playlist, now_playing, digits):
        items = []

        for position, track in enumerate(playlist):
            pieces = [self.format_track(track)]
            if self.show_numbers and digits:
                # Mark current position as 'C'
                if position == self.playlist.focus_position:
                    position = 'C'

                number = str(position).ljust(digits + 1, ' ')
                pieces.insert(0, ('bumper', number))

            text = widget.PlaylistItem(pieces)
            if position == now_playing:
                styles = ('playing', 'playing focus')
            else:
                styles = ('playlist', 'focus playlist')

            items.append(urwid.AttrMap(text, *styles))

        return items

    def track_changed(self):
        mpd = mstat.initialize_mpd(self.conf)
        return self.current_track != self.now_playing_index(mpd)

    def playlist_items(self):
        mpd = mstat.initialize_mpd(self.conf)

        playlist = mpd.playlistinfo()
        now_playing = self.now_playing_index(mpd)

        n_items = len(playlist)
        digits = (floor(log10(n_items)) + 1) if n_items else 0

        body = self.decorated_playlist_items(playlist, now_playing, digits)

        if not body:
            text = urwid.Text('Playlist is empty')
            body.append(urwid.AttrMap(text, 'playlist'))

        return body, now_playing

    def update(self, *args):
        current_position = 0
        try:
            current_position = self.playlist.focus_position
        except IndexError:
            pass

        items, self._current_track = self.playlist_items()

        # TODO: Do we really have to clear the playlist every time?
        self.clear_playlist()
        self.playlist.body.extend(items)

        try:
            self.playlist.focus_position = current_position
        except IndexError:
            try:
                self.playlist.focus_position = current_position - 1
            except IndexError:
                pass

        self.update_playing_status()
        self.redraw()

    def update_playing_status(self):
        self.update_status(self.status_text())

    def status_params(self, status, track):
        elapsed_time = int(status.get('time', '0').split(':')[0])
        total_time = int(track.get('time', '0').split(':')[0])

        elapsed_min, elapsed_sec = elapsed_time // 60, elapsed_time % 60
        total_min, total_sec = total_time // 60, total_time % 60

        state = status['state']
        if state == 'play':
            state = 'Now Playing'

        return {
            'status': state[0].upper() + state[1:],
            'time_elapsed': '{}:{}'.format(
                elapsed_min,
                str(elapsed_sec).rjust(2, '0')
            ),
            'time_total': '{}:{}'.format(
                total_min,
                str(total_sec).rjust(2, '0')
            ),
            'title': track.get('title', 'Unknown Track'),
            'artist': track.get('artist', 'Unknown Artist'),
            'album_artist': track.get('album_artist', 'Unknown Artist'),
            'album': track.get('album', 'Unknown Album'),
            'filename': track['file'],
            'track': track.get('track', 'Unknown'),
            'date': track.get('date', 'Unknown'),
        }

    def status_text(self):
        mpd = mstat.initialize_mpd(self.conf)
        status = mpd.status()

        text = ''

        songid = status.get('songid')
        if songid:
            track = mpd.playlistid(songid)
            if track:
                params = self.status_params(status, track[0])
                text = self.status_format.format(**params)

        return 'Playlist | ' + text

    def clear_playlist(self):
        del self.playlist.body[:]

    def clear_mpd_playlist(self):
        logger.debug('clearing list')

        mpd = mstat.initialize_mpd(self.conf)
        mpd.stop()
        mpd.clear()

        self.update()

    def love_track(self):
        current_position = self.playlist.focus_position

        if current_position is None:
            return

        track = mstat.get_playlist_track(self.session, self.conf,
                                         current_position)
        if track is None:
            logger.debug('Could not find track to love')
            return

        self.prompt = widget.Prompt(
            'Mark track loved? [Y/n]: ',
            self.playlist.focus.original_widget,
            track)

        urwid.connect_signal(self.prompt, 'prompt_done',
                             self.complete_love_track)

        footer = urwid.AttrMap(self.prompt, 'footer')

        self.update_footer(footer)
        self.update_focus('footer')

    def complete_love_track(self, value, selection, track):
        urwid.disconnect_signal(self, self.prompt, 'prompt_done',
                                self.complete_love_track)
        self.update_focus('body')

        if value is None:
            return
        elif value == '':
            value = 'y'

        if value.lower()[0] == 'y':
            urwid.emit_signal(self, 'love_track', track)

    def unlove_track(self):
        current_position = self.playlist.focus_position

        if current_position is None:
            return

        track = mstat.get_playlist_track(self.session, self.conf,
                                         current_position)
        if track is None:
            logger.debug('Could not find track to unlove')
            return

        self.prompt = widget.Prompt(
            'Mark track unloved? [Y/n]: ',
            self.playlist.focus.original_widget,
            track)

        urwid.connect_signal(self.prompt, 'prompt_done',
                             self.complete_unlove_track)

        footer = urwid.AttrMap(self.prompt, 'footer')

        self.update_footer(footer)
        self.update_focus('footer')

    def complete_unlove_track(self, value, selection, track):
        urwid.disconnect_signal(self, self.prompt, 'prompt_done',
                                self.complete_unlove_track)
        self.update_focus('body')

        if value is None:
            return
        elif value == '':
            value = 'y'

        if value.lower()[0] == 'y':
            urwid.emit_signal(self, 'unlove_track', track)

    def load_playlist(self, name=None):
        if name is None:
            raise CommandError('Missing parameter: name')

        mpd = mstat.initialize_mpd(self.conf)
        self.clear_mpd_playlist()

        try:
            mpd.load(name)
            self.update_footer('Loaded playlist {}'.format(name))
            return True
        except MpdCommandError as ex:
            logger.debug(ex)
            raise CommandError("Unable to load playlist '{}'".format(
                name))

    def save_playlist(self, name=None):
        if name is None:
            raise CommandError('Missing parameter: name')

        mpd = mstat.initialize_mpd(self.conf)

        try:
            mpd.rm(name)
            mpd.save(name)
            self.update_footer('Saved playlist {}'.format(name))
            return True
        except MpdCommandError as ex:
            logger.debug(ex)
            raise CommandError("Unable to save playlist '{}'".format(
                name))
