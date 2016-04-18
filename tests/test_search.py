import pytest

from suggestive.search import LazySearcher
from suggestive.widget import Searchable


@pytest.mark.parametrize('pattern,matches', [
    ('José González', True),
    ('Jose Gonzalez', True),
    ('jose', True),
    ('gonzalez', True),
    ('noep', False),
])
def test_searches(pattern, matches):
    view = Searchable()
    view.searchable_text = 'José González'

    searcher = LazySearcher(pattern)
    assert searcher.match(view) == matches
