"""
Main application/UI
"""

from suggestive.threads import (
    MpdObserver, EventDispatcher, DatabaseUpdater, ScrobbleInitializeThread)
from suggestive.analytics import Analytics
from suggestive.config import Config
from suggestive.command import CommanderEdit, Commandable, typed
import suggestive.widget as widget
import suggestive.mstat as mstat
import suggestive.migrate as migrate
from suggestive.search import LazySearcher
from suggestive.error import CommandError
from suggestive.buffer import (
    VerticalBufferList, HorizontalBufferList, ScrobbleBuffer,
    NewPlaylistBuffer, NewLibraryBuffer
)

import argparse
import urwid
import logging
from logging.handlers import RotatingFileHandler
import threading
import os.path
import sys


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())

MEGABYTE = 1024 * 1024


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
    def __init__(self, args, conf, session):
        self.conf = conf
        self.session = session

        self.mpd = mstat.initialize_mpd(conf)
        self.db_update_thread = None

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

        if not args.no_update and (args.update or conf.update_on_startup()):
            self.start_mpd_update()

    def update_library_status(self, *args, **kwArgs):
        self.library_buffer.update_status(*args, **kwArgs)

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
        #buf = LibraryBuffer(self.conf, self.session)
        buf = NewLibraryBuffer(self.conf, self.session)
        urwid.connect_signal(buf, 'set_focus', self.top.update_focus)
        urwid.connect_signal(buf, 'set_footer', self.update_footer)
        urwid.connect_signal(buf, 'redraw', self.event_loop.draw_screen)

        #buf.update_suggestions()

        return buf

    def create_playlist_buffer(self):
        buf = NewPlaylistBuffer(self.conf, self.session)
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

    def start_event_system(self):
        events = {
            'playlist': self.update_playlist_event,
            'player': self.update_player_event,
            'database': self.update_database_event,
            'update': self.check_update_event,
        }
        self.observer = MpdObserver(self.conf, events, self.quit_event)
        self.dispatcher = EventDispatcher(self.quit_event)

        self.dispatcher.start()
        self.observer.start()

    def update_player_event(self):
        if self.playlist_buffer.track_changed():
            self.update_playlist_event()
        else:
            self.playlist_buffer.update_playing_status()

    def update_database_event(self):
        self.update_library_status('Library (updating database...)')
        updater = DatabaseUpdater(
            self.conf,
            self.quit_event,
            self.update_library_event)
        updater.start()

    def check_update_event(self):
        if 'updating_db' in self.mpd.status():
            self.update_library_status('Library (updating MPD...)')
        else:
            self.update_library_status('Library')

    def start_mpd_update(self):
        self.mpd.update()

    def start_scrobble_initialize(self):
        scrobble_thread = ScrobbleInitializeThread(
            self.conf, self.quit_event)
        scrobble_thread.daemon = False
        scrobble_thread.start()

    def update_library_event(self):
        logger.info('Updating library')
        self.session.expire_all()
        self.event_loop.set_alarm_in(0, self.library_buffer.update_suggestions)
        self.event_loop.set_alarm_in(0, self.scrobble_buffer.update)
        self.update_library_status('Library')

    def update_playlist_event(self):
        # TODO: Optimize by checking what's changed
        self.event_loop.set_alarm_in(0, self.playlist_buffer.update)

        # TODO: Re-enable in appropriate place
        #if self.playlist_buffer.track_changed():
        #    self.event_loop.set_alarm_in(0, self.scrobble_buffer.update)
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
            try:
                self.playlist_buffer.save_playlist(playlist)
            except Exception as ex:
                logger.error('Unable to save playlist: {}'.format(ex))
                pass

        self.quit_event.set()
        raise urwid.ExitMainLoop()

    def setup_bindings(self):
        return {
            'q': lambda: self.exit(),
            'u': lambda: self.start_mpd_update(),
            'U': lambda: self.update_database_event(),
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
        self.edit = widget.Prompt('/')
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
        self.start_event_system()
        self.start_scrobble_initialize()

        return mainloop


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
            app = Application(args, conf, main_session)
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
    parser.add_argument('--update', '-u', help='Update database',
                        action='store_true')
    parser.add_argument('--no_update', '-U', help='Do not update database',
                        action='store_true')

    run(parser.parse_args())
