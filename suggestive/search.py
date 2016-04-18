from suggestive.widget import Searchable

import logging
import re
from itertools import chain, islice

logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


class LazySearcher(object):

    """
    Performs a regex search on the text of a list of widgets
    """

    def __init__(self, pattern, reverse=False):
        self.pattern = pattern
        self.reverse = bool(reverse)

    def match(self, view):
        if not isinstance(view, Searchable):
            return False

        for fuzzy_unicode in (False, True):
            value = view.search_text(fuzzy_unicode)

            logger.debug('Search for pattern %s in %s', self.pattern, value)
            if re.search(self.pattern, value, re.I):
                return True

        return False

    def next_item(self, views, position, backward=False):
        enumerated = list(enumerate(views))
        if self.reverse:
            backward = not backward

        if backward:
            ordered = chain(
                reversed(enumerated[0:position]),
                reversed(enumerated[position:]))
        else:
            next_pos = position + 1

            ordered = chain(
                islice(enumerated, next_pos, None, 1),
                islice(enumerated, 0, next_pos, 1))

        matches = (idx for idx, view in ordered if self.match(view))

        return next(matches, None)
