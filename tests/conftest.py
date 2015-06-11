from suggestive.config import Config

import pytest
from configparser import RawConfigParser
from tempfile import NamedTemporaryFile, mkdtemp
import shutil
from unittest.mock import patch


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
            verbose=True,
            update_on_startup=False,
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
