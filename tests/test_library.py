from suggestive.mvc import library

import pytest
from unittest.mock import Mock


@pytest.fixture
def model():
    artist = Mock()
    artist.name = 'Test Artist'

    album = Mock(ignored=False, artist=artist)
    album.name = 'Test Album'

    return library.AlbumModel(album, 1.0)


def test_with_score(model):
    conf = Mock(show_score=Mock(return_value=True))

    v = library.AlbumView(model, conf)

    assert v.text == 'Test Artist - Test Album (1)'
    assert v.score == 1.0


def test_without_score(model):
    conf = Mock(show_score=Mock(return_value=False))

    v = library.AlbumView(model, conf)

    assert v.text == 'Test Artist - Test Album'
    assert v.score == 1.0


def test_ignored(model):
    model.db_album.ignored = True
    conf = Mock(show_score=Mock(return_value=False))

    v = library.AlbumView(model, conf)

    assert v.text == 'Test Artist - Test Album [I]'
    assert v.score == 1.0
