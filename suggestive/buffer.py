from suggestive.command import Commandable
import suggestive.signals as signals
import logging
import urwid
from itertools import chain

logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


######################################################################
# Buffer list
######################################################################

class BufferList(object):
    """
    Super class for different buffer orientation styles
    """

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
        logger.debug('All buffers: {}'.format(list(self)))
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

    @property
    def orientation(self):
        return 'horizontal'


class VerticalBufferList(urwid.Columns, BufferList):

    def __init__(self):
        BufferList.__init__(self)
        urwid.Columns.__init__(self, [], dividechars=1)

    def __iter__(self):
        return BufferList.__iter__(self)

    @property
    def orientation(self):
        return 'vertical'


######################################################################
# Buffers
######################################################################

class Buffer(urwid.Frame, Commandable):
    """
    Super class for buffer objects.  Based on urwid.Frame.  Defines a footer
    that can display a status message or anchor a prompt.
    """

    __metaclass__ = urwid.signals.MetaSignals
    signals = [
        signals.SET_FOOTER,
        signals.SET_FOCUS,
        signals.SET_STATUS
    ]

    def __init__(self, *args, **kwArgs):
        super(Buffer, self).__init__(*args, **kwArgs)
        self.bindings = self.setup_bindings()
        self.commands = self.setup_commands()
        self.active = False
        urwid.connect_signal(self, signals.SET_STATUS, self.update_status)

    def update_status(self, value):
        if isinstance(value, str):
            status = urwid.Text(value)
        else:
            status = value

        footer = urwid.AttrMap(status, 'status')
        self.set_footer(footer)

    def update_focus(self, to_focus):
        urwid.emit_signal(self, signals.SET_FOCUS, to_focus)

    def update_footer(self, footer, focus=False):
        urwid.emit_signal(self, signals.SET_FOOTER, footer, focus)

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
