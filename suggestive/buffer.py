from suggestive.command import Commandable

import logging
import urwid
from itertools import chain


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


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
