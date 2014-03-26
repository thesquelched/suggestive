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
