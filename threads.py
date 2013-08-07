import mstat
import threading
import logging


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


db_lock = threading.Lock()


class AppThread(threading.Thread):

    """Base class for suggestive threads"""

    pass


class MpdWatchThread(AppThread):

    """Watches mpd for changes"""

    def __init__(self, conf, playlist_cb, *args, **kwArgs):
        super(MpdWatchThread, self).__init__(*args, **kwArgs)
        self.conf = conf
        self.playlist_cb = playlist_cb

    def run(self):
        mpd = mstat.initialize_mpd(self.conf)

        while True:
            changes = mpd.idle('playlist', 'player')
            if 'playlist' in changes or 'player' in changes:
                # update playlist
                logger.debug('Detected playlist change')
                self.playlist_cb()


class DatabaseUpdateThread(AppThread):

    """Start a database update"""

    def __init__(self, conf, callback, *args, **kwArgs):
        super(DatabaseUpdateThread, self).__init__(*args, **kwArgs)
        self.callback = callback
        self.conf = conf

        self.session = mstat.initialize_sqlalchemy(conf)
        self.mpd = mstat.initialize_mpd(conf)
        self.lastfm = mstat.initialize_lastfm(conf)

    def run(self):
        logger.debug('Waiting for lock')

        with db_lock:
            logger.info('Start MPD update')
            self.mpd.update()
            logger.info('Finished MPD update')

            logger.info('Update internal database')
            mstat.update_database(self.session, self.mpd, self.lastfm,
                                  self.conf)

            self.session.close()

            logger.info('Finished update')

            (self.callback)()

        logger.debug('Released lock')
