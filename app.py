import urwid
import logging
import threading
import mstat
from analytics import Analytics
from datetime import datetime
from subprocess import call
from itertools import chain
import re

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

ENQUEUE = 'enqueue'
PLAY = 'play'

######################################################################
# Threads
######################################################################


class AppThread(threading.Thread):
    pass


class DatabaseUpdateThread(AppThread):
    def __init__(self, conf, callback, *args, **kwArgs):
        super(DatabaseUpdateThread, self).__init__(*args, **kwArgs)
        self.callback = callback
        self.conf = conf

        self.session = mstat.initialize_sqlalchemy(conf)
        self.mpd = mstat.initialize_mpd(conf)
        self.lastfm = mstat.initialize_lastfm(conf)

    def run(self):
        mstat.update_database(self.session, self.mpd, self.lastfm, self.conf)
        logger.info('Finished update')
        (self.callback)()


######################################################################
# Main Functions
######################################################################


class Application(object):
    def __init__(self, conf):
        self.conf = conf

        self.mpd = mstat.initialize_mpd(conf)
        session = mstat.initialize_sqlalchemy(conf)
        self.anl = Analytics(session)

        self.suggestions = []
        self.last_updated = datetime.now()
        self.page_size = 10
        self.page = 0

        # urwid stuff
        self.list_view = self.suggestion_list()
        self.header = urwid.Text('')
        self.status = urwid.Text('Idle')
        self.footer = urwid.Pile([urwid.Divider('\u2500'), self.status])

        self.event_loop = self.main_loop()

    def num_pages(self):
        return len(self.suggestions) // self.page_size

    def start_db_update(self):
        self.update_status('Updating database')
        update_thread = DatabaseUpdateThread(self.conf, self.update_event)
        update_thread.daemon = False
        update_thread.start()

    def update_event(self):
        self.event_loop.set_alarm_in(0, self.update_suggestions)

    def update_suggestions(self, *_args):
        logger.info('Update suggestions display')
        self.last_updated = datetime.now()

        #self.suggestions = self.anl.loved_order()
        self.suggestions = self.anl.suggest_albums()
        self.list_view = self.suggestion_list()
        self.update_header()
        self.update_status('Idle')

    def enqueue_album(self, widget_, album):
        logger.info('Enqueue: {} - {}'.format(album.artist.name, album.name))
        mpd_tracks = list(chain.from_iterable(
            self.mpd.listallinfo(track.filename) for track in album.tracks))

        for i, track in enumerate(mpd_tracks):
            trackno = str(track.get('track', i))
            trackno = re.sub(r'(\d+)/\d+', r'\1', trackno)
            track['track'] = int(trackno)

        sorted_tracks = sorted(mpd_tracks, key=lambda track: track['track'])
        ids = [self.mpd.addid(track['file']) for track in sorted_tracks]
        return ids

    def play_album(self, widget_, album):
        logger.info('Play: {} - {}'.format(album.artist.name, album.name))
        self.mpd.clear()
        ids = self.enqueue_album(widget_, album)
        if ids:
            self.mpd.playid(ids[0])

    def update_header(self):
        timestamp = self.last_updated.strftime('%Y-%m-%d %H:%M:%S')
        self.header.set_text('Last updated: {}'.format(timestamp))

    def update_status(self, status):
        self.status.set_text(status)
        self.footer = urwid.Pile([urwid.Divider('\u2500'), self.status])

    def dispatch(self, key):
        if key == 'q':
            raise urwid.ExitMainLoop()
        elif key == 'u':
            self.start_db_update()
        elif key == 'r':
            self.update_suggestions()
        elif key == '~':
            self.event_loop.screen.stop()
            call('ncmpcpp', shell=True)
            self.event_loop.screen.start()

    def suggestion_list(self):
        if not self.suggestions:
            body = [urwid.Text('MPD database is empty')]
        else:
            body = []

        for suggestion in self.suggestions:
            item = SelectableAlbum(suggestion)

            urwid.connect_signal(item, 'enqueue', self.enqueue_album,
                                 item.album)
            urwid.connect_signal(item, 'play', self.play_album, item.album)

            body.append(urwid.AttrMap(item, None, focus_map='reversed'))

        box = urwid.ListBox(urwid.SimpleFocusListWalker(body))
        box._command_map = AlbumListCommands()
        return box

    def main_loop(self):
        logger.info('Starting event loop')

        self.update_suggestions()
        self.update_header()
        self.update_status('Idle')
        #self.start_db_update()

        main = urwid.Padding(self.list_view, left=2, right=2)
        middle = urwid.Filler(main, height=('relative', 100), valign='middle',
                              top=1, bottom=1)
        top = urwid.Frame(middle, header=self.header, footer=self.footer)

        return urwid.MainLoop(top, palette=[('reversed', 'standout', '')],
                              unhandled_input=self.dispatch)


class AlbumListCommands(urwid.CommandMap):
    DEFAULT_BINDINGS = {
        'cursor up': ('k', 'up'),
        'cursor down': ('j', 'down'),
        'cursor left': ('h', 'left'),
        'cursor right': ('l', 'right'),
        'cursor page up': ('ctrl b', 'page up'),
        'cursor page down': ('ctrl f', 'page down'),
        'cursor max left': ('g', 'home'),
        'cursor max right': ('G', 'end'),
        'quit': ('q',),
        'update': ('u',),
        'reload': ('r',),
        ENQUEUE: (' ',),
        PLAY: ('enter',),
    }

    @classmethod
    def _flatten(cls, bindings):
        flattened = {}
        for action, keys in bindings.items():
            flattened.update({key: action for key in keys})

        return flattened

    def __init__(self, *args, **kwArgs):
        super(AlbumListCommands, self).__init__()
        self.update(self._flatten(self.DEFAULT_BINDINGS))
        self.update(*args, **kwArgs)

    def update(self, *args, **kwArgs):
        if args and isinstance(args[0], dict):
            bindings = args[0]
        else:
            bindings = kwArgs

        for key, command in bindings.items():
            self.__setitem__(key, command)


class SelectableAlbum(urwid.WidgetWrap):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['enqueue', 'play']

    def __init__(self, suggestion):
        self.album = album = suggestion.album
        text = '{} - {} ({}/{} loved)'.format(
            album.artist.name, album.name, len(suggestion.loved),
            len(album.tracks))
        super(SelectableAlbum, self).__init__(urwid.SelectableIcon(text))

        self._command_map = AlbumListCommands()

    def keypress(self, size, key):
        if self._command_map[key] == ENQUEUE:
            self._emit('enqueue')
        elif self._command_map[key] == PLAY:
            self._emit('play')
        else:
            return key


def main():
    conf = mstat.configuration(path='suggestive.conf')

    logging.basicConfig(level=logging.DEBUG, filename='log.txt', filemode='w')
    logger.info('Starting event loop')

    app = Application(conf)

    app.event_loop.run()


if __name__ == '__main__':
    main()
