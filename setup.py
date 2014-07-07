from setuptools import setup


setup(
    name='suggestive',
    version='0.3.0',
    description='Python MPD client with integrated Last.FM support',
    author='Scott Kruger',
    author_email='thesquelched+python@gmail.com',
    url='https://github.com/thesquelched/suggestive',
    keywords='suggestive mpd lastfm music',

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
        'urwid>=1.1.1',
        'python-mpd2>=0.5.1',
        'requests>=1.2.3',
        'SQLAlchemy>=0.9.6',
        'alembic>=0.6.0',
    ],
)
