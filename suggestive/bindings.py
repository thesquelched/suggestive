import urwid

# Movement
UP = 'cursor up'
DOWN = 'cursor down'
LEFT = 'cursor left'
RIGHT = 'cursor right'
PAGE_UP = 'cursor page up'
PAGE_DOWN = 'cursor page down'
GO_TO_TOP = 'cursor max left'
GO_TO_BOTTOM = 'cursor max right'

# Searching
SEARCH_NEXT = 'search_next'
SEARCH_PREV = 'search_prev'

# Library commands
ENQUEUE = 'enqueue'
PLAY = 'play'
EXPAND = 'expand'

# Miscellaneous
QUIT = 'quit'
UPDATE = 'update'


class ListCommands(urwid.CommandMap):
    DEFAULT_BINDINGS = {
        UP: ('k', 'up'),
        DOWN: ('j', 'down'),
        LEFT: ('h', 'left'),
        RIGHT: ('l', 'right'),
        PAGE_UP: ('ctrl b', 'page up'),
        PAGE_DOWN: ('ctrl f', 'page down'),

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
        UP: ('k', 'up'),
        DOWN: ('j', 'down'),
        LEFT: ('h', 'left'),
        RIGHT: ('l', 'right'),
        PAGE_UP: ('ctrl b', 'page up'),
        PAGE_DOWN: ('ctrl f', 'page down'),
        GO_TO_TOP: ('g', 'home'),
        GO_TO_BOTTOM: ('G', 'end'),

        QUIT: ('q',),
        UPDATE: ('u',),

        SEARCH_NEXT: ('n',),
        SEARCH_PREV: ('N',),

        ENQUEUE: (' ',),
        PLAY: ('enter',),
        EXPAND: ('z',),
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
