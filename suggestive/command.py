import suggestive.signals as signals

import urwid
import re
import shlex


COMMAND_KWARG_RGX = re.compile(r'^(\w+)=(.*?)$')
TRUTHY = (True, 'True', 'TRUE', 'true', 1, 'yes')


def convert(ptype, value):
    if value == '':
        return None
    elif ptype is bool:
        return True if value in TRUTHY else False
    else:
        return ptype(value)


def typed(**params):
    def decorator(func):
        def decorated(self, *args, **kwArgs):
            for name, ptype in params.items():
                if name not in kwArgs:
                    continue

                kwArgs[name] = convert(ptype, kwArgs[name])

            return func(self, *args, **kwArgs)
        return decorated
    return decorator


class CommanderEdit(urwid.Edit):
    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.COMMAND_DONE, signals.AUTOCOMPLETE]

    def __init__(self, history):
        super(CommanderEdit, self).__init__(':')
        self.history = history
        self.index = None
        self.command = ''

    def keypress(self, size, key):
        if key == 'enter':
            text = self.get_edit_text()
            urwid.emit_signal(self, signals.COMMAND_DONE, text)
        elif key == 'esc':
            urwid.emit_signal(self, signals.COMMAND_DONE, None)
        elif key in ('up', 'down'):
            self.get_history(key)
        elif key == 'tab':
            self.autocomplete()
        else:
            super(CommanderEdit, self).keypress(size, key)

        return True

    def autocomplete(self):
        urwid.emit_signal(self, signals.AUTOCOMPLETE, self.get_edit_text())

    def get_history(self, key):
        if not self.history:
            return

        if self.index is None and key is 'up':
            index = 0
            self.command = str(self.edit_text)
        elif not self.index and key is 'down':
            index = None
        else:
            index = self.index + (1 if key is 'up' else -1)

        if index is None:
            cmd = self.command
        else:
            index = max(0, min(len(self.history) - 1, index))
            cmd = self.history[index]

        self.set_edit_text(cmd)
        self.index = index


class Commandable(object):
    commands = {}
    command_history = []

    @classmethod
    def parse_command_args(cls, args_raw):
        args = []
        kwargs = {}
        for arg in args_raw:
            match = re.search(COMMAND_KWARG_RGX, arg)
            if match is None:
                args.append(arg)
            else:
                name, value = match.groups()
                kwargs[name] = value

        return (args, kwargs)

    def execute_command(self, command_raw):
        if not self.command_history or self.command_history[0] != command_raw:
            self.command_history.insert(0, command_raw)

        pieces = shlex.split(command_raw)
        if not pieces:
            return

        command_name, args_raw = pieces[0], pieces[1:]
        if command_name in self.commands:
            args, kwargs = self.parse_command_args(args_raw)
            command_func = self.commands[command_name]
            command_func(*args, **kwargs)

            return True
        else:
            return False

    def wipe_history(self):
        self.command_history = []
