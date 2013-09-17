import suggestive.bindings as bindings
from suggestive.util import album_text

import urwid


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


class SuggestiveListBox(urwid.ListBox):

    def __init__(self, *args, **kwArgs):
        super(SuggestiveListBox, self).__init__(*args, **kwArgs)
        self._command_map = bindings.ListCommands


class SelectableLibraryItem(urwid.WidgetWrap):
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


class SelectableAlbum(SelectableLibraryItem):

    def __init__(self, suggestion):
        self.content = self.album = suggestion.album
        self.expanded = False
        text = album_text(self.album)
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
