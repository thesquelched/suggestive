"""
Main application/UI
"""

from suggestive.threads import (
    MpdWatchThread, DatabaseUpdateThread, ScrobbleInitializeThread)
from suggestive.analytics import (
    Analytics, FractionLovedOrder, BannedOrder, ArtistFilter, AlbumFilter,
    SortOrder, PlaycountOrder, BaseOrder, ModifiedOrder)
from suggestive.config import Config
from suggestive.command import CommanderEdit, Commandable
from suggestive.widget import (
    Prompt, SuggestiveListBox, SelectableAlbum, SelectableTrack)
import suggestive.bindings as bindings
import suggestive.mstat as mstat
from suggestive.util import album_text
import suggestive.migrate as migrate


import argparse
import urwid
import logging
from logging.handlers import RotatingFileHandler
import threading
import re
import os.path
import sys
from itertools import chain, islice
from mpd import CommandError

logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())

MEGABYTE = 1024 * 1024


class BufferList(object):
    def __init__(self):
        self.buffers = []

    def next_buffer(self):
        current_buffer = self.focus

        logger.debug('Current buffers: {}'.format(self.buffers))

        try:
            idx = self.buffers.index(current_buffer)
            next_buffer = self.buffers[idx + 1]
            self.go_to_buffer(next_buffer)
        except (IndexError, ValueError):
            self.focus_position = 0

    def add(self, buf, *options):
        self.contents.append((buf, self.options(*options)))

    def current_buffer(self):
        return self.focus

    def buffer_index(self, buf):
        buffers = [item[0] for item in self.contents]
        return buffers.index(buf)

    def go_to_buffer(self, buf):
        if not buf.will_accept_focus():
            return

        try:
            idx = self.buffer_index(buf)

            self.focus_position = idx
        except ValueError:
            pass

    def remove(self, buf):
        if len(self.contents) == 1:
            return False

        try:
            idx = self.buffer_index(buf)
            self.contents.pop(idx)

            while not isinstance(self.focus, Buffer):
                self.contents.pop(idx)

            self.buffers.remove(buf)

            return True

        except ValueError:
            return False


class HorizontalBufferList(urwid.Pile, BufferList):

    def __init__(self):
        BufferList.__init__(self)
        urwid.Pile.__init__(self, [])

    def add(self, buf, *options):
        self.buffers.append(buf)

        super(HorizontalBufferList, self).add(buf, *options)


class VerticalBufferList(urwid.Columns, BufferList):

    def __init__(self):
        BufferList.__init__(self)
        urwid.Columns.__init__(self, [])

    def add(self, buf):
        self.buffers.append(buf)

        if len(self.contents) > 0:
            fill = urwid.AttrMap(urwid.SolidFill(), 'status')
            super(VerticalBufferList, self).add(fill, 'given')
        super(VerticalBufferList, self).add(buf)


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


