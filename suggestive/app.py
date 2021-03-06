"""
Main application/UI
"""

import asyncio
import argparse
import urwid
import logging
from logging.handlers import RotatingFileHandler
import threading
import os
import gzip

from suggestive.db.session import initialize as initialize_session
from suggestive import widget, signals, mstat, migrate
from suggestive.threads import (
    MpdObserver, EventDispatcher, DatabaseUpdater, ScrobbleInitializeThread)
from suggestive.config import Config
from suggestive.command import CommanderEdit, Commandable, typed
from suggestive.search import LazySearcher
from suggestive.error import CommandError
from suggestive.buffer import VerticalBufferList, HorizontalBufferList
from suggestive.mvc.scrobbles import ScrobbleBuffer
from suggestive.mvc.library import LibraryBuffer
from suggestive.mvc.playlist import PlaylistBuffer
from suggestive.mvc.base import Controller


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())

MEGABYTE = 1024 * 1024


class MainView(urwid.Frame):
    """
    Main view for urwid display, containing all of the buffers, as well as the
    main status footer
    """

    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.SET_FOOTER, signals.SET_FOCUS]

    def __init__(self, conf, loop):
        self._conf = conf

        self._buffers = self.initialize_buffers(loop)
        self._buffer_list = self.create_buffer_list()

        super(MainView, self).__init__(
            urwid.AttrMap(self._buffer_list, 'footer')
        )

        # Signals
        urwid.connect_signal(self, signals.SET_FOOTER, self.update_footer)
        urwid.connect_signal(self, signals.SET_FOCUS, self.update_focus)

    @property
    def conf(self):
        return self._conf

    @property
    def buffers(self):
        return self._buffers

    @property
    def library(self):
        return self.buffers['library']

    @property
    def playlist(self):
        return self.buffers['playlist']

    @property
    def scrobbles(self):
        return self.buffers['scrobbles']

    def __iter__(self):
        return iter(self._buffer_list)

    def initialize_buffers(self, loop):
        default = set(self.conf.general.default_buffers)
        logger.debug('Default buffers: {}'.format(default))

        buffers = {
            'library': self.create_library_buffer(
                loop, 'library' in default),
            'playlist': self.create_playlist_buffer(
                loop, 'playlist' in default),
            'scrobbles': self.create_scrobbles_buffer(
                loop, 'scrobbles' in default),
        }

        logger.debug('Controller registry: {}'.format(Controller._registry))

        return buffers

    def create_library_buffer(self, loop, active=False):
        buf = LibraryBuffer(self.conf, loop)
        buf.active = active
        urwid.connect_signal(buf, signals.SET_FOCUS, self.update_focus)
        urwid.connect_signal(buf, signals.SET_FOOTER, self.update_footer)

        return buf

    def create_playlist_buffer(self, loop, active=False):
        buf = PlaylistBuffer(self.conf, loop)
        buf.active = active
        urwid.connect_signal(buf, signals.SET_FOCUS, self.update_focus)
        urwid.connect_signal(buf, signals.SET_FOOTER, self.update_footer)

        return buf

    def create_scrobbles_buffer(self, loop, active=False):
        buf = ScrobbleBuffer(self.conf, loop)
        buf.active = active
        urwid.connect_signal(buf, signals.SET_FOCUS, self.update_focus)
        urwid.connect_signal(buf, signals.SET_FOOTER, self.update_footer)

        return buf

    def toggle_buffer(self, name):
        buf = self.buffers.get(name)
        if not buf:
            raise CommandError('Unknown buffer: {}'.format(name))

        if buf.active:
            logger.debug('Close {}'.format(name))
            if self._buffer_list.remove(buf):
                buf.active = False
        else:
            logger.debug('Open {}'.format(name))
            self._buffer_list.add(buf)
            buf.active = True

    def change_orientation(self, orientation=None):
        """
        Change the buffer list orientation between vertical and horizontal
        """
        if orientation not in ('vertical', 'horizontal'):
            if self._buffer_list.orientation == 'vertical':
                orientation = 'horizontal'
            else:
                orientation = 'vertical'

        self.update(orientation)

    def create_buffer_list(self, orientation=None):
        if orientation == 'horizontal':
            buffer_list = HorizontalBufferList()
        else:
            buffer_list = VerticalBufferList()

        for bufname in ('library', 'playlist', 'scrobbles'):
            buf = self.buffers[bufname]
            logger.debug('Buffer {} is {}'.format(
                bufname,
                'active' if buf.active else 'not active'))

            if buf.active:
                buffer_list.add(buf)

        return buffer_list

    def next_buffer(self):
        self._buffer_list.next_buffer()

    def current_buffer(self):
        return self._buffer_list.current_buffer()

    def update(self, orientation=None):
        self._buffer_list = self.create_buffer_list(orientation)
        self.body.original_widget = self._buffer_list

    def update_footer(self, footer, focus=False):
        self.set_footer(footer)
        if focus:
            self.set_focus('footer')

    def update_focus(self, to_focus):
        self.set_focus(to_focus)


