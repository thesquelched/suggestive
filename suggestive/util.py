import logging
import re
import itertools


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def album_text(album):
    return '{} - {}'.format(album.artist.name, album.name)


def retry(attempts=2):
    """Function retry decorator"""

    def retry_dec(func):
        def wrapper(self, *args, **kwArgs):
            last_error = ValueError('No attempts made')
            for attempt in range(attempts):
                try:
                    return func(self, *args, **kwArgs)
                except Exception as error:
                    last_error = error

            raise last_error
        return wrapper
    return retry_dec


def track_num(trackno):
    """Get the correct track number from an mpd item"""
    if isinstance(trackno, (tuple, list)):
        trackno = trackno[0]

    simplified = re.sub(r'(\d+)/\d+', r'\1', str(trackno))
    return int(simplified)


def partition(coll, size):
    """Partition a collection into chunks"""
    coll = iter(coll)
    while True:
        chunk = list(itertools.islice(coll, size))
        if not chunk:
            break

        yield chunk
