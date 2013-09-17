import logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def album_text(album):
    return '{} - {}'.format(album.artist.name, album.name)
