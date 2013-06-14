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

    self.events = queue.PriorityQueue()
    self.last_updated = datetime.now()

  def start_db_update(self):
    update_thread = DatabaseUpdateThread(self.conf, self.events)
    update_thread.daemon = False
    update_thread.start()

  def display_suggestions(self, suggestions, page = None):
    if page is None:
      page = 0

    pages = len(suggestions)//10
    if page > pages:
      albums = suggestions[:10]
    else:
      albums = suggestions[page*10:(page+1)*10]

    self.stdscr.clear()
    self.stdscr.addstr(0, 0, 'Last updated: {}'.format(self.last_updated))
    self.stdscr.addstr(1, 0, '-'*80)

    # Write albums
    for i, album in enumerate(albums, 2):
      self.stdscr.addstr(i, 0, '{} - {}'.format(album.artist.name, album.name))

    self.stdscr.refresh()

  def update_suggestions(self):
    self.last_updated = datetime.now()

    suggestions = self.anl.suggest_albums()
    self.display_suggestions(suggestions)

    return suggestions

  def run(self):
    logger.info('Starting event loop')

    input_thread = UserInputThread(self.stdscr, self.events)
    input_thread.daemon = True
    input_thread.start()

    self.stdscr.clear()
    suggestions = self.update_suggestions()

    self.start_db_update()

    page = 0
    
    while True:
      event = self.events.get()

      if isinstance(event, KeyPressEvent):
        if event.key == 'q':
          return
        elif event.key == 'u':
          self.start_db_update()
        elif event.key == 'j':
          page = min(page+1, len(suggestions)//10)
          logger.debug('Page: {}'.format(page))
          self.display_suggestions(suggestions, page = page)
        elif event.key == 'k':
          page = max(page-1, 0)
          logger.debug('Page: {}'.format(page))
          self.display_suggestions(suggestions, page = page)
      elif isinstance(event, DatabaseUpdated):
        page = 0
        suggestions = self.update_suggestions()

def main(stdscr):
  conf = mstat.configuration(path = 'suggestive.conf')
  app = Application(stdscr, conf)

  logging.basicConfig(level=logging.DEBUG, filename = 'log.txt', filemode = 'w')
  logger.info('Starting event loop')

  app.run()

if __name__ == '__main__':
  wrapper(main)
