import logging

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
