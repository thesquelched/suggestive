from suggestive.command import Commandable
import suggestive.widget as widget
import suggestive.mstat as mstat
from suggestive.error import CommandError
from suggestive.playlist import PlaylistController, PlaylistView, PlaylistModel

import logging
import urwid
from itertools import chain
from mpd import CommandError as MpdCommandError


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


class NewPlaylistBuffer(Buffer):
    signals = Buffer.signals + ['love_track', 'unlove_track']
    ITEM_FORMAT = '{artist} - {album} - {title}{suffix}'

    def __init__(self, conf, session):
        self.conf = conf
        self.model = PlaylistModel([])
        self.controller = PlaylistController(self.model, conf, session)
        self.view = PlaylistView(self.model, self.controller, conf)

        self.current_track = None
        self.status_format = conf.playlist_status_format()

        super(NewPlaylistBuffer, self).__init__(self.view)

        self.update_status('Playlist')

    def setup_bindings(self):
        keybinds = super(NewPlaylistBuffer, self).setup_bindings()
        keybinds.update({
            'm': self.move_track,
        })

        return keybinds

    def search(self, searcher):
        self.view.search(searcher)

    def next_search(self):
        self.view.next_search_item()

    def will_accept_focus(self):
        return len(self.model.tracks) > 0

    def move_track(self):
        logger.debug('Start playlist move')
        self.view.update(show_bumper=True)

        self.move_prompt = widget.PlaylistMovePrompt(
            self.view.focus_position)
        urwid.connect_signal(self.move_prompt, 'prompt_done',
                             self.complete_move)
        urwid.connect_signal(self.move_prompt, 'update_index',
                             self.view.move_update_index)

        self.update_footer(urwid.AttrMap(self.move_prompt, 'footer'))
        self.update_focus('footer')

    def complete_move(self, value):
        urwid.disconnect_signal(self, self.move_prompt, 'prompt_done',
                                self.complete_move)
        urwid.disconnect_signal(self, self.move_prompt, 'update_index',
                                self.view.move_update_index)

        self.update_focus('body')

        try:
            new_index = int(value)
            logger.debug('Moving playlist track from {} to {}'.format(
                self.view.focus_position, new_index))

            mpd = mstat.initialize_mpd(self.conf)
            mpd.move(self.view.focus_position, new_index)
        except (TypeError, ValueError):
            logger.error('Invalid move index: {}'.format(value))

        self.update()

    def now_playing_index(self, mpd):
        current = mpd.currentsong()
        if current and 'pos' in current:
            return int(current['pos'])
        else:
            return None

    def track_changed(self):
        mpd = mstat.initialize_mpd(self.conf)
        return self.current_track != self.now_playing_index(mpd)

    def update(self, *args):
        self.controller.update_model()

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

        return 'Playlist'

    def clear_mpd_playlist(self):
        self.controller.clear()

    def load_playlist(self, name=None):
        if name is None:
            raise CommandError('Missing parameter: name')

        try:
            self.controller.load_playlist(name)
            self.update_footer('Loaded playlist {}'.format(name))
            return True
        except MpdCommandError as ex:
            logger.debug(ex)
            raise CommandError("Unable to load playlist '{}'".format(
                name))

    def save_playlist(self, name=None):
        if name is None:
            raise CommandError('Missing parameter: name')

        try:
            self.controller.save_playlist(name)
            self.update_footer('Saved playlist {}'.format(name))
            return True
        except MpdCommandError as ex:
            logger.debug(ex)
            raise CommandError("Unable to save playlist '{}'".format(
                name))