class LibraryBuffer(Buffer):
    signals = Buffer.signals + ['update_playlist']

    def __init__(self, conf, session):
        self.conf = conf
        self.session = session
        self.commands = self.setup_commands()

        self.anl = Analytics(conf)

        self.orderers = [BaseOrder()]
        self.default_orderers = list(self.init_default_orderers(conf))

        self.suggestions = []

        self.search_matches = []
        self.current_search_index = None

        self.list_view = self.suggestion_list()

        super(LibraryBuffer, self).__init__(self.list_view)
        self.update_status('Library')

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

        commands = {
            'unorder': self.clear_orderers,
            'unordered': self.clear_orderers,
            'love': self.love_selection,
            'unlove': self.unlove_selection,
        }

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
        if selection is not None:
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
        return {
            '/': lambda: self.start_search(),
            'esc': lambda: self.reset_orderers(),
        }

    def suggestion_list(self):
        body = []
        for suggestion in self.suggestions:
            item = SelectableAlbum(suggestion)

            urwid.connect_signal(item, 'enqueue', self.enqueue_album)
            urwid.connect_signal(item, 'play', self.play_album)

            body.append(urwid.AttrMap(item, 'album', 'focus album'))

        if not body:
            body = [urwid.AttrMap(urwid.Text('No albums found'), 'album')]

        albumlist = AlbumList(self, urwid.SimpleFocusListWalker(body))
        return albumlist

    def update_suggestions(self, *_args):
        logger.info('Update suggestions display')

        self.suggestions = self.get_suggestions()

        self.list_view = self.suggestion_list()
        self.set_body(self.list_view)
        #self.redraw()

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

    def start_search(self, reverse=False):
        self.edit = Prompt('/')
        urwid.connect_signal(self.edit, 'prompt_done', self.search_done,
                             reverse)
        footer = urwid.AttrMap(self.edit, 'footer')
        self.update_footer(footer)
        self.update_focus('footer')

    def search_done(self, pattern, reverse=False):
        logger.debug('Reverse: {}'.format(reverse))
        self.update_focus('body')
        urwid.disconnect_signal(self, self.edit, 'prompt_done',
                                self.search_done)

        if pattern:
            logger.info('SEARCH FOR: {}'.format(pattern))
            n_found = self.list_view.search(pattern)

            if n_found:
                status = 'Found {} match{}'.format(
                    n_found, 'es' if n_found > 1 else '')
            else:
                status = 'No items matching {}'.format(pattern)

            self.update_status(status)

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

        self.format_keys = re.findall(r'\{(\w+)\}', self.ITEM_FORMAT)
        walker = urwid.SimpleFocusListWalker(self.playlist_items())
        self.playlist = SuggestiveListBox(walker)
        super(PlaylistBuffer, self).__init__(self.playlist)

        self.update_status('Playlist')

    def will_accept_focus(self):
        mpd = mstat.initialize_mpd(self.conf)
        return len(mpd.playlistinfo()) > 0

    def setup_bindings(self):
        return {
            #'c': self.clear_mpd_playlist,
            'd': self.delete_track,
            'enter': self.play_track,
        }

    def setup_commands(self):
        return {
            'love': self.love_track,
            'unlove': self.unlove_track,
        }

    def delete_track(self):
        current_position = self.playlist.focus_position

        if current_position is not None:
            mpd = mstat.initialize_mpd(self.conf)
            mpd.delete(current_position)

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

    def playlist_items(self):
        mpd = mstat.initialize_mpd(self.conf)

        playlist = mpd.playlistinfo()
        current = mpd.currentsong()
        if current and 'pos' in current:
            current_position = int(current['pos'])
        else:
            current_position = None

        body = []
        for position, track in enumerate(playlist):
            text = urwid.SelectableIcon(self.format_track(track))
            if position == current_position:
                styles = ('playing', 'playing focus')
            else:
                styles = ('playlist', 'focus playlist')

            with_attr = urwid.AttrMap(text, *styles)
            body.append(with_attr)

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
            #fm = mstat.initialize_lastfm(self.conf)
            #mstat.set_track_loved(self.session, fm, track)

            ##selection.update_text()
            #self.redraw()

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
            #fm = mstat.initialize_lastfm(self.conf)
            #mstat.set_track_unloved(self.session, fm, track)

            #self.redraw()


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

        self.bindings = self.setup_bindings()
        self.commands = self.setup_commands()

        self.anl = Analytics(conf)

        self.suggestions = []

        self.search_matches = []
        self.current_search_index = None

        self.orientation = self.conf.orientation()

        if self.orientation == 'vertical':
            self.buffers = VerticalBufferList()
        else:
            self.buffers = HorizontalBufferList()

        self.top = MainWindow(conf, self.buffers)
        self.event_loop = self.main_loop()

        # Initialize buffers
        self.library_buffer = self.create_library_buffer()
        self.playlist_buffer = self.create_playlist_buffer()

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

        self.update_footer_text('suggestive')
        self.playing_update()

    def setup_buffers(self):
        default_buffers = self.conf.default_buffers()

        if 'library' in default_buffers:
            self.buffers.add(self.library_buffer)
            self.library_buffer.active = True
        if 'playlist' in default_buffers:
            self.buffers.add(self.playlist_buffer)
            self.playlist_buffer.active = True

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

        self.orientation = orientation
        self.buffers = buffers
        self.top.body = self.buffers

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
        self.library_buffer.update_status('Library')

    def update_playlist_event(self):
        self.event_loop.set_alarm_in(0, self.playlist_buffer.update)
        #self.playlist_buffer.update()

    def dispatch(self, key):
        if key in self.bindings:
            func = self.bindings[key]
            func()
            return True
        else:
            return False

    def exit(self):
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
        }

    def setup_commands(self):
        return {
            'playlist': self.open_playlist,
            'library': self.open_library,
            'q': self.exit,
            'orientation': self.change_orientation,
            'or': self.change_orientation,
        }

    def clear_playlist(self):
        self.playlist_buffer.clear_mpd_playlist()
        if self.buffers.current_buffer() is self.playlist_buffer:
            self.buffers.go_to_buffer(self.library_buffer)

    def pause(self):
        mpd = mstat.initialize_mpd(self.conf)
        mpd.pause()

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
            list(self.buffers.focus.commands.items())
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
            success = False

            try:
                success = self.buffers.focus.execute_command(command)
                if not success:
                    success = self.execute_command(command)
            except TypeError as err:
                logger.debug('TypeError: {}'.format(err))
                self.update_footer_text(
                    "Invalid arguments for command '{}'".format(command),
                    error=True)

            if not success:
                self.update_footer_text(
                    "Unknown command: '{}'".format(command),
                    error=True)

    def setup_palette(self):
        return self.conf.palette()

    def setup_term(self, screen):
        colormode = 256 if self.conf.use_256_colors() else 88
        screen.set_terminal_properties(colors=colormode)

    def playing_update(self, *args):
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


