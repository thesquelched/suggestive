import queue
from curses import wrapper
import logging
import threading
from time import sleep
import mstat
from analytics import Analytics
from datetime import datetime

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

EVENTS = queue.PriorityQueue()
SUGGESTIONS = []
PAGE = 0
LAST_UPDATED = datetime.now()

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
class UserInputThread(threading.Thread):
  def __init__(self, stdscr, *args, **kwArgs):
    super(UserInputThread, self).__init__(*args, **kwArgs)
    self.stdscr = stdscr

  def run(self):
    while True:
      key = self.stdscr.getkey()
      EVENTS.put(KeyPressEvent(key))

class DatabaseUpdateThread(threading.Thread):
  def __init__(self, conf, *args, **kwArgs):
    super(DatabaseUpdateThread, self).__init__(*args, **kwArgs)
    self.conf = conf

    self.session = mstat.initialize_sqlalchemy(conf)
    self.mpd = mstat.initialize_mpd(conf)
    self.lastfm = mstat.initialize_lastfm(conf)

  def run(self):
    mstat.update_database(self.session, self.mpd, self.lastfm, self.conf)
    EVENTS.put(DatabaseUpdated(self.session))

######################################################################
# Main Functions
######################################################################
def start_db_update(conf):
  update_thread = DatabaseUpdateThread(conf)
  update_thread.daemon = False
  update_thread.start()

def main(stdscr):
  global PAGE
  logging.basicConfig(level=logging.DEBUG, filename = 'log.txt', filemode = 'w')
  logger.info('Starting event loop')

  conf = mstat.configuration(path = 'suggestive.conf')
  session = mstat.initialize_sqlalchemy(conf)
  anl = Analytics(session)

  input_thread = UserInputThread(stdscr)
  input_thread.daemon = True
  input_thread.start()

  stdscr.clear()
  update_suggestions(stdscr, anl)

  start_db_update(conf)
  
  while True:
    event = EVENTS.get()

    if isinstance(event, KeyPressEvent):
      if event.key == 'q':
        return
      elif event.key == 'u':
        start_db_update(conf)
      elif event.key == 'j':
        PAGE += 1
        display_suggestions(stdscr)
      elif event.key == 'k':
        PAGE = max(PAGE-1, 0)
        display_suggestions(stdscr)
    elif isinstance(event, DatabaseUpdated):
      update_suggestions(stdscr, anl)

def display_suggestions(stdscr):
  suggestions = SUGGESTIONS[PAGE*10:(PAGE+1)*10]

  stdscr.clear()
  stdscr.addstr(0, 0, 'Last updated: {}'.format(LAST_UPDATED))
  stdscr.addstr(1, 0, '-'*80)
  for i, suggestion in enumerate(suggestions, 2):
    stdscr.addstr(i, 0, '{} - {}'.format(suggestion.artist.name, suggestion.name))
  stdscr.refresh()

def update_suggestions(stdscr, anl):
  global PAGE
  global SUGGESTIONS
  global LAST_UPDATED
  logger.info('Database updated')
  LAST_UPDATED = datetime.now()
  SUGGESTIONS = anl.suggest_albums()
  PAGE = 0
  display_suggestions(stdscr)

if __name__ == '__main__':
  wrapper(main)
