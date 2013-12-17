"""
Main application/UI
"""

from suggestive.threads import (
    MpdWatchThread, DatabaseUpdateThread, ScrobbleInitializeThread)
from suggestive.analytics import (
    Analytics, FractionLovedOrder, BannedOrder, ArtistFilter, AlbumFilter,
    SortOrder, PlaycountOrder, BaseOrder, ModifiedOrder)
from suggestive.config import Config
from suggestive.command import CommanderEdit, Commandable, typed
from suggestive.widget import (
    Prompt, SuggestiveListBox, SelectableAlbum, SelectableTrack, PlaylistItem)
import suggestive.bindings as bindings
import suggestive.mstat as mstat
from suggestive.util import album_text
import suggestive.migrate as migrate
from suggestive.search import LazySearcher
from suggestive.error import CommandError


from math import floor, log10
import argparse
import urwid
import logging
from logging.handlers import RotatingFileHandler
import threading
import re
import os.path
import sys
from itertools import chain, groupby
from mpd import CommandError as MpdCommandError

logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())

MEGABYTE = 1024 * 1024


class PlaylistMovePrompt(Prompt):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['update_index']

    def __init__(self, original_position):
        super(PlaylistMovePrompt, self).__init__('Move item to: ')
        self.input_buffer = ''
        self.original_position = original_position
        self.current_position = original_position

    def update_index(self, index=None):
        try:
            index = self.position() if index is None else index
            urwid.emit_signal(self, 'update_index', self.current_position,
                              index)
            self.current_position = index
        except IndexError:
            pass

    def input(self, char):
        self.input_buffer += char
        self.update_index()

    def backspace(self):
        self.input_buffer = self.input_buffer[:-1]
        self.update_index()

    def position(self):
        if not self.input_buffer:
            return self.original_position

        try:
            return int(self.input_buffer)
        except (TypeError, ValueError):
            logger.warn('Bad move index: {}'.format(self.input_buffer))
            raise IndexError('Invalid move index: {}'.format(
                self.input_buffer))

    def keypress(self, size, key):
        if len(key) == 1:
            self.input(key)
        elif key == 'backspace':
            self.backspace()

        return super(PlaylistMovePrompt, self).keypress(size, key)


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


class ScrobbleListWalker(urwid.ListWalker):

    def __init__(self, conf, session, previous=None, plays=None):
        if plays is None:
            plays = []

        self.focus = 0
        self.items = []
        self.session = session

        self.items.extend(self._generate_plays(plays))

        if isinstance(previous, ScrobbleListWalker):
            self._load_more(previous.size())
        else:
            self._load_more(conf.initial_scrobbles())

    def __iter__(self):
        return iter(self.items)

    def size(self):
        return len(self.items)

    @classmethod
    def _icon(cls, scrobble):
        info = scrobble.scrobble_info
        text = '{} - {}'.format(info.artist, info.title)

        icon = urwid.SelectableIcon(text)
        return urwid.AttrMap(icon, 'scrobble', 'focus scrobble')

    @classmethod
    def _day(cls, scrobble):
        return scrobble.time.strftime('%Y-%m-%d')

    def __len__(self):
        return len(self.items)

    def _play(self, track):
        text = '{} - {}'.format(track.artist.name, track.name)

        icon = urwid.SelectableIcon(text)
        return urwid.AttrMap(icon, 'scrobble', 'focus scrobble')

    def _generate_plays(self, tracks):
        if not tracks:
            return []

        plays = [self._play(track) for track in tracks]
        header = urwid.AttrMap(urwid.Text('Plays'), 'scrobble date')

        return [header] + plays

    def _generate_icons(self, scrobbles):
        widgets = (i.original_widget for i in reversed(self.items))
        last_day = next(
            (w.get_text()[0] for w in widgets
             if not isinstance(w, urwid.SelectableIcon)),
            None)

        for day, group in groupby(scrobbles, self._day):
            group = list(group)
            if day != last_day:
                last_day = day
                yield urwid.AttrMap(urwid.Text(day), 'scrobble date')

            for scrobble in group:
                yield self._icon(scrobble)

    def _load_more(self, position):
        n_items = len(self.items)
        n_load = 1 + position - n_items
        scrobbles = mstat.get_scrobbles(self.session, n_load, n_items)

        #self.items.extend([self._icon(scrobble) for scrobble in items])
        self.items.extend(list(self._generate_icons(scrobbles)))

    def __getitem__(self, idx):
        return urwid.SelectableIcon(str(idx))

    def get_focus(self):
        return self._get(self.focus)

    def set_focus(self, focus):
        self.focus = focus
        self._modified()

    def get_next(self, current):
        return self._get(current + 1)

    def get_prev(self, current):
        return self._get(current - 1)

    def _get(self, pos):
        if pos < 0:
            return None, None

        if pos >= len(self.items):
            self._load_more(pos)

        return self.items[pos], pos


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
        return SuggestiveListBox(
            ScrobbleListWalker(self.conf, self.session, previous, plays))

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


