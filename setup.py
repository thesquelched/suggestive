from setuptools import setup
import os.path


def read_version():
    """Read the library version"""
    path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)),
        'suggestive',
        '_version.py'
    )
    with open(path) as f:
        exec(f.read())
        return locals()['__version__']


def download_url():
    return 'https://github.com/thesquelched/suggestive/tarball/{0}'.format(
        read_version())


CHANGELOG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'CHANGELOG.md')


if __name__ == '__main__':
    setup(
        name='suggestive',
        version=read_version(),
        description='Python MPD client with integrated Last.FM support',
        author='Scott Kruger',
        author_email='scott@chojin.org',
        url='https://github.com/thesquelched/suggestive',
        keywords='suggestive mpd lastfm music',
        download_url=download_url(),

        packages=['suggestive'],
        entry_points={
            'console_scripts': [
                'suggestive = suggestive.app:main',
            ],
        },

        package_data={
            'suggestive': [
                'alembic/env.py',
                'alembic/script.py.mako',
                'alembic/versions/*.py'
            ],
        },
        install_requires=[
            'alembic>=0.6.0',
            'pylastfm>=0.2.0',
            'python-mpd2>=0.5.1',
            'requests>=1.2.3',
            'SQLAlchemy>=0.9.6',
            'urwid>=1.1.1',
        ],
    )
