suggestive
==========

Python MPD client with integrated Last.FM support

Installation
============

`suggestive` required python 3.5 or higher.  Also, you'll probably want a
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
  --update, -u          Update database
  --no_update, -U       Do not update database
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
api_secret = 141iojhu789uihy78uiho9uih89080
```

A [sample configuration file](suggestive.conf.example) is available.


Bindings
========

`suggestive` uses vim-like keybindings.

General
-------

- `q`, `<C-c>` - Quit
- `:` - Enter command mode
- `u` - Update mpd
- `U` - Force `suggestive` database update
- `p` - Pause/resume playback
- `<C-w>` - Switch between open buffers
- `r` - Reload library (useful to recalculate album order)
- `L` - Toggle track loved status

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
- `i` - Toggle ignored (ignored tracks always appear at the bottom of the
        library)

Playlist
------

- `c` - Clear playlist
- `d` - Remove track
- `enter` - Play track
- `m` - Enter move mode
- `>` - Next track
- `<` - Previous track


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

Playback
--------

- `seek <seconds>` - Seek the currently playing track to the given position.
  If `seconds` begins with `+` or `-`, then seek to the given time relative to
  the present.


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
- `:modified <reverse=false>` - (Alias: `mod`) Sort by file modification time,
  which can be useful for finding recently-downloaded albums
- `:playcount <min=0.0> <max=None> <reverse=false>` - (Alias: `pc`) Display
  albums in order of fractional playcount (i.e. number of scrobbles / number of
  tracks).  Note that this number can be greater than 1
  tracks from the library
- `:sort <reverse=false>` - Sort albums using the string 'artist - album'
- `:reset` - Reset library order to default
- `:unorder` - Remove all orderings (Alias: `unordered`)

Orderers
--------

`suggestive` provides the capability of sorting your library with one or more filters or "orderers".  It assigns a simple ranking to albums according to the orderers you have specified, with higher ranked albums at the top.  The default ordering gives higher weight to albums with more loved tracks, as well as those with a higher fractional playcount.  These orderers work in concert, so an album with many loved tracks might be ranked similarly to one that has been played many times, but lower to one that has both.  The available orderer commands are `album`, `artist`, `loved`, `playcount`, `sort`, and `modified`.  See the library commands section for more information.

Either hitting `esc` or using the `:reset` command will reset the orderers back to the default, which is `loved; playcount`.  You can change the default in your config file using the `library.default_order` option.  The format is just a semicolor-separated list of orderer commands, without the preceding colon.  For example, this sets the default ordering to modification date in reverse order:

```
[library]
default_order = modified reverse=true
```

If you wish to work from scratch with no ordering, use the `:unorder` command.

### Custom order commands

You can combine one or more order commands to create your own custom orderer
commands.  This can be done in your config file, similarly to setting a default
orderer; see the example config file for more information.

Here's an example that creates a command `mycommand` that uses the `loved` and
`playcount` orderers:

```
[custom_orderers]
mycommand = unorder; loved max=0; playcount
```

`mycommand` will then be accessible from command mode in the library buffer,
just like any other orderer.


Known Issues
============

Although I am using `suggestive` as my full-time MPD client, it's still
somewhat early in development, and you might encounter some problems while
using it.

Sometimes, you can resolve an issue by deleting/renaming the `suggestive`
database file (`$HOME/.suggestive/music.db` by default), and then re-running
suggestive, which will rebuild the database.  If this does not resolve the
problem, please open up a GitHub issue.


Development Notes
=================

Database Migrations
-------------------

I use `alembic` to generate migrations for `suggestive`'s internal sqlite
database.  To generate database migrations:

1. Install the latest version of `suggestive` and run it at least once to
   migrate to the latest database version
2. Copy `alembic.ini.template` to `alembic.ini`
3. Replace `<INSERT SUGGESTIVE DB PATH HERE>` with the path to your
   `suggestive` database, e.g. `/home/myuser/.suggestive/music.db`.
4. Make changes to the database model
5. Create a new migration file: `alembic revision --autogenerate -m '<COMMIT MESSAGE>'`
