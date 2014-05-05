import suggestive.library as library

from unittest import TestCase
from unittest.mock import MagicMock, Mock


class TestAlbumView(TestCase):

    @classmethod
    def setUpClass(cls):
        artist = Mock()
        artist.name = 'Test Artist'

        album = Mock(artist=artist)
        album.name = 'Test Album'
        cls.model = library.AlbumModel(album, 1.0)

    def test_with_score(self):
        conf = Mock()
        conf.show_score = MagicMock(return_value=True)

        v = library.AlbumView(self.model, conf)

        self.assertEqual(v.text, 'Test Artist - Test Album (1)')
        self.assertEqual(v.score, 1.0)

    def test_without_score(self):
        conf = Mock()
        conf.show_score = MagicMock(return_value=False)

        v = library.AlbumView(self.model, conf)

        self.assertEqual(v.text, 'Test Artist - Test Album')
        self.assertEqual(v.score, 1.0)
