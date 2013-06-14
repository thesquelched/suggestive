import queue
import urwid
import logging
import threading
from time import sleep
import mstat
from analytics import Analytics, Suggestion
from datetime import datetime
import copy

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

ENQUEUE = 'enqueue'
PLAY = 'play'

######################################################################
# Events
######################################################################
class Event(object):
  def __init__(self, priority = None):
    self.priority = None if priority is None else int(priority)

  def __lt__(self, other):
    if self.priority is None:
      return False
    elif other.priority is None:
      return True
    else:
      return self.priority < other.priority

class KeyPressEvent(Event):
  def __init__(self, key_pressed):
    super(KeyPressEvent, self).__init__(priority = 0)
    self.key = key_pressed

class DatabaseUpdated(Event):
  def __init__(self, session):
    super(DatabaseUpdated, self).__init__(priority = 1)
    self.session = session

######################################################################
# Threads
######################################################################
class AppThread(threading.Thread):
  def __init__(self, events, *args, **kwArgs):
    super(AppThread, self).__init__(*args, **kwArgs)
    self.events = events
    logger.debug(events)

class UserInputThread(AppThread):
  def __init__(self, stdscr, quit_keys, *args, **kwArgs):
    super(UserInputThread, self).__init__(*args, **kwArgs)
    self.stdscr = stdscr
    self.quit_keys = quit_keys

  def run(self):
    while True:
      key = self.stdscr.getkey()
      self.events.put(KeyPressEvent(key))

      if key in self.quit_keys:
        return

class DatabaseUpdateThread(AppThread):
  def __init__(self, conf, *args, **kwArgs):
    super(DatabaseUpdateThread, self).__init__(*args, **kwArgs)
    self.conf = conf

    self.session = mstat.initialize_sqlalchemy(conf)
    self.mpd = mstat.initialize_mpd(conf)
    self.lastfm = mstat.initialize_lastfm(conf)

  def run(self):
    mstat.update_database(self.session, self.mpd, self.lastfm, self.conf)
    self.events.put(DatabaseUpdated(self.session))

######################################################################
# Main Functions
######################################################################

class Application(object):
  def __init__(self, conf):
    self.conf = conf

    session = mstat.initialize_sqlalchemy(conf)
    self.anl = Analytics(session)

    self.suggestions = []
    self.events = queue.PriorityQueue()
    self.last_updated = datetime.now()
    self.page_size = 10
    self.page = 0

    # urwid stuff
    self.list_view = suggestion_list(datetime.now().strftime('%Y-%m-%d %H:%M'),  self.suggestions)

  def num_pages(self):
    return len(self.suggestions)//self.page_size

  def start_db_update(self):
    update_thread = DatabaseUpdateThread(self.conf, self.events)
    update_thread.daemon = False
    update_thread.start()

  def update_suggestions(self):
    self.last_updated = datetime.now()

    self.suggestions = self.anl.suggest_albums()
    self.list_view = suggestion_list(datetime.now().strftime('%Y-%m-%d %H:%M'),  self.suggestions)

  def dispatch(self, key):
    #keys = self.keys
    if key == 'q':
      raise urwid.ExitMainLoop()
    elif key == 'u':
      self.start_db_update()

  def run(self):
    logger.info('Starting event loop')

    self.update_suggestions()
    #self.start_db_update()

    main = urwid.Padding(self.list_view, left=2, right=2)
    top = urwid.Overlay(main, urwid.SolidFill(),
      align = 'left', width=('relative', 60),
      valign='top', height=('relative', 60),
      min_width=20, min_height=9)
    urwid.MainLoop(top, palette = [('reversed', 'standout', '')], unhandled_input = self.dispatch).run()

class AlbumListCommands(urwid.CommandMap):
  DEFAULT_BINDINGS = {
    'cursor up': ('k', 'up'),
    'cursor down': ('j', 'down'),
    'cursor left': ('h', 'left'),
    'cursor right': ('l', 'right'),
    'cursor page up': ('ctrl b', 'page up'),
    'cursor page down': ('ctrl f', 'page down'),
    'cursor max left': ('g', 'home'),
    'cursor max right': ('G', 'end'),
    'quit': ('q',),
    'update': ('u',),
    'enqueue': (' ',),
    'play': ('enter',),
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

def enqueue(widget_, album):
  logger.info('Enqueue: {} - {}'.format(album.artist.name, album.name))

class SelectableAlbum(urwid.WidgetWrap):
  __metaclass__ = urwid.signals.MetaSignals
  signals = ['enqueue']

  def __init__(self, suggestion):
    self.album = album = suggestion.album
    text = '{} - {}'.format(album.artist.name, album.name)
    super(SelectableAlbum, self).__init__(
      urwid.SelectableIcon(text))

    self._command_map = AlbumListCommands()
    urwid.connect_signal(self, 'enqueue', enqueue, self.album)

  def keypress(self, size, key):
    if self._command_map[key] == ENQUEUE:
      self._emit('enqueue')
    else:
      return key

def suggestion_list(updated, suggestions):
  body = [urwid.Text(updated), urwid.Divider()]
  for suggestion in suggestions:
    item = SelectableAlbum(suggestion)
    body.append(urwid.AttrMap(item, None, focus_map='reversed'))

  box = urwid.ListBox(urwid.SimpleFocusListWalker(body))
  box._command_map = AlbumListCommands()
  return box

def main():
  conf = mstat.configuration(path = 'suggestive.conf')
  app = Application(conf)

  logging.basicConfig(level=logging.DEBUG, filename = 'log.txt', filemode = 'w')
  logger.info('Starting event loop')

  app.run()

if __name__ == '__main__':
  main()
