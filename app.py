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

def start_db_update(conf):
  update_thread = DatabaseUpdateThread(conf)
  update_thread.daemon = False
  update_thread.start()

######################################################################
# Main Function
######################################################################
def main(stdscr):
  logging.basicConfig(level=logging.DEBUG, filename = 'log.txt', filemode = 'w')
  logger.info('Starting event loop')

  conf = mstat.configuration(path = 'suggestive.conf')
  session = mstat.initialize_sqlalchemy(conf)
  anl = Analytics(session)

  input_thread = UserInputThread(stdscr)
  input_thread.daemon = True
  input_thread.start()

  #session = mstat.run('suggestive.conf')
  #anl = Analytics(session)

  #suggestions = anl.suggest_albums(10)
  #for i, suggestion in enumerate(suggestions):
  #  stdscr.addstr(i, 0, '{} - {}'.format(suggestion.artist.name, suggestion.name))
  #stdscr.refresh()

  #key = stdscr.getkey()

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
    elif isinstance(event, DatabaseUpdated):
      update_suggestions(stdscr, anl)

def update_suggestions(stdscr, anl):
  logger.info('Database updated')
  suggestions = anl.suggest_albums(10)

  stdscr.clear()
  now = datetime.now()
  stdscr.addstr(0, 0, 'Last updated: {}'.format(now))
  stdscr.addstr(1, 0, '-'*80)
  for i, suggestion in enumerate(suggestions, 2):
    stdscr.addstr(i, 0, '{} - {}'.format(suggestion.artist.name, suggestion.name))
  stdscr.refresh()

if __name__ == '__main__':
  wrapper(main)