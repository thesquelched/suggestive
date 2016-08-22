import suggestive.mstat as mstat
from suggestive.util import partition
from suggestive.db.session import session_scope

from pylastfm import LastfmError
import threading
import logging
import traceback
from queue import PriorityQueue, Empty


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# Synchronization primitives
db_lock = threading.Lock()
updating_database = threading.Event()


def log_errors(cls):
    orig_run = cls.run

    def newrun(self):
        try:
            orig_run(self)
        except:
            logger.critical('{} encountered exception'.format(cls.__name__))
            logger.critical(traceback.format_exc())
            raise

    cls.run = newrun

    return cls


class PriorityEventQueue(PriorityQueue):

    unique = {'player', 'playlist', 'database'}

    def __init__(self):
        self.events = set()
        self.set_lock = threading.Lock()
        super(PriorityEventQueue, self).__init__()

    def in_queue(self, event):
        return (
            event in self.events and
            event in self.unique
        )

    def put(self, item, *args, **kwArgs):
        with self.set_lock:
            event = item[-1]
            if self.in_queue(event):
                logger.debug('{} already in queue'.format(item))
                return

            self.events.add(event)
            super(PriorityEventQueue, self).put(item, *args, **kwArgs)

    def get(self, *args, **kwArgs):
        item = super(PriorityEventQueue, self).get(*args, **kwArgs)
        with self.set_lock:
            event = item[-1]
            self.events.discard(event)
            return item


event_queue = PriorityEventQueue()


class AppThread(threading.Thread):

    """Base class for suggestive threads"""

    def __init__(self, quit_event, *args, **kwArgs):
        super(AppThread, self).__init__(*args, **kwArgs)
        self.quit_event = quit_event


class MpdObserver(AppThread):

    """
    database: the song database has been modified after update.
    update: a database update has started or finished. If the database was
        modified during the update, the database event is also emitted.
    stored_playlist: a stored playlist has been modified, renamed, created or
        deleted
    playlist: the current playlist has been modified
    player: the player has been started, stopped or seeked
    mixer: the volume has been changed
    output: an audio output has been enabled or disabled
    options: options like repeat, random, crossfade, replay gain
    sticker: the sticker database has been modified.
    subscription: a client has subscribed or unsubscribed to a channel
    message: a message was received on a channel this client is subscribed to;
        this event is only emitted when the queue is empty
    """

    order = (
        'player',
        'playlist',
        'database',
        'update',
        'stored_playlist',
        'mixer',
        'output',
        'options',
        'sticker',
        'subscription',
        'message',
    )

    def __init__(self, conf, events, quit_event):
        super(MpdObserver, self).__init__(quit_event)

        self.conf = conf
        self.events = events
        self.priorities = self.build_priority()

        # Thread properties
        self.daemon = True

    def build_priority(self):
        return {event: i for i, event in enumerate(self.order)}

    def consume_event(self, event):
        callback = self.events.get(event)
        if not callable(callback):
            logger.error('Event {} has no associated callback'.format(
                event))
            return

        priority = self.priorities.get(event, 0)
        event_queue.put((priority, callback))

    def run(self):
        mpd = mstat.initialize_mpd(self.conf)

        while not self.quit_event.is_set():
            logger.debug('MPD: idle')
            changes = mpd.idle()
            logger.debug('Mpd changes: {}'.format(changes))
            for change in changes:
                self.consume_event(change)


class EventDispatcher(AppThread):

    default_timeout = 1

    def __init__(self, quit_event, timeout=None):
        super(EventDispatcher, self).__init__(quit_event)
        if timeout is None:
            timeout = self.default_timeout

        self.timeout = float(timeout)

    def run(self):
        while not self.quit_event.is_set():
            try:
                _, callback = event_queue.get(True, self.timeout)
                callback()
            except Empty:
                pass


class DatabaseUpdater(AppThread):

    def __init__(self, conf, quit_event, update_status):
        super(DatabaseUpdater, self).__init__(quit_event)
        self.conf = conf
        self.update_status = update_status
        self.daemon = False

    def run(self):
        if updating_database.is_set():
            logger.debug('Ignoring database update; already running')
            return

        logger.debug('Waiting for database lock')
        with db_lock:
            if self.quit_event.is_set():
                return

            logger.info('Starting database update')
            updating_database.set()

            mstat.update_database(self.conf)

            logger.debug('Finished database update')
            updating_database.clear()

            (self.update_status)()


@log_errors
class ScrobbleInitializeThread(AppThread):

    """Load scrobbles from all time"""

    def __init__(self, conf, callback, *args, **kwArgs):
        super(ScrobbleInitializeThread, self).__init__(*args, **kwArgs)
        self.conf = conf
        self.callback = callback

    def run(self):
        conf = self.conf

        logger.info('Start initializing scrobbles')

        lastfm = mstat.initialize_lastfm(conf)
        with session_scope(conf) as session:
            earliest = mstat.earliest_scrobble(session)

        try:
            batches = partition(
                lastfm.scrobbles(conf.lastfm_user, end=earliest),
                200)
        except LastfmError as exc:
            logger.error('Could not contact LastFM server', exc_info=exc)
            batches = []

        for batch in batches:
            if self.quit_event.is_set():
                return

            logger.debug('ScrobbleInitializeThread: Waiting for lock')

            with db_lock:
                logger.debug('ScrobbleInitializeThread: Acquired lock')

                with session_scope(conf) as session:
                    mstat.load_scrobble_batch(session, lastfm, conf, batch)

        with db_lock:
            with session_scope(conf) as session:
                mstat.ScrobbleLoader.delete_duplicates(session)

        logger.info('Finished initializing scrobbles')
        (self.callback)()
