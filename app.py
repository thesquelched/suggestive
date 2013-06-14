import queue
import curses
import logging
import threading
from time import sleep
import mstat
from analytics import Analytics
from datetime import datetime
import copy

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

DEFAULT_KEYS = dict(
  up = set(['k', curses.KEY_UP]),
  down = set(['j', curses.KEY_DOWN]),
  left = set(['h', curses.KEY_LEFT]),
  right = set(['l', curses.KEY_RIGHT]),
  page_up = set(['\x02', curses.KEY_PPAGE]),
  page_down = set(['\x06', curses.KEY_NPAGE]),
  top = set(['g', curses.KEY_HOME]),
  bottom = set(['G', curses.KEY_END]),
  quit = set(['q']),
  update = set(['u']),
)

class KeyBindings(object):
  def __init__(self, user_bindings = None):
    if user_bindings is None:
      user_bindings = {}

    bindings = copy.copy(DEFAULT_KEYS)
    bindings.update(user_bindings)

    for name, keys in bindings.items():
      setattr(self, name, keys)

######################################################################
# Exceptions
######################################################################
class QuitApplication(Exception):
  pass

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
  def __init__(self, stdscr, *args, **kwArgs):
    super(UserInputThread, self).__init__(*args, **kwArgs)
    self.stdscr = stdscr

  def run(self):
    while True:
      key = self.stdscr.getkey()
      self.events.put(KeyPressEvent(key))

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
  def __init__(self, stdscr, conf):
    self.stdscr = stdscr
    self.conf = conf

    session = mstat.initialize_sqlalchemy(conf)
    self.anl = Analytics(session)

    self.suggestions = []
    self.events = queue.PriorityQueue()
    self.last_updated = datetime.now()
    self.page_size = 10
    self.page = 0
    self.keys = KeyBindings()

  def num_pages(self):
    return len(self.suggestions)//self.page_size

  def start_db_update(self):
    update_thread = DatabaseUpdateThread(self.conf, self.events)
    update_thread.daemon = False
    update_thread.start()

  def display_suggestions(self):
    pages = self.num_pages()
    if self.page > pages:
      albums = self.suggestions[:self.page_size]
    else:
      albums = self.suggestions[self.page*self.page_size:(self.page+1)*self.page_size]

    self.stdscr.clear()
    self.stdscr.addstr(0, 0, 'Last updated: {}'.format(self.last_updated))
    self.stdscr.addstr(1, 0, '-'*80)

    # Write albums
    for i, album in enumerate(albums, 2):
      self.stdscr.addstr(i, 0, '{} - {}'.format(album.artist.name, album.name))

    self.stdscr.refresh()

  def update_suggestions(self):
    self.last_updated = datetime.now()

    self.suggestions = self.anl.suggest_albums()
    self.display_suggestions()

  def dispatch(self, key):
    keys = self.keys
    if key in keys.quit:
      raise QuitApplication
    elif key in keys.update:
      self.start_db_update()
    elif key in keys.page_down:
      self.page = min(self.page+1, self.num_pages())
      logger.debug('Page: {}'.format(self.page))
      self.display_suggestions()
    elif key in keys.page_up:
      self.page = max(self.page-1, 0)
      logger.debug('Page: {}'.format(self.page))
      self.display_suggestions()

  def run(self):
    logger.info('Starting event loop')

    input_thread = UserInputThread(self.stdscr, self.events)
    input_thread.daemon = True
    input_thread.start()

    self.stdscr.clear()
    self.update_suggestions()

    self.start_db_update()

    while True:
      event = self.events.get()

      if isinstance(event, KeyPressEvent):
        try:
          self.dispatch(event.key)
        except QuitApplication:
          return
      elif isinstance(event, DatabaseUpdated):
        self.page = 0
        self.update_suggestions()

def main(stdscr):
  conf = mstat.configuration(path = 'suggestive.conf')
  app = Application(stdscr, conf)

  logging.basicConfig(level=logging.DEBUG, filename = 'log.txt', filemode = 'w')
  logger.info('Starting event loop')

  app.run()

if __name__ == '__main__':
  curses.wrapper(main)
