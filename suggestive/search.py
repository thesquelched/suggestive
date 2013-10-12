import logging
import re
from itertools import chain, islice

logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


class LazySearcher(object):

    def __init__(self, pattern, reverse=False):
        self.pattern = pattern
        self.reverse = bool(reverse)

    def match(self, item):
        match = re.search(
            self.pattern, item.original_widget.item_text(), re.I)

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


class Searcher(object):

    def __init__(self, pattern, items, current):
        self.pattern = pattern

        self.matches, self.match_index = self.search(items, current)

    def _indices(self, items):
        return [
            i for i, item in enumerate(items)
            if re.search(self.pattern, item, re.I) is not None
        ]

    def current_match(self):
        return self.matches[self.match_index]

    def search(self, items, current):
        n_items = len(items)
        items_wrap = chain(
            islice(items, current, None),
            islice(items, 0, current)
        )

        items_text = [item.original_widget.item_text() for item in items_wrap]
        indices = self._indices(items_text)

        matches = [(current + index) % n_items for index in indices]

        if not matches:
            raise ValueError('No matches found')

        if matches[0] == current and len(matches) > 1:
            match_index = 1
        else:
            match_index = 0

        logger.debug('{} matches found'.format(len(matches)))

        return matches, match_index

    def find_closest_match(self, current, backward=False):
        if backward:
            n_matches = len(self.matches)
            return next(
                (n_matches - idx - 1 for idx, position
                 in enumerate(reversed(self.matches))
                 if position < current),
                n_matches - 1
            )
        else:
            return next(
                (idx for idx, position in enumerate(self.matches)
                 if position > current),
                0
            )

    def next_match(self, current, backward=False):
        if current != self.matches[self.match_index]:
            index = self.find_closest_match(current, backward=backward)
        else:
            index = self.match_index + (-1 if backward else 1)

        if index < 0:
            return len(self.matches) - 1
        elif index >= len(self.matches):
            return 0
        else:
            return index

    def next_search_item(self, current, backward=False):
        if not self.matches or self.match_index is None:
            logger.debug('No search found')
            return None

        index = self.next_match(current, backward=backward)
        return self.matches[index]