class LibraryBuffer(Buffer):
    signals = Buffer.signals + ['update_playlist']

    def __init__(self, conf, session):
        self.conf = conf
        self.list_view = None

        self.show_score = conf.show_score()

        self.session = session
        self.commands = self.setup_commands()

        self.anl = Analytics(conf)

        self.orderers = [BaseOrder()]
        self.default_orderers = list(self.init_default_orderers(conf))
        self.searcher = None

        self.suggestions = []

        self.search_matches = []
        self.current_search_index = None

        self.list_view = self.suggestion_list()

        super(LibraryBuffer, self).__init__(self.list_view)
        self.update_status('Library')

    def search(self, searcher):
        self.list_view.search(searcher)

    def next_search(self):
        self.list_view.next_search_item()

    def orderer_command(self, orderer, defaults):
        if not defaults:
            return orderer

        def orderer_func(*args, **kwArgs):
            kwArgs.update(defaults)
            return orderer(*args, **kwArgs)
        return orderer_func

    def init_default_orderers(self, conf):
        order_commands = conf.default_orderers()
        for cmd in order_commands:
            self.execute_command(cmd)

        return self.orderers

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
            ('artist', 'ar'): (ArtistFilter, None),
            ('album', 'al'): (AlbumFilter, None),
            ('sort',): (SortOrder, {
                'ignore_artist_the': self.conf.ignore_artist_the()
            }),
            ('loved', 'lo'): (FractionLovedOrder, None),
            ('banned', 'bn'): (BannedOrder, None),
            ('pc', 'playcount'): (PlaycountOrder, None),
            ('mod', 'modified'): (ModifiedOrder, None),
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
            'reset': self.reset_orderers,
            'unorder': self.clear_orderers,
            'unordered': self.clear_orderers,
            'love': self.love_selection,
            'unlove': self.unlove_selection,
        })

        commands.update({
            name: self.orderer_func(orderer)
            for name, orderer in orderers.items()
        })

        return commands

    def find_track_selection(self, track):
        o_widgets = (w.original_widget for w in self.list_view.body)
        match = (w for w in o_widgets
                 if isinstance(w, SelectableTrack) and w.track == track)
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

        self.prompt = Prompt(
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

        self.prompt = Prompt(
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

    def setup_bindings(self):
        keybinds = super(LibraryBuffer, self).setup_bindings()

        if self.conf.esc_resets_orderers():
            keybinds.update({
                'esc': lambda: self.reset_orderers(),
            })

        return keybinds

    def suggestion_list(self):
        body = []
        for suggestion in self.suggestions:
            item = SelectableAlbum(suggestion, self.show_score)

            urwid.connect_signal(item, 'enqueue', self.enqueue_album)
            urwid.connect_signal(item, 'play', self.play_album)

            body.append(urwid.AttrMap(item, 'album', 'focus album'))

        if not body:
            body = [urwid.AttrMap(urwid.Text('No albums found'), 'album')]

        albumlist = AlbumList(self, urwid.SimpleFocusListWalker(body))
        urwid.connect_signal(albumlist, 'set_footer', self.update_footer)

        return albumlist

    def update_suggestions(self, *_args):
        logger.info('Update suggestions display')

        last_album = self.last_selected_album()

        logger.debug('Last album before update: {}'.format(last_album))

        self.suggestions = self.get_suggestions()

        self.list_view = self.suggestion_list()
        self.remember_focus(last_album)
        self.set_body(self.list_view)

    def last_selected_album(self):
        if self.list_view is not None:
            try:
                idx = self.list_view.focus_position
                return self.suggestions[idx].album
            except IndexError:
                return None
        else:
            return None

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
            trackno = str(track.get('track', i))
            trackno = re.sub(r'(\d+)/\d+', r'\1', trackno)
            track['track'] = int(trackno)

        sorted_tracks = sorted(mpd_tracks, key=lambda track: track['track'])
        return [mpd.addid(track['file']) for track in sorted_tracks]

    def play_tracks(self, tracks):
        mpd = mstat.initialize_mpd(self.conf)

        if tracks:
            logger.info('Play: {}'.format(album_text(tracks[0].album)))

        mpd.clear()
        ids = self.enqueue_tracks(tracks)
        if ids:
            mpd.playid(ids[0])

    def add_orderer(self, orderer_class, *args, **kwArgs):
        orderer = orderer_class(*args, **kwArgs)
        try:
            idx = list(map(type, self.orderers)).index(orderer)
            self.orderers[idx] = orderer
        except ValueError:
            self.orderers.append(orderer)

        logger.debug('Orderers: {}'.format(
            ', '.join(map(repr, self.orderers))))

        self.update_suggestions()

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

        self.orderers = [BaseOrder()]
        logger.debug('Orderers: {}'.format(
            ', '.join(map(repr, self.orderers))))

        self.update_suggestions()
        self.update_footer('suggestive')


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

        self.format_keys = re.findall(r'\{(\w+)\}', self.ITEM_FORMAT)
        walker = urwid.SimpleFocusListWalker(self.playlist_items())
        self.playlist = SuggestiveListBox(walker)
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

        self.move_prompt = PlaylistMovePrompt(self.playlist.focus_position)
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

            #self.playlist.body.insert(index, self.playlist.focus)
            #self.playlist.body.pop(current)
        except IndexError:
            logger.error('Index out of range')

    def delete_track(self):
        current_position = self.playlist.focus_position

        if current_position is not None:
            mpd = mstat.initialize_mpd(self.conf)
            mpd.delete(current_position)
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

            text = PlaylistItem(pieces)
            if position == now_playing:
                styles = ('playing', 'playing focus')
            else:
                styles = ('playlist', 'focus playlist')

            items.append(urwid.AttrMap(text, *styles))

        return items

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

        return body

    def update(self, *args):
        current_position = 0
        try:
            current_position = self.playlist.focus_position
        except IndexError:
            pass

        items = self.playlist_items()

        self.clear_playlist()
        self.playlist.body.extend(items)

        try:
            self.playlist.focus_position = current_position
        except IndexError:
            try:
                self.playlist.focus_position = current_position - 1
            except IndexError:
                pass

        self.update_status(self.status_text())
        self.redraw()

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

        self.prompt = Prompt(
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

        self.prompt = Prompt(
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


class MainWindow(urwid.Frame):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['set_footer', 'set_focus']

    def __init__(self, conf, *args, **kwArgs):
        super(MainWindow, self).__init__(*args, **kwArgs)
        self.conf = conf

        # Signals
        urwid.connect_signal(self, 'set_footer', self.update_footer)
        urwid.connect_signal(self, 'set_focus', self.update_focus)

    def update_footer(self, footer, focus=False):
        self.set_footer(footer)
        if focus:
            self.set_focus('footer')

    def update_focus(self, to_focus):
        self.set_focus(to_focus)


class Application(Commandable):
    def __init__(self, conf, session):
        self.conf = conf
        self.session = session

        self.quit_event = threading.Event()

        self.anl = Analytics(conf)

        self.suggestions = []

        self.search_matches = []
        self.current_search_index = None

        self.orientation = self.conf.orientation()

        if self.orientation == 'vertical':
            self.buffers = VerticalBufferList()
        else:
            self.buffers = HorizontalBufferList()

        self.top = MainWindow(conf, urwid.AttrMap(self.buffers, 'footer'))
        self.event_loop = self.main_loop()

        # Initialize buffers
        self.library_buffer = self.create_library_buffer()
        self.playlist_buffer = self.create_playlist_buffer()
        self.scrobble_buffer = self.create_scrobble_buffer()

        urwid.connect_signal(
            self.library_buffer,
            'update_playlist',
            self.playlist_buffer.update)
        urwid.connect_signal(
            self.playlist_buffer,
            'love_track',
            self.library_buffer.love_track)
        urwid.connect_signal(
            self.playlist_buffer,
            'unlove_track',
            self.library_buffer.unlove_track)

        self.setup_buffers()
        self.bindings = self.setup_bindings()
        self.commands = self.setup_commands()

        self.update_footer_text('suggestive')
        self.playing_update()

        if conf.update_on_startup():
            self.start_db_update()

    def setup_buffers(self):
        default_buffers = self.conf.default_buffers()

        if 'library' in default_buffers:
            self.buffers.add(self.library_buffer)
            self.library_buffer.active = True
        if 'playlist' in default_buffers:
            self.buffers.add(self.playlist_buffer)
            self.playlist_buffer.active = True
        if 'scrobbles' in default_buffers:
            self.buffers.add(self.scrobble_buffer)
            self.scrobble_buffer.active = True

    def change_orientation(self, orientation=None):
        if orientation is None:
            orientation = ('vertical' if self.orientation == 'horizontal'
                           else 'horizontal')

        if orientation == 'vertical':
            buffers = VerticalBufferList()
        else:
            buffers = HorizontalBufferList()

        if self.library_buffer.active:
            buffers.add(self.library_buffer)
        if self.playlist_buffer.active:
            buffers.add(self.playlist_buffer)
        if self.scrobble_buffer.active:
            buffers.add(self.scrobble_buffer)

        self.orientation = orientation
        self.buffers = buffers
        self.top.body = self.buffers

        self.top.body = urwid.AttrMap(self.buffers, 'footer')

    def update_footer(self, value, error=False):
        if isinstance(value, str):
            self.update_footer_text(value, error=error)
        else:
            self.top.update_footer(value)

    def update_footer_text(self, value, error=False):
        text = urwid.AttrMap(
            urwid.Text(value),
            'footer error' if error else 'footer'
        )
        self.top.update_footer(text)

    def create_library_buffer(self):
        buf = LibraryBuffer(self.conf, self.session)
        urwid.connect_signal(buf, 'set_focus', self.top.update_focus)
        urwid.connect_signal(buf, 'set_footer', self.update_footer)
        urwid.connect_signal(buf, 'redraw', self.event_loop.draw_screen)

        buf.update_suggestions()

        return buf

    def create_playlist_buffer(self):
        buf = PlaylistBuffer(self.conf, self.session)
        urwid.connect_signal(buf, 'set_focus', self.top.update_focus)
        urwid.connect_signal(buf, 'set_footer', self.update_footer)
        urwid.connect_signal(buf, 'redraw', self.event_loop.draw_screen)

        return buf

    def create_scrobble_buffer(self):
        buf = ScrobbleBuffer(self.conf, self.session)
        urwid.connect_signal(buf, 'set_focus', self.top.update_focus)
        urwid.connect_signal(buf, 'set_footer', self.update_footer)
        urwid.connect_signal(buf, 'redraw', self.event_loop.draw_screen)

        return buf

    def open_playlist(self):
        if self.playlist_buffer.active:
            logger.debug('Close playlist')
            if self.buffers.remove(self.playlist_buffer):
                self.playlist_buffer.active = False
        else:
            logger.debug('Open playlist')
            self.buffers.add(self.playlist_buffer)
            self.playlist_buffer.active = True

    def open_library(self):
        if self.library_buffer.active:
            logger.debug('Close playlist')
            if self.buffers.remove(self.library_buffer):
                self.library_buffer.active = False
        else:
            logger.debug('Open playlist')
            self.buffers.add(self.library_buffer)
            self.library_buffer.active = True

    def open_scrobbles(self):
        if self.scrobble_buffer.active:
            logger.debug('Close scrobbles')
            if self.buffers.remove(self.scrobble_buffer):
                self.scrobble_buffer.active = False
        else:
            logger.debug('Open scrobbles')
            self.buffers.add(self.scrobble_buffer)
            self.scrobble_buffer.active = True

    def start_db_update(self):
        self.library_buffer.update_status('Library (updating...)')

        update_thread = DatabaseUpdateThread(
            self.conf, self.update_library_event, self.quit_event)
        update_thread.daemon = False
        update_thread.start()

    def start_scrobble_initialize(self):
        scrobble_thread = ScrobbleInitializeThread(
            self.conf, self.quit_event)
        scrobble_thread.daemon = False
        scrobble_thread.start()

    def start_mpd_watch_thread(self):
        thread = MpdWatchThread(
            self.conf, self.update_playlist_event, self.quit_event)
        thread.daemon = True
        thread.start()

    def update_library_event(self):
        self.session.expire_all()
        self.event_loop.set_alarm_in(0, self.library_buffer.update_suggestions)
        self.event_loop.set_alarm_in(0, self.scrobble_buffer.update)
        self.library_buffer.update_status('Library')

    def update_playlist_event(self):
        self.event_loop.set_alarm_in(0, self.playlist_buffer.update)
        self.event_loop.set_alarm_in(0, self.scrobble_buffer.update)

    def dispatch(self, key):
        if key in self.bindings:
            func = self.bindings[key]
            func()
            return True
        else:
            return False

    def exit(self):
        if self.conf.save_playlist_on_close():
            playlist = self.conf.playlist_save_name()
            self.playlist_buffer.save_playlist(playlist)

        self.quit_event.set()
        raise urwid.ExitMainLoop()

    def setup_bindings(self):
        return {
            'q': lambda: self.exit(),
            'u': lambda: self.start_db_update(),
            ':': lambda: self.start_command(),
            'p': lambda: self.pause(),
            'ctrl w': lambda: self.buffers.next_buffer(),
            'c': self.clear_playlist,
            'r': self.update_library_event,
            '/': lambda: self.start_search(),
            '?': lambda: self.start_search(reverse=True),
        }

    def setup_commands(self):
        return {
            'playlist': self.open_playlist,
            'library': self.open_library,
            'scrobbles': self.open_scrobbles,
            'q': self.exit,
            'orientation': self.change_orientation,
            'or': self.change_orientation,
            'score': self.toggle_show_score,
            'save': self.playlist_buffer.save_playlist,
            'load': self.playlist_buffer.load_playlist,
        }

    def clear_playlist(self):
        self.playlist_buffer.clear_mpd_playlist()
        if self.buffers.current_buffer() is self.playlist_buffer:
            self.buffers.next_buffer()

    @typed(show=bool)
    def toggle_show_score(self, show=None):
        current = self.library_buffer.show_score
        logger.debug('Toggle show score; current={}, show={}'.format(
            current, show))
        if show is None or bool(show) != current:
            self.library_buffer.show_score = not current
            self.library_buffer.update_suggestions()

    def pause(self):
        mpd = mstat.initialize_mpd(self.conf)
        mpd.pause()

    def start_search(self, reverse=False):
        self.edit = Prompt('/')
        urwid.connect_signal(self.edit, 'prompt_done', self.search_done,
                             reverse)
        footer = urwid.AttrMap(self.edit, 'footer')
        self.update_footer(footer)
        self.top.update_focus('footer')

    def search_done(self, pattern, reverse=False):
        logger.debug('Reverse: {}'.format(reverse))
        self.top.update_focus('body')
        urwid.disconnect_signal(self, self.edit, 'prompt_done',
                                self.search_done)

        if pattern:
            logger.info('SEARCH FOR: {}'.format(pattern))
            searcher = LazySearcher(pattern, reverse=reverse)

            for buf in self.buffers:
                buf.search(searcher)

            self.buffers.current_buffer().next_search()

    def start_command(self):
        self.edit = CommanderEdit(self.command_history)
        urwid.connect_signal(self.edit, 'command_done', self.command_done)
        urwid.connect_signal(self.edit, 'autocomplete', self.autocomplete)
        footer = urwid.AttrMap(self.edit, 'footer')
        self.top.set_footer(footer)
        self.top.set_focus('footer')

    def autocomplete(self, partial):
        all_commands = dict(
            list(self.commands.items()) +
            list(self.buffers.current_buffer().commands.items())
        )
        matches = [cmd for cmd in all_commands if cmd.startswith(partial)]
        logger.debug('Matching: {}'.format(matches))
        if matches:
            self.edit.set_edit_text(matches[0])
            self.edit.set_edit_pos(len(matches[0]))

    def command_done(self, command):
        self.top.set_focus('body')
        urwid.disconnect_signal(self, self.edit, 'command_done',
                                self.command_done)

        if command:
            try:
                current_buf = self.buffers.current_buffer()
                success = current_buf.execute_command(command)
                if not success:
                    success = self.execute_command(command)

                if not success:
                    self.update_footer_text(
                        "Unable to execute command '{}'".format(command),
                        error=True)
            except TypeError as err:
                logger.debug('TypeError: {}'.format(err))
                self.update_footer_text(
                    "Invalid arguments for command '{}'".format(command),
                    error=True)
            except CommandError as ex:
                logger.debug(ex)
                self.update_footer_text(ex.message, error=True)

    def setup_palette(self):
        return self.conf.palette()

    def setup_term(self, screen):
        colormode = 256 if self.conf.use_256_colors() else 88
        screen.set_terminal_properties(colors=colormode)

    def playing_update(self, *args):
        # TODO: Only do this on mpd change
        text = self.playlist_buffer.status_text()
        self.playlist_buffer.update_status(text)
        self.event_loop.set_alarm_in(1, self.playing_update)

    def main_loop(self):
        mainloop = urwid.MainLoop(
            self.top,
            palette=self.setup_palette(),
            unhandled_input=self.dispatch,
            handle_mouse=False,
        )

        self.setup_term(mainloop.screen)

        # Start threads
        self.start_mpd_watch_thread()
        self.start_scrobble_initialize()

        return mainloop


class AlbumList(SuggestiveListBox):
    def __init__(self, app, *args, **kwArgs):
        super(AlbumList, self).__init__(*args, **kwArgs)

        # TODO: dirty, filthy hack. Do bindings externally and pass in conf
        self.app = app

        self._command_map = bindings.AlbumListCommands

    def sort_tracks(self, tracks):
        track_and_num = []
        mpd = mstat.initialize_mpd(self.app.conf)

        for i, track in enumerate(tracks):
            try:
                mpd_track = mpd.listallinfo(track.filename)
            except MpdCommandError:
                continue

            if not mpd_track:
                continue
            trackno = str(mpd_track[0].get('track', i))
            trackno = re.sub(r'(\d+)/\d+', r'\1', trackno)

            track_and_num.append((int(trackno), track))

        return sorted(track_and_num, key=lambda pair: pair[0])

    def expand_album(self, album_widget):
        current = self.focus_position
        album = album_widget.original_widget.album

        sorted_tracks = self.sort_tracks(album.tracks)
        for track_no, track in reversed(sorted_tracks):
            track_widget = SelectableTrack(album_widget, track, track_no)

            urwid.connect_signal(track_widget, 'enqueue',
                                 self.app.enqueue_track)
            urwid.connect_signal(track_widget, 'play', self.app.play_track)

            item = urwid.AttrMap(track_widget, 'track', 'focus track')
            self.body.insert(current + 1, item)

        album_widget.original_widget.expanded = True
        self.set_focus_valign('top')

    def collapse_album(self, album_widget):
        current = self.focus_position
        album_index = self.body.index(album_widget, 0, current + 1)

        logger.debug('Album index: {}'.format(album_index))

        album = album_widget.original_widget.album
        for i in range(len(album.tracks)):
            track_widget = self.body[album_index + 1]
            if isinstance(track_widget.original_widget, SelectableTrack):
                self.body.pop(album_index + 1)
            else:
                logger.error('Item #{} is not a track'.format(i))

        album_widget.original_widget.expanded = False

    def toggle_expand(self):
        widget = self.focus

        if isinstance(widget.original_widget, SelectableTrack):
            widget = widget.original_widget.parent

        if widget.original_widget.expanded:
            self.collapse_album(widget)
        else:
            self.expand_album(widget)

        album = widget.original_widget.album

        logger.info('Expand: {} ({} tracks)'.format(
            album_text(album),
            len(album.tracks)))

    def keypress(self, size, key):
        cmd = self._command_map[key]
        if cmd == 'expand':
            self.toggle_expand()
        else:
            return super(AlbumList, self).keypress(size, key)

        # Necessary to get list focus to redraw
        super(AlbumList, self).keypress(size, None)

        return True


def initialize_logging(conf):
    handler = RotatingFileHandler(
        conf.log_file(),
        mode='a',
        backupCount=3,
        maxBytes=1 * MEGABYTE,
    )

    fmt = logging.Formatter(
        '%(asctime)s %(levelname)s (%(name)s)| %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(fmt)
    handler.setLevel(conf.log_level())

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(conf.log_level())

    # Disable other loggers
    logging.getLogger('mpd').setLevel(logging.ERROR)
    logging.getLogger('requests').setLevel(logging.ERROR)


def run(args):
    conf = Config(args)
    initialize_logging(conf)

    msg = conf.check_config()
    if msg is not None:
        print(msg)
        sys.exit(1)

    if not os.path.exists(conf.database()):
        print('Music database not found; initializing...')
        migrate.initialize_database(conf)
        mstat.update_mpd(conf)

    # Migrate to latest database configuration
    migrate.migrate(conf)

    # Request API write access from user
    session_file = conf.lastfm_session_file()
    if conf.lastfm_secret_key() and not os.path.exists(session_file):
        fm = mstat.initialize_lastfm(conf)
        assert(fm.session_key is not None)

    with mstat.session_scope(conf, commit=False) as main_session:
        try:
            logger.info('Starting event loop')
            app = Application(conf, main_session)
            app.event_loop.run()
        except KeyboardInterrupt:
            logger.error("Exited via keyboard interrupt; next time, use 'q'")
        except Exception as err:
            import traceback
            logger.critical('Encountered exception: {}'.format(err))
            logger.critical(traceback.format_exc())
            raise


def main():
    parser = argparse.ArgumentParser(description='Suggestive')
    parser.add_argument('--log', '-l', help='Log file path')
    parser.add_argument('--config', '-c', help='Config file path')

    run(parser.parse_args())