class Application(Commandable):
    """
    Application class for urwid interface
    """

    def __init__(self, args, conf):
        self._conf = conf

        self._mpd = mstat.initialize_mpd(conf)
        self.quit_event = threading.Event()

        self.loop = asyncio.get_event_loop()
        self.top = MainView(conf, self.loop)
        self.urwid_loop = self.main_loop()

        self.bindings = self.setup_bindings()
        self.commands = self.setup_commands()

        self.update_footer_text('suggestive')
        self.continuously_update_playlist_status()

        if not args.no_update and (args.update or conf.general.update_on_startup):
            self.start_mpd_update()

    @property
    def conf(self):
        return self._conf

    def update_library_status(self, *args, **kwArgs):
        """
        Update the library buffer status footer
        """
        self.top.library.update_status(*args, **kwArgs)

    def update_footer(self, value, error=False):
        """Update the main window footer"""

        if isinstance(value, str):
            self.update_footer_text(value, error=error)
        else:
            self.top.update_footer(value)

    def update_footer_text(self, value, error=False):
        """Update the main window footer text contents"""

        text = urwid.AttrMap(
            urwid.Text(value),
            'footer error' if error else 'footer'
        )
        self.top.update_footer(text)

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
        if self.top.playlist.track_changed():
            self.update_playlist_event()
        else:
            self.top.playlist.update_playing_status()

    def update_database_event(self):
        self.update_library_status('Library (updating database...)')
        updater = DatabaseUpdater(
            self.conf,
            self.quit_event,
            self.update_library_event)
        updater.start()

    def check_update_event(self):
        if 'updating_db' in self._mpd.status():
            self.update_library_status('Library (updating MPD...)')
        else:
            self.update_library_status('Library')

    @mstat.mpd_retry
    def start_mpd_update(self):
        self._mpd.update()

    def start_scrobble_initialize(self):
        scrobble_thread = ScrobbleInitializeThread(
            self.conf, self.update_library_event, self.quit_event)
        scrobble_thread.daemon = False
        scrobble_thread.start()

    def update_library_event(self):
        logger.info('Updating library')
        self.urwid_loop.set_alarm_in(
            0,
            lambda *args: self.top.library.controller.update_model())
        self.urwid_loop.set_alarm_in(0, self.top.scrobbles.reload)
        self.update_library_status('Library')

    def update_playlist_event(self):
        self.urwid_loop.set_alarm_in(0, self.top.playlist.update)
        self.urwid_loop.set_alarm_in(0, self.top.scrobbles.update)

    def dispatch(self, key):
        if key in self.bindings:
            func = self.bindings[key]
            func()
            return True
        else:
            return False

    def exit(self):
        if self.conf.playlist.save_playlist_on_close:
            playlist = self.conf.playlist.playlist_save_name
            try:
                self.top.playlist.save_playlist(playlist)
            except Exception as ex:
                logger.error('Unable to save playlist: {}'.format(ex))
                pass

        self.quit_event.set()
        raise urwid.ExitMainLoop()

    def setup_bindings(self):
        """
        Set up global application bindings
        """
        return {
            'q': lambda: self.exit(),
            'u': lambda: self.start_mpd_update(),
            'U': lambda: self.update_database_event(),
            ':': lambda: self.start_command(),
            'p': lambda: self.pause(),
            'ctrl w': lambda: self.top.next_buffer(),
            'c': self.clear_playlist,
            'r': self.update_library_event,
            '/': lambda: self.start_search(),
            '?': lambda: self.start_search(reverse=True),
        }

    def setup_commands(self):
        """
        Set up global application commands
        """
        return {
            'playlist': lambda: self.top.toggle_buffer('playlist'),
            'library': lambda: self.top.toggle_buffer('library'),
            'scrobbles': lambda: self.top.toggle_buffer('scrobbles'),
            'q': self.exit,
            'orientation': self.top.change_orientation,
            'or': self.top.change_orientation,
            'score': self.toggle_show_score,
            'save': self.top.playlist.save_playlist,
            'load': self.top.playlist.load_playlist,
            'seek': self.top.playlist.seek,
        }

    def clear_playlist(self):
        self.top.playlist.clear_mpd_playlist()
        if self.top.current_buffer() is self.top.playlist:
            self.top.next_buffer()

    @typed(show=bool)
    def toggle_show_score(self, show=None):
        self.conf.library.show_score = not self.conf.library.show_score
        self.update_library_event()

    def pause(self):
        mpd = mstat.initialize_mpd(self.conf)
        mpd.pause()

    def start_search(self, reverse=False):
        self.edit = widget.Prompt('/')
        urwid.connect_signal(
            self.edit,
            signals.PROMPT_DONE,
            self.search_done,
            reverse)
        footer = urwid.AttrMap(self.edit, 'footer')
        self.update_footer(footer)
        self.top.update_focus('footer')

    def search_done(self, pattern, reverse=False):
        logger.debug('Reverse: {}'.format(reverse))
        self.top.update_focus('body')
        urwid.disconnect_signal(
            self,
            self.edit,
            signals.PROMPT_DONE,
            self.search_done)

        if pattern:
            logger.debug('SEARCH FOR: {}'.format(pattern))
            searcher = LazySearcher(pattern, reverse=reverse)

            for buf in self.top:
                buf.search(searcher)

            self.top.current_buffer().next_search()

    def start_command(self):
        self.edit = CommanderEdit(self.command_history)

        urwid.connect_signal(
            self.edit,
            signals.COMMAND_DONE,
            self.command_done)
        urwid.connect_signal(
            self.edit,
            signals.AUTOCOMPLETE,
            self.autocomplete)

        footer = urwid.AttrMap(self.edit, 'footer')
        self.top.set_footer(footer)
        self.top.set_focus('footer')

    def autocomplete(self, partial):
        all_commands = dict(
            list(self.commands.items()) +
            list(self.top.current_buffer().commands.items())
        )
        matches = [cmd for cmd in all_commands if cmd.startswith(partial)]
        logger.debug('Matching: {}'.format(matches))
        if matches:
            self.edit.set_edit_text(matches[0])
            self.edit.set_edit_pos(len(matches[0]))

    def command_done(self, command):
        self.top.set_focus('body')
        urwid.disconnect_signal(
            self,
            self.edit,
            signals.COMMAND_DONE,
            self.command_done)

        if command:
            try:
                current_buf = self.top.current_buffer()
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
        return self.conf.appearance.palette

    def setup_term(self, screen):
        screen.set_terminal_properties(colors=self.conf.general.colormode)

    def continuously_update_playlist_status(self, *args):
        text = self.top.playlist.status_text()
        self.top.playlist.update_status(text)
        self.urwid_loop.set_alarm_in(
            1,
            self.continuously_update_playlist_status)

    def main_loop(self):
        mainloop = urwid.MainLoop(
            self.top,
            palette=self.setup_palette(),
            unhandled_input=self.dispatch,
            handle_mouse=False,
            event_loop=urwid.AsyncioEventLoop(loop=self.loop),
        )

        self.setup_term(mainloop.screen)

        # Start threads
        self.start_event_system()
        self.start_scrobble_initialize()

        return mainloop


