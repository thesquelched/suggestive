import logging
import re
import itertools
import six


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def album_text(album):
    return '{} - {}'.format(album.artist.name, album.name)


def retry(attempts=None, exceptions=None):
    """Function retry decorator"""
    if attempts is None:
        attempts = 2

    assert attempts > 0, 'Must make at least one attempt'

    if exceptions is None:
        exceptions = (Exception,)
    elif issubclass(exceptions, Exception):
        exceptions = (exceptions,)

    def retry_dec(func, exceptions=exceptions):
        def wrapper(*args, **kwArgs):
            for attempt in six.moves.range(attempts):
                try:
                    return func(*args, **kwArgs)
                except exceptions as exc:
                    logger.debug('Attempt %d failed for function %s',
                                 attempt, func.__name__, exc_info=exc)
                    if attempt == attempts - 1:
                        raise

        return wrapper
    return retry_dec


def retry_function(func, *args, **kwargs):
    """Retry a function call directly, instead of having to make a wrapper
    function with the @retry decorator"""
    exceptions = kwargs.pop('exceptions', None)
    attempts = kwargs.pop('attempts', None)

    decorator = retry(attempts=attempts, exceptions=exceptions)
    return decorator(lambda: func(*args, **kwargs))()


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
