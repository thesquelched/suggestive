suggestive
==========

Python MPD client with integrated Last.FM support

Installation
============

`suggestive` required python 3.2 or higher.  Also, you'll probably want a
Last.FM scrobbler to make use of the album ordering features.  I personally
prefer [mpdscribble](http://mpd.wikia.com/wiki/Client:Mpdscribble), but
whatever floats your boat.

Installation via git
--------------------

```bash
$ git clone https://github.com/thesquelched/suggestive.git
$ cd suggestive
$ python3 setup.py install
```

Usage
=====

```bash
$ suggestive -h
usage: suggestive [-h] [--log LOG] [--config CONFIG]

Suggestive

optional arguments:
  -h, --help            show this help message and exit
  --log LOG, -l LOG     Log file path
  --config CONFIG, -c CONFIG
                        Config file path
```

Configuration
=============

`suggestive` looks for a configuration file in the following places (in-order):

2. `$HOME/.suggestive.conf`
3. `/etc/suggestive.conf`

You can also force a certain config path using the `-c` option. Before you can
run `suggestive`, you must supply two pieces of information: your Last.FM
username and a Last.FM API key.  You can sign up for an API key
[here](http://www.last.fm/api/accounts).

Here is a minimal `suggestive` configuration file:

```
[lastfm]
user = my_lastfm_user
api_key = 0123456789abcdefghijklmnopqrstuv

# For LastFM write access (optional)
api_secret = 141iojhu789uihy78uiho9uih89080
```

A [sample configuration file](suggestive.conf.example) is available.


Known Issues
============

`suggestive` is still very early in development, although it is quite
functional already.  However, there are some outstanding issues:

- Non-fatal exceptions may temporarily show up in the terminal
- Opening/closing new buffers doesn't work well for vertical orientation

Sometimes, you can resolve an issue by deleting/renaming the `suggestive`
database file (`$HOME/.suggestive/music.db` by default), and then re-running
suggestive, which will rebuild the database.  If this does not resolve the
problem, please open up a GitHub issue.


Bindings
========

`suggestive` uses vim-like keybindings.

General
-------

- `q`, `<C-c>` - Quit
- `:` - Enter command mode
- `u` - Update database
- `p` - Pause/resume playback
- `<C-w>` - Switch between open buffers
- `r` - Reload library (useful to recalculate album order)

Movement
--------

- `h`, `arrow-left` - Left
- `j`, `arrow-down` - Down
- `k`, `arrow-up` - Up
- `l`, `arrow-right` - Right
- `<C-f>`, `page-down` - Scroll one page down
- `<C-b>`, `page-up` - Scroll one page up
- `g`, `home` - Go to top
- `G`, `end` - Go to bottom

Search
------

- `/` - Search forward
- `?` - Search backward
- `n` - Next search result
- `N` - Previous search result

Library
-------

- `space` - Enqueue album/track
- `enter` - Play album/track
- `z` - Toggle tracks fold (i.e. toggle album tracks display)

Playlist
------

- `c` - Clear playlist
- `d` - Remove track
- `enter` - Play track


Command mode
============

General commands
----------------

- `q` - quit
- `playlist` - toggle playlist buffer
- `library` - toggle library buffer
- `orientation` - (Alias: `or`) toggle between vertical and horizontal orientations
- `score <show=bool>` - Toggle or set whether or not to show the ordering score
  in the library


Library
-------

`suggestive` tries to order your library so that albums you'd probably like to listen to are close to the top, while albums you don't like are towards the bottom.  However, you can change what's displayed using one or more filters or orderers.  Note that you can compose multiple filters/orderers by issuing succesive commands.

- `<ESC>` - Clear all filters/orderers, restoring the default ordering (may be
  disabled with the `library/esc_resets_orderers` config option)
- `:album <name>` - (Alias: `al`) Only display albums matching `name`
  (case-insensitive)
- `:artist <name>` - (Alias: `ar`) Only display albums of the artist matching
  `name` (case-insensitive)
- `:loved <min=0.0> <max=1.0> <reverse=false>` - (Alias: `lo`) Display albums
  in order of fraction of tracks loved. You may optional specify the minimum or
  maximum fraction of loved tracks for an album to be displayed
- `:playcount <min=0.0> <max=None> <reverse=false>` - (Alias: `pc`) Display
  albums in order of fractional playcount (i.e. number of scrobbles / number of
  tracks).  Note that this number can be greater than 1
- `:banned <remove_banned=true>` - Penalize (or remove) albums with banned
  tracks from the library
- `:sort <reverse=false>` - Sort albums using the string 'artist - album'
- `:reset` - Reset library order to default
- `:unorder` - Remove all orderings (Alias: `unordered`)
- `:love` - Mark the selected album/track loved in LastFM
- `:unlove` - Mark the selected album/track unloved in LastFM


Development
===========

Database Migrations
-------------------

I use `alembic` to generate migrations for `suggestive`'s internal sqlite
database.  To generate database migrations:

1. Install the latest version of `suggestive` and run it at least once to
   migrate to the latest database version
2. Copy `alembic.ini.template` to `alembic.ini`
3. Replace `<INSERT SUGGESTIVE DB PATH HERE>` with the path to your
   `suggestive` database, e.g. `/home/myuser/.suggsetive/music.db`.
4. Make changes to the database model
5. Create a new migration file: `alembic revision --autogenerate -m '<COMMIT MESSAGE>'`
