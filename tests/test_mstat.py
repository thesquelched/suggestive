from unittest.mock import patch, MagicMock
from suggestive import mstat


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
