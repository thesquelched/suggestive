import os.path
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

from suggestive import mstat
from suggestive.db.model import Track


@patch('suggestive.mstat.MpdLoader')
def test_playlist_tracks_missing(mpd_loader, mock_config):
    """Test that, if the mpd playlist has tracks that don't exist in the
    playlist, we attempt to load them into the databse, and if that fails, a
    placeholder is returned"""

    track1_info = {'file': '/path/to/track1.mp3', 'title': 'test track one'}
    track2_info = {'file': '/path/to/track2.mp3'}

    track1 = Track(name=track1_info['title'], filename=track1_info['file'])

    session = MagicMock()
    (session.query.return_value.options.return_value.filter.return_value
     .all.side_effect) = (
        [track1],
        [],
    )

    @contextmanager
    def make_session(*args, **kwargs):
        yield session

    with patch('suggestive.mstat.session_scope', make_session):
        tracks = mstat.database_tracks_from_mpd(
            mock_config, [track1_info, track2_info])
        assert len(tracks) == 2
        assert tracks[0] == track1

        track2 = tracks[1]
        assert track2.name == os.path.basename(track2_info['file'])
        assert track2.filename == track2_info['file']

    mpd_loader.return_value.load_mpd_tracks.assert_called_with(
        session, [track2_info['file']])


def test_duplicate_filenames(mock_config):
    """Test that the cardinality of the database tracks returned is the same
    as the input list of MPD track information"""
    track1_info = {'file': 'filename1', 'title': 'track one'}
    track2_info = {'file': 'filename2', 'title': 'track two'}

    track1, track2 = (Track(name=info['title'], filename=info['file'])
                      for info in (track1_info, track2_info))

    session = MagicMock()
    (session.query.return_value.options.return_value.filter.return_value
     .all.return_value) = [track1, track2]

    @contextmanager
    def make_session(*args, **kwargs):
        yield session

    with patch('suggestive.mstat.session_scope', make_session):
        tracks = mstat.database_tracks_from_mpd(
            mock_config, [track1_info, track2_info, track1_info])

        assert len(tracks) == 3


class TestMpdLoader:

    @patch('suggestive.mstat.initialize_mpd')
    def test_check_duplicates(self, init_mpd):
        init_mpd.side_effect = [
            MagicMock(find=MagicMock(side_effect=OSError)),
            MagicMock(),
        ]

        session = MagicMock()
        (session.query.return_value.join.return_value.group_by.return_value
         .having.return_value.all.return_value) = [MagicMock()]

        loader = mstat.MpdLoader(None)
        loader.check_duplicates(session)

        assert init_mpd.call_count == 2

    @patch('suggestive.mstat.initialize_mpd')
    def test_list_mpd_files(self, init_mpd):
        init_mpd.side_effect = [
            MagicMock(list=MagicMock(side_effect=OSError)),
            MagicMock(),
        ]

        loader = mstat.MpdLoader(None)
        loader._list_mpd_files()

        assert init_mpd.call_count == 2

    @patch('suggestive.mstat.initialize_mpd')
    def test_mpd_info(self, init_mpd):
        init_mpd.side_effect = [
            MagicMock(listallinfo=MagicMock(side_effect=OSError)),
            MagicMock(),
        ]

        loader = mstat.MpdLoader(None)
        loader._mpd_info(None)

        assert init_mpd.call_count == 2
