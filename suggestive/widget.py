import suggestive.bindings as bindings
import suggestive.signals as signals

import urwid
import logging

logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


def signal_map(mapping):
    """
    Class decorator.  Takes a dictionary of mapping from keybind -> signal.  If
    one of the keybinds is detected, the specified signal is sent with the
    calling object as the only argument.
    """

    def decorator(cls):
        if not hasattr(cls, 'signals'):
            return cls

        cls.__keymap = mapping

        def keypress(self, size, key):
            if key in self.__keymap:
                signal = self.__keymap[key]
                logger.debug("Keypress '{}' sent signal '{}'".format(
                    key, signal))
                # Emit signal with self as the only argument
                urwid.emit_signal(self, self.__keymap[key], self)

                super(cls, self).keypress(size, None)
                return True

            return super(cls, self).keypress(size, key)

        cls.keypress = keypress

        return cls

    return decorator


######################################################################
# Prompts
######################################################################

class Prompt(urwid.Edit):
    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.PROMPT_DONE]

    def __init__(self, prompt, *metadata):
        super(Prompt, self).__init__(prompt)
        self.metadata = metadata

    def keypress(self, size, key):
        if key == 'enter':
            urwid.emit_signal(
                self,
                signals.PROMPT_DONE,
                self.get_edit_text(),
                *self.metadata)
        elif key == 'esc':
            urwid.emit_signal(
                self,
                signals.PROMPT_DONE,
                None,
                *self.metadata)
        else:
            super(Prompt, self).keypress(size, key)

        return True


class PlaylistMovePrompt(Prompt):
    __metaclass__ = urwid.signals.MetaSignals
    signals = Prompt.signals + [signals.UPDATE_INDEX]

    def __init__(self, original_position):
        super(PlaylistMovePrompt, self).__init__('Move item to: ',
                                                 original_position)
        self.input_buffer = ''
        self.original_position = original_position
        self.current_position = original_position

    def update_index(self, index=None):
        try:
            index = self.position() if index is None else index
            urwid.emit_signal(
                self,
                signals.UPDATE_INDEX,
                self.current_position,
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
# Misc widgets
######################################################################

class SuggestiveListBox(urwid.ListBox):
    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.SET_FOOTER]

    def __init__(self, *args, **kwArgs):
        super(SuggestiveListBox, self).__init__(*args, **kwArgs)
        self._command_map = bindings.ListCommands
        self.searcher = None

    def update_footer(self, *args, **kwArgs):
        urwid.emit_signal(self, signals.SET_FOOTER, *args, **kwArgs)

    def search(self, searcher):
        logger.debug('Start search')
        self.searcher = searcher

    def get_next_search(self, backward=False):
        logger.debug('Get next search')
        if self.searcher is None:
            logger.debug('No search found')
            return

        index = self.searcher.next_item(self.body, self.focus_position,
                                        backward=backward)
        logger.debug('Found next match: {}'.format(index))

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


class Searchable(object):

    @property
    def search_text(self):
        return self.canonical_text


class SelectableScrobble(urwid.WidgetWrap):

    def __init__(self, scrobble):
        self.content = self.scrobble = scrobble

        info = scrobble.scrobble_info
        text = '{} - {}'.format(info.artist, info.title)

        super(SelectableScrobble, self).__init__(urwid.SelectableIcon(text))