def initialize_logging(conf):
    def gzip_rotate(source, dest):
        with open(source, 'rb') as sf:
            with gzip.open(dest, 'wb') as df:
                for line in sf:
                    df.write(line)

        os.remove(source)

    try:
        os.makedirs(os.path.dirname(conf.general.log))
    except IOError:
        pass

    handler = RotatingFileHandler(
        conf.general.log,
        mode='a',
        backupCount=3,
        maxBytes=10 * MEGABYTE,
    )
    handler.rotator = gzip_rotate

    fmt = logging.Formatter(
        '%(asctime)s %(levelname)s (%(name)s)| %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(fmt)
    handler.setLevel(conf.general.log_level)

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(conf.general.log_level)

    # Disable other loggers
    logging.getLogger('mpd').setLevel(logging.ERROR)
    logging.getLogger('requests').setLevel(logging.ERROR)

    # SQLAlchemy query logging
    if conf.general.log_sql_queries:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)


def run(args):
    conf = Config(args)
    initialize_logging(conf)

    first_time = not os.path.exists(conf.general.database)
    if first_time:
        print('Music database not found; initializing...')
        migrate.initialize_database(conf)
        mstat.update_mpd(conf)
    else:
        initialize_session(conf)

    # Migrate to latest database configuration
    migrate.migrate(conf)

    # Request API write access from user
    session_file = conf.general.session_file
    if conf.lastfm.api_secret and not os.path.exists(session_file):
        mstat.initialize_lastfm(conf)

    if args.reinitialize_scrobbles and not first_time:
        print('Reinitialize scrobbles from LastFM...')
        mstat.reinitialize_scrobbles(conf)

    try:
        logger.debug('Starting event loop')
        app = Application(args, conf)
        app.urwid_loop.run()
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
    parser.add_argument('--reinitialize-scrobbles', action='store_true',
                        help='Re-initialize scrobbles from LastFM')

    run(parser.parse_args())


if __name__ == '__main__':
    main()
