from suggestive.lastfm import LastFM
from suggestive.config import Config

import pytest
import pylastfm
import shutil
from six.moves.configparser import RawConfigParser
from tempfile import NamedTemporaryFile, mkdtemp

try:
    from unittest.mock import patch, MagicMock
except ImportError:
    from mock import patch, MagicMock


@pytest.fixture(autouse=True)
def disable_write(request):
    patcher = patch.object(LastFM, '_save_session', MagicMock())
    patcher.start()
    request.addfinalizer(patcher.stop)


@pytest.fixture(scope='session')
def config_dir(request):
    path = mkdtemp()

    @request.addfinalizer
    def clean_dir():
        shutil.rmtree(path)

    return path


@pytest.fixture(scope='session')
def mock_config(config_dir):
    data = dict(
        general=dict(
            conf_dir=config_dir,
            verbose='true',
            update_on_startup='false',
        ),
        mpd=dict(
            host='localhost',
            port=6600,
        ),
        lastfm=dict(
            scrobble_days=180,
            user='user',
            api_key='apikey',
            api_secret='secret',
        ),
    )
    config = RawConfigParser()
    for section, options in data.items():
        config.add_section(section)
        for key, value in options.items():
            config.set(section, key, value)

    with NamedTemporaryFile(mode='w') as temp:
        config.write(temp)
        temp.flush()

        with patch('suggestive.config.CONFIG_PATHS', [temp.name]):
            return Config()


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
