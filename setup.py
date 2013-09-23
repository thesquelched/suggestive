try:
    from setuptools import setup
    kwArgs = dict(
        install_requires=[
            'urwid>=1.1.1',
            'python-mpd2>=0.5.1',
            'SQLAlchemy>=0.8.1',
            'requests>=1.2.3',
        ],
    )
except ImportError:
    from distutils.core import setup
    kwArgs = {}


setup(
    name='suggestive',
    version='0.1',
    description='Python MPD client with integrated Last.FM support',
    author='Scott Kruger',
    author_email='thesquelched+python@gmail.com',
    url='https://github.com/thesquelched/suggestive',
    keywords='suggestive mpd lastfm music',

    packages=['suggestive'],
    scripts=['scripts/suggestive'],

    **kwArgs
)
