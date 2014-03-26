import suggestive.bindings as bindings
from suggestive.buffer import BufferList
from suggestive.util import album_text
import suggestive.mstat as mstat

import urwid
import logging
from itertools import groupby

logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


######################################################################
# Prompts
######################################################################

class Prompt(urwid.Edit):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['prompt_done']

    def __init__(self, prompt, *metadata):
        super(Prompt, self).__init__(prompt)
        self.metadata = metadata

    def keypress(self, size, key):
        if key == 'enter':
            urwid.emit_signal(self, 'prompt_done', self.get_edit_text(),
                              *self.metadata)
        elif key == 'esc':
            urwid.emit_signal(self, 'prompt_done', None, *self.metadata)
        else:
            super(Prompt, self).keypress(size, key)

        return True


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


######################################################################
# Buffer lists
######################################################################

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
        icon = SelectableScrobble(scrobble)
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
             if not isinstance(w, SelectableScrobble)),
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

        if pos >= len(self.items):
            return None, None

        return self.items[pos], pos


######################################################################
# Misc widgets
######################################################################

class SuggestiveListBox(urwid.ListBox):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['set_footer']

    def __init__(self, *args, **kwArgs):
        super(SuggestiveListBox, self).__init__(*args, **kwArgs)
        self._command_map = bindings.ListCommands
        self.searcher = None

    def update_footer(self, *args, **kwArgs):
        urwid.emit_signal(self, 'set_footer', *args, **kwArgs)

    def search(self, searcher):
        self.searcher = searcher

    def get_next_search(self, backward=False):
        if self.searcher is None:
            logger.debug('No search found')
            return

        index = self.searcher.next_item(self.body, self.focus_position,
                                        backward=backward)
        if index is None:
            raise ValueError('No match found')

        return index

    def next_search_item(self, backward=False):
        try:
            next_idx = self.get_next_search(backward)
            if next_idx is None:
                return

            self.set_focus(next_idx)
        except ValueError:
            self.update_footer('No match found')

    def first_selectable(self):
        return next(
            (i for i, item in enumerate(self.body) if item.selectable()),
            0
        )

    def keypress(self, size, key):
        cmd = self._command_map[key]
        if cmd in (bindings.GO_TO_TOP, bindings.GO_TO_BOTTOM):
            n_items = len(self.body)
            self.set_focus(
                self.first_selectable() if cmd == bindings.GO_TO_TOP
                else n_items - 1)
        elif cmd in (bindings.SEARCH_NEXT, bindings.SEARCH_PREV):
            backward = (cmd == bindings.SEARCH_PREV)
            self.next_search_item(backward=backward)
        else:
            return super(SuggestiveListBox, self).keypress(size, key)

        # Necessary to get list focus to redraw
        super(SuggestiveListBox, self).keypress(size, None)

        return True


class SearchableItem(object):

    def item_text(self):
        return self._w.get_text()[0]


class SelectableLibraryItem(urwid.WidgetWrap, SearchableItem):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['enqueue', 'play']

    _command_map = bindings.AlbumListCommands
    content = None

    def keypress(self, size, key):
        if self._command_map[key] == 'enqueue':
            urwid.emit_signal(self, 'enqueue', self.content)
        elif self._command_map[key] == 'play':
            urwid.emit_signal(self, 'play', self.content)
        else:
            return key


class SelectableScrobble(SelectableLibraryItem):

    def __init__(self, scrobble):
        self.content = self.scrobble = scrobble

        info = scrobble.scrobble_info
        text = '{} - {}'.format(info.artist, info.title)

        super(SelectableScrobble, self).__init__(urwid.SelectableIcon(text))


class SelectableAlbum(SelectableLibraryItem):

    def __init__(self, suggestion, show_score=False):
        self.content = self.album = suggestion.album
        self.expanded = False

        text = album_text(self.album)
        if show_score:
            text = '{} ({:.4g})'.format(text, suggestion.order)

        super(SelectableAlbum, self).__init__(urwid.SelectableIcon(text))

    def update_text(self):
        self._w.set_text(album_text(self.album))

    def tracks(self):
        return self.album.tracks


class SelectableTrack(SelectableLibraryItem):
    __metaclass__ = urwid.signals.MetaSignals
    signals = ['enqueue', 'play']

    def __init__(self, parent, track, track_no):
        self.parent = parent
        self.content = self.track = track
        self.track_no = track_no
        super(SelectableTrack, self).__init__(
            urwid.SelectableIcon(self.text(track, track_no)))

    def update_text(self):
        self._w.set_text(self.text(self.track, self.track_no))

    @classmethod
    def text(cls, track, track_no):
        text = '{} - {}'.format(track_no, track.name)
        if track.lastfm_info and track.lastfm_info.loved:
            return text + ' [L]'
        elif track.lastfm_info and track.lastfm_info.banned:
            return text + ' [B]'
        else:
            return text

    def tracks(self):
        return [self.track]


class PlaylistItem(urwid.WidgetWrap, SearchableItem):

    def __init__(self, *args, **kwArgs):
        super(PlaylistItem, self).__init__(
            urwid.SelectableIcon(*args, **kwArgs))
