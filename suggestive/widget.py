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
