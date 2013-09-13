import urwid


SEARCH_NEXT = 'search_next'
SEARCH_PREV = 'search_prev'
GO_TO_TOP = 'cursor max left'
GO_TO_BOTTOM = 'cursor max right'


class ListCommands(urwid.CommandMap):
    DEFAULT_BINDINGS = {
        'cursor up': ('k', 'up'),
        'cursor down': ('j', 'down'),
        'cursor left': ('h', 'left'),
        'cursor right': ('l', 'right'),
        'cursor page up': ('ctrl b', 'page up'),
        'cursor page down': ('ctrl f', 'page down'),

        GO_TO_TOP: ('g', 'home'),
        GO_TO_BOTTOM: ('G', 'end'),
    }

    @classmethod
    def _flatten(cls, bindings):
        flattened = {}
        for action, keys in bindings.items():
            flattened.update({key: action for key in keys})

        return flattened

    def __init__(self, *args, **kwArgs):
        super(ListCommands, self).__init__()
        self.update(self._flatten(self.DEFAULT_BINDINGS))
        self.update(*args, **kwArgs)

    def update(self, *args, **kwArgs):
        if args and isinstance(args[0], dict):
            bindings = args[0]
        else:
            bindings = kwArgs

        for key, command in bindings.items():
            self.__setitem__(key, command)


class AlbumListCommands(urwid.CommandMap):
    DEFAULT_BINDINGS = {
        'cursor up': ('k', 'up'),
        'cursor down': ('j', 'down'),
        'cursor left': ('h', 'left'),
        'cursor right': ('l', 'right'),
        'cursor page up': ('ctrl b', 'page up'),
        'cursor page down': ('ctrl f', 'page down'),
        'quit': ('q',),
        'update': ('u',),
        'reload': ('r',),

        GO_TO_TOP: ('g', 'home'),
        GO_TO_BOTTOM: ('G', 'end'),
        SEARCH_NEXT: ('n',),
        SEARCH_PREV: ('N',),

        'enqueue': (' ',),
        'play': ('enter',),
        'expand': ('z',),
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
