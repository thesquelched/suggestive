import urwid
from suggestive.widget import SearchableItem

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

    def match(self, item):
        if isinstance(item, urwid.AttrMap):
            item = item.original_widget

        if not isinstance(item, SearchableItem):
            return False

        match = re.search(
            self.pattern, item.item_text(), re.I)

        return match is not None

    def next_item(self, items, position, backward=False):
        enumerated = list(enumerate(items))
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

        matches = (idx for idx, item in ordered if self.match(item))
        return next(matches, None)