class AlbumSearcher(object):

    def __init__(self, pattern, items, current):
        self.pattern = pattern

        self.matches, self.match_index = self.search(items, current)

    def _order_items(self, items):
        raise NotImplementedError

    def _current_position(self, items, current):
        raise NotImplementedError

    def _indices(items):
        raise NotImplementedError

    def current_match(self):
        return self.matches[self.match_index]

    def search(self, items, current):
        current = self._current_position(items, current)
        items = self._order_items(items)

        ordered = chain(
            islice(items, current, None),
            islice(items, 0, current)
        )

        albums = (item.original_widget.album for item in ordered)
        search_items = (album_text(album) for album in albums)

        indices = self._indices(search_items)
        matches = [
            (current + index) % len(items) for index in indices
        ]

        if not matches:
            raise ValueError('No matches found')

        if matches[0] == current and len(matches) > 1:
            match_index = 1
        else:
            match_index = 0

        logger.debug('{} matches found'.format(len(matches)))

        return matches, match_index

    def find_closest_match(self, current, backward=False):
        if backward:
            return next(
                (len(self.matches) - idx - 1 for idx, position
                 in enumerate(reversed(self.matches))
                 if position < current),
                len(self.matches) - 1
            )
        else:
            return next(
                (idx for idx, position in enumerate(self.matches)
                 if position > current),
                0
            )

    def next_match(self, current, backward=False):
        if current != self.matches[self.match_index]:
            index = self.find_closest_match(current, backward=backward)
        else:
            index = self.match_index + (-1 if backward else 1)

        if index < 0:
            return len(self.matches) - 1
        elif index >= len(self.matches):
            return 0
        else:
            return index

    def next_search_item(self, current, backward=False):
        if not self.matches or self.match_index is None:
            logger.debug('No search found')
            return None

        index = self.next_match(current, backward=backward)
        return self.matches[index]


class ForwardAlbumSearcher(AlbumSearcher):

    @classmethod
    def _order_items(self, items):
        return list(items)

    @classmethod
    def _current_position(self, _items, current):
        return current

    def _indices(self, items):
        return [
            i for i, item in enumerate(items)
            if re.search(self.pattern, item, re.I) is not None
        ]


class ReverseAlbumSearcher(AlbumSearcher):

    @classmethod
    def _order_items(self, items):
        return list(reversed(items))

    @classmethod
    def _current_position(self, items, current):
        return len(items) - current - 1

    def _indices(self, items):
        n_items = len(items)
        return [
            (n_items - i - 1) for i, item in enumerate(items)
            if re.search(self.pattern, item, re.I) is not None
        ]


class AlbumList(urwid.ListBox):

    def __init__(self, app, *args, **kwArgs):
        super(AlbumList, self).__init__(*args, **kwArgs)

        self.app = app
        self.searcher = None

        self._command_map = bindings.AlbumListCommands

    def search(self, pattern, reverse=False):
        self.searcher = None

        searcher = ReverseAlbumSearcher if reverse else ForwardAlbumSearcher

        try:
            self.searcher = searcher(
                pattern, self.body, self.focus_position)
            self.set_focus(self.searcher.current_match())
            return len(self.searcher.matches)
        except ValueError as err:
            logger.info('No matches found')
            logger.debug('Exception: {}'.format(err))
            return 0

    def next_search_item(self, backward=False):
        if self.searcher is None:
            logger.debug('No search found')
            return

        index = self.searcher.next_search_item(
            self.focus_position, backward=backward)

        self.set_focus(index)

    def sort_tracks(self, tracks):
        track_and_num = []
        mpd = mstat.initialize_mpd(self.app.conf)

        for i, track in enumerate(tracks):
            try:
                mpd_track = mpd.listallinfo(track.filename)
            except CommandError:
                continue

            if not mpd_track:
                continue
            trackno = str(mpd_track[0].get('track', i))
            trackno = re.sub(r'(\d+)/\d+', r'\1', trackno)

            track_and_num.append((int(trackno), track))

        logger.debug('Track nums: {}'.format([x[0] for x in track_and_num]))

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
        #self.body.insert(current + 1, self.focus)

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
        if cmd in (bindings.SEARCH_NEXT, bindings.SEARCH_PREV):
            backward = (cmd == bindings.SEARCH_PREV)
            self.next_search_item(backward=backward)
        elif cmd in (bindings.GO_TO_TOP, bindings.GO_TO_BOTTOM):
            n_items = len(self.body)
            self.set_focus(0 if cmd == bindings.GO_TO_TOP else n_items - 1)
        elif cmd == 'expand':
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
