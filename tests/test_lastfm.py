from suggestive.lastfm import LastFM

import pytest
import pylastfm
from unittest.mock import patch, MagicMock


@pytest.fixture(scope='module', autouse=True)
def disable_write(request):
    patcher = patch.object(LastFM, '_save_session', MagicMock())
    patcher.start()
    request.addfinalizer(patcher.stop)


@pytest.mark.parametrize('auth_returns', [
    [pylastfm.FileError, None],
    [None],
])
@patch.object(LastFM, '_authorize_application', MagicMock())
def test_authorization(auth_returns, mock_config):
    with patch('pylastfm.client.LastFM.authenticate') as authenticate:
        authenticate.side_effect = auth_returns

        lastfm = LastFM(mock_config)
        assert isinstance(lastfm.client, pylastfm.LastFM)


@patch.object(LastFM, '_get_user_permission')
@patch('pylastfm.LastFM')
def test_authorization_process(lastfm, get_user_permission, mock_config):
    instance = MagicMock()
    lastfm.return_value = instance

    instance.authenticate.side_effect = [pylastfm.FileError, None]
    LastFM(mock_config)

    assert instance.auth.get_token.call_count == 1
    assert get_user_permission.call_count == 1
    assert instance.auth.get_session.call_count == 1
