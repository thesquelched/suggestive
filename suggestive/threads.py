import suggestive.mstat as mstat
import threading
import logging
import traceback


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
            changes = mpd.idle('playlist', 'player')
            if 'playlist' in changes or 'player' in changes:
                # update playlist
                logger.debug('Detected playlist change')
                self.playlist_cb()


@log_errors
class DatabaseUpdateThread(AppThread):

    """Start a database update"""

    def __init__(self, conf, callback, *args, **kwArgs):
        super(DatabaseUpdateThread, self).__init__(*args, **kwArgs)
        self.callback = callback
        self.conf = conf

    def run(self):
        logger.debug('Waiting for lock')

        with db_lock:
            logger.info('Start MPD update')
            mpd = mstat.initialize_mpd(self.conf)
            mpd.update()
            logger.info('Finished MPD update')

            if self.quit_event.is_set():
                return

            logger.info('Update internal database')
            mstat.update_database(self.conf)

            logger.info('Finished update')

            (self.callback)()

        logger.debug('Released lock')


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

        batches = lastfm.scrobble_batches(conf.lastfm_user(), end=earliest)

        for batch in batches:
            if self.quit_event.is_set():
                return

            logger.debug('ScrobbleInitializeThread: Waiting for lock')

            with db_lock:
                logger.debug('ScrobbleInitializeThread: Acquired lock')

                with mstat.session_scope(conf) as session:
                    mstat.load_scrobble_batch(session, lastfm, conf, batch)

        logger.info('Finished initializing scrobbles')
