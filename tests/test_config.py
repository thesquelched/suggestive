import pytest
from contextlib import contextmanager
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock, patch

from suggestive.config import Config, interpolate


@contextmanager
def make_config(**sections):
    formatted = ((name, '\n'.join('{} = {}'.format(*setting) for setting in settings.items()))
                 for name, settings in sections.items())
    content = '\n'.join('[{}]\n{}\n'.format(name, settings) for name, settings in formatted)

    with NamedTemporaryFile(mode='w') as handle:
        handle.write(content)
        handle.seek(0)

        yield MagicMock(
            config=handle.name,
            log=None,
            update=None,
            no_update=None,
            reinitialize_scrobbles=None,
        )


@pytest.fixture(scope='module', autouse=True)
def mock_config_paths(request):
    patcher = patch('suggestive.config.CONFIG_PATHS', [])
    request.addfinalizer(patcher.stop)
    patcher.start()


@pytest.mark.parametrize('value,config,result', (
    ('literal', {}, 'literal'),
    (1, {}, 1),
    ('{foo}', {'foo': 1}, '1'),
    ('{foo} {bar}', {'foo': 1, 'bar': 2}, '1 2'),
    ('{foo} {foo}', {'foo': 1}, '1 1'),
    ('%(foo)s', {'foo': 1}, '1'),
    ('%(foo)s %(bar)s', {'foo': 1, 'bar': 2}, '1 2'),
    ('%(foo)s %(foo)s', {'foo': 1}, '1 1'),
))
def test_interpolate(value, config, result):
    assert interpolate(value, config) == result


def test_empty_config():
    with make_config() as argv:
        conf = Config(argv)

    assert conf.general.conf_dir == '$HOME/.suggestive'
    assert conf.general.database == '$HOME/.suggestive/music.db'
    assert conf.general.highcolor
    assert conf.general.default_buffers == ['library', 'playlist']
    assert conf.general.orientation == 'horizontal'
    assert conf.general.log == '$HOME/.suggestive/log.txt'
    assert not conf.general.verbose
    assert not conf.general.log_sql_queries
    assert conf.general.session_file == '$HOME/.suggestive/session'
    assert not conf.general.update_on_startup

    assert conf.mpd.host == 'localhost'
    assert conf.mpd.port == 6600

    assert conf.lastfm.scrobble_days == 180
    assert conf.lastfm.user == ''
    assert conf.lastfm.api_key == ''
    assert conf.lastfm.api_secret == ''
    assert not conf.lastfm.log_responses
    assert conf.lastfm.url == 'http://ws.audioscrobbler.com/2.0'

    assert conf.playlist.status_format == ('{status}: {artist} - {title} '
                                           '[{time_elapsed}/{time_total}]')
    assert not conf.playlist.save_playlist_on_close
    assert conf.playlist.playlist_save_name == 'suggestive.state'

    assert conf.library.ignore_artist_the
    assert conf.library.default_order == ['loved', 'playcount']
    assert not conf.library.show_score
    assert conf.library.esc_resets_orderers

    assert conf.scrobbles.initial_load == 50

    assert conf.custom_orderers == {}


@pytest.mark.parametrize('orderers,result', (
    ('', []),
    ('playcount', ['playcount']),
    ('playcount min=0.5; loved', ['playcount min=0.5', 'loved']),
))
def test_default_orderers(orderers, result):
    with make_config(library={'default_order': orderers}) as argv:
        conf = Config(argv)

    assert conf.library.default_order == result
    assert conf.library.ignore_artist_the


@pytest.mark.parametrize('buffers,result', (
    ('', []),
    ('scrobbles', ['scrobbles']),
    ('scrobbles, playlist, library', ['scrobbles', 'playlist', 'library']),
))
def test_default_buffers(buffers, result):
    with make_config(general={'default_buffers': buffers}) as argv:
        conf = Config(argv)

    assert conf.general.default_buffers == result


@pytest.mark.parametrize('orderers,result', (
    ({'first': ''}, {'first': []}),
    ({'first': 'playcount; loved'}, {'first': ['playcount', 'loved']}),
    ({'first': 'playcount; loved', 'second': 'modified'},
     {'first': ['playcount', 'loved'], 'second': ['modified']}),
))
def test_custom_orderers(orderers, result):
    with make_config(custom_orderers=orderers) as argv:
        conf = Config(argv)

    assert conf.custom_orderers == result
