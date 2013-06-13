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
def start_db_update(conf, events):
  update_thread = DatabaseUpdateThread(conf, events)
  update_thread.daemon = False
  update_thread.start()

def main(stdscr):
  logging.basicConfig(level=logging.DEBUG, filename = 'log.txt', filemode = 'w')
  logger.info('Starting event loop')

  events = queue.PriorityQueue()
  page = 0
  conf = mstat.configuration(path = 'suggestive.conf')
  session = mstat.initialize_sqlalchemy(conf)
  anl = Analytics(session)

  input_thread = UserInputThread(stdscr, events)
  input_thread.daemon = True
  input_thread.start()

  stdscr.clear()
  suggestions = update_suggestions(stdscr, anl)

  start_db_update(conf, events)
  
  while True:
    event = events.get()

    if isinstance(event, KeyPressEvent):
      if event.key == 'q':
        return
      elif event.key == 'u':
        start_db_update(conf, events)
      elif event.key == 'j':
        page += 1
        display_suggestions(suggestions, page, stdscr)
      elif event.key == 'k':
        page = max(page-1, 0)
        display_suggestions(suggestions, page, stdscr)
    elif isinstance(event, DatabaseUpdated):
      suggestions = update_suggestions(stdscr, anl)

def display_suggestions(suggestions, page, stdscr):
  albums = suggestions[page*10:(page+1)*10]

  stdscr.clear()
  stdscr.addstr(0, 0, 'Last updated: {}'.format(LAST_UPDATED))
  stdscr.addstr(1, 0, '-'*80)
  for i, album in enumerate(albums, 2):
    stdscr.addstr(i, 0, '{} - {}'.format(album.artist.name, album.name))
  stdscr.refresh()

def update_suggestions(stdscr, anl):
  global LAST_UPDATED

  logger.info('Database updated')
  LAST_UPDATED = datetime.now()
  suggestions = anl.suggest_albums()
  display_suggestions(suggestions, 0, stdscr)

  return suggestions

if __name__ == '__main__':
  wrapper(main)
