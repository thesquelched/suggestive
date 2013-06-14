import queue
#import curses
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

DEFAULT_KEYS = {}
#DEFAULT_KEYS = dict(
#  up = set(['k', curses.KEY_UP]),
#  down = set(['j', curses.KEY_DOWN]),
#  left = set(['h', curses.KEY_LEFT]),
#  right = set(['l', curses.KEY_RIGHT]),
#  page_up = set(['\x02', curses.KEY_PPAGE]),
#  page_down = set(['\x06', curses.KEY_NPAGE]),
#  top = set(['g', curses.KEY_HOME]),
#  bottom = set(['G', curses.KEY_END]),
#  quit = set(['q']),
#  update = set(['u']),
#)

class KeyBindings(object):
  def __init__(self, user_bindings = None):
    if user_bindings is None:
      user_bindings = {}

    bindings = copy.copy(DEFAULT_KEYS)
    bindings.update(user_bindings)

    for name, keys in bindings.items():
      if name in DEFAULT_KEYS:
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
    for i, suggestion in enumerate(albums, 2):
      album = suggestion.album
      self.stdscr.addstr(i, 0, '{} - {}'.format(album.artist.name, album.name))

    self.stdscr.refresh()

  def update_suggestions(self):
    self.last_updated = datetime.now()

    self.suggestions = self.anl.suggest_albums()
    #self.display_suggestions()

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

  #def run2(self):
  #  main = urwid.Padding(suggestion_list(datetime.now().strftime('%Y-%m-%d %H:%M'), ['foo', 'bar']), left=2, right=2)
  #  top = urwid.Overlay(main, urwid.SolidFill(),
  #    align = 'center', width=('relative', 60),
  #    valign='middle', height=('relative', 60),
  #    min_width=20, min_height=9)
  #  urwid.MainLoop(top, palette = [('reversed', 'standout', '')]).run()

  def run(self):
    logger.info('Starting event loop')

    #input_thread = UserInputThread(self.stdscr, self.keys.quit, self.events)
    #input_thread.daemon = True
    #input_thread.start()

    #self.stdscr.clear()
    self.update_suggestions()

    self.start_db_update()

    event = self.events.get()
    main = urwid.Padding(suggestion_list(datetime.now().strftime('%Y-%m-%d %H:%M'),  self.suggestions), left=2, right=2)
    top = urwid.Overlay(main, urwid.SolidFill(),
      align = 'center', width=('relative', 60),
      valign='middle', height=('relative', 60),
      min_width=20, min_height=9)
    urwid.MainLoop(top, palette = [('reversed', 'standout', '')]).run()
    #while True:
    #  event = self.events.get()

    #  if isinstance(event, KeyPressEvent):
    #    try:
    #      self.dispatch(event.key)
    #    except QuitApplication:
    #      return
    #  elif isinstance(event, DatabaseUpdated):
    #    self.page = 0
    #    self.update_suggestions()

class SelectableAlbum(urwid.WidgetWrap):
  def __init__(self, selection):
    self.selection = selection
    album = selection.album
    text = '{} - {}'.format(album.artist.name, album.name)
    super(SelectableAlbum, self).__init__(
      urwid.SelectableIcon(text))

  def keypress(self, size, key):
    if key in (' ', 'enter'):
      logger.info('selected')

    return super(SelectableAlbum, self).keypress(size, key)

def suggestion_list(updated, suggestions):
  body = [urwid.Text(updated), urwid.Divider()]
  for suggestion in suggestions:
    item = SelectableAlbum(suggestion)
    body.append(urwid.AttrMap(item, None, focus_map='reversed'))

  return urwid.ListBox(urwid.SimpleFocusListWalker(body))

#if __name__ == '__main__':
#  main = urwid.Padding(suggestion_list(datetime.now().strftime('%Y-%m-%d %H:%M'), ['foo', 'bar']), left=2, right=2)
#  top = urwid.Overlay(main, urwid.SolidFill(),
#    align = 'center', width=('relative', 60),
#    valign='middle', height=('relative', 60),
#    min_width=20, min_height=9)
#  urwid.MainLoop(top, palette = [('reversed', 'standout', '')]).run()

def main():
  conf = mstat.configuration(path = 'suggestive.conf')
  app = Application(conf)

  logging.basicConfig(level=logging.DEBUG, filename = 'log.txt', filemode = 'w')
  logger.info('Starting event loop')

  app.run()

if __name__ == '__main__':
  main()
  #curses.wrapper(main)
