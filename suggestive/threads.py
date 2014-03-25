import suggestive.mstat as mstat
from suggestive.lastfm import LastfmError
import threading
import logging
import traceback
import socket
from Queue import PriorityQueue, Empty


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


db_lock = threading.Lock()


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

    unique = {'player', 'playlist', 'database'}

    def __init__(self, conf, events, queue):
        self.conf = conf
        self.events = events
        self.queue = queue
        self.priorities = self.build_priority()
        #self.events = {
        #    'database': None,
        #    'update': None,
        #    'stored_playlist': None,
        #    'playlist': None,
        #    'player': None,
        #    'mixer': None,
        #    'output': None,
        #    'options': None,
        #    'sticker': None,
        #    'subscription': None,
        #    'message': None,
        #}

    def build_priority(self):
        return {event: i for i, event in enumerate(self.order)}

    def consume_event(self, event):
        callback = self.events.get(event)
        if not callable(callback):
            return

        if callback in self.queue and callback in self.unique:
            return

        priority = self.priorities.get(event, 0)
        self.queue.put((priority, callback))

    def run(self):
        mpd = mstat.initialize_mpd(self.conf)

        while not self.quit_event.is_set():
            changes = mpd.idle()
            for change in changes:
                self.consume_event(change)


class EventDispatcher(AppThread):

    default_timeout = 1

    def __init__(self, queue, quit_event, timeout=None):
        if timeout is None:
            timeout = self.default_timeout

        self.queue = queue
        self.timeout = float(timeout)

    def run(self):
        while not self.quit_event.is_set():
            try:
                _, callback = self.queue.get(True, self.timeout)
                callback()
            except Empty:
                pass


@log_errors
class MpdWatchThread(AppThread):

    """Watches mpd for changes"""

    def __init__(self, conf, playlist_cb, *args, **kwArgs):
        super(MpdWatchThread, self).__init__(*args, **kwArgs)
        self.conf = conf
        self.playlist_cb = playlist_cb

    def run(self):
        mpd = mstat.initialize_mpd(self.conf)

        while not self.quit_event.is_set():
            mpd.idle('playlist', 'player')
            self.playlist_cb()


@log_errors
class DatabaseUpdateThread(AppThread):

    """Start a database update"""

    def __init__(self, conf, callback, status_updater, *args, **kwArgs):
        super(DatabaseUpdateThread, self).__init__(*args, **kwArgs)
        self.callback = callback
        self.conf = conf
        self.status_updater = status_updater
        self.mpd = mstat.initialize_mpd(self.conf)
        self.mpd.idletimeout = 1

    def idle(self):
        while not self.quit_event.is_set():
            try:
                self.mpd.idle('database')
                return
            except (socket.timeout, OSError):
                continue

    def run(self):
        logger.info('Started database update thread')

        while not self.quit_event.is_set():
            logger.info('Waiting for MPD database update event')

            self.idle()

            if self.quit_event.is_set():
                logger.info('Exiting database update thread')
                return

            (self.status_updater)('Library (updating database...)')
            logger.info('Started database update')

            logger.debug('Waiting for lock')
            with db_lock:
                logger.info('Update internal database')
                mstat.update_database(self.conf)

                logger.info('Finished update')

            logger.debug('Released lock')
            (self.callback)()


@log_errors
class MpdUpdateThread(AppThread):

    """Update the MPD database"""

    def __init__(self, conf, callback, *args, **kwArgs):
        super(MpdUpdateThread, self).__init__(*args, **kwArgs)
        self.conf = conf
        self.callback = callback

    def run(self):
        logger.info('Start MPD update')
        mpd = mstat.initialize_mpd(self.conf)
        mpd.update()
        mpd.idle('update')

        logger.info('Finished MPD update')
        (self.callback)()


@log_errors
class ScrobbleInitializeThread(AppThread):

    """Load scrobbles from all time"""

    def __init__(self, conf, *args, **kwArgs):
        super(ScrobbleInitializeThread, self).__init__(*args, **kwArgs)
        self.conf = conf

    def run(self):
        conf = self.conf

        logger.info('Start initializing scrobbles')

        lastfm = mstat.initialize_lastfm(conf)
        with mstat.session_scope(conf) as session:
            earliest = mstat.earliest_scrobble(session)

        try:
            batches = lastfm.scrobble_batches(conf.lastfm_user(), end=earliest)
        except LastfmError as err:
            logger.error('Could not contact LastFM server')
            logger.debug(err)
            batches = []

        for batch in batches:
            if self.quit_event.is_set():
                return

            logger.debug('ScrobbleInitializeThread: Waiting for lock')

            with db_lock:
                logger.debug('ScrobbleInitializeThread: Acquired lock')

                with mstat.session_scope(conf) as session:
                    mstat.load_scrobble_batch(session, lastfm, conf, batch)

        logger.info('Finished initializing scrobbles')
