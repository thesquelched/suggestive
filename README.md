suggestive
==========

<!--#Use MPD and Last.FM to suggest music to listen to-->
Python MPD client with integrated Last.FM

Installation
============

Prerequisites
-------------

`suggestive` required python 3.2 or higher.

```bash
$ sudo pip-3.2 install urwid python-mpd2 SQLAlchemy requests
```

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

Movement
--------

- `h`, arrow-left - Left
- `j`, arrow-down - Down
- `k`, arrow-up - Up
- `l`, arrow-right - Right
- `<C-f>`, page-down - Scroll one page down
- `<C-b>`, page-up - Scroll one page up
- `g`, `home` - Go to top
- `G`, `end` - Go to bottom

Search
------

- `/` - Search forward
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
- `orientation` - toggle between vertical and horizontal orientations


Library
-------

`suggestive` tries to order your library so that albums you'd probably like to listen to are close to the top, while albums you don't like are towards the bottom.  However, you can change what's displayed using one or more filters or orderers.  Note that you can compose multiple filters/orderers by issuing succesive commands.

- `<ESC>` - Clear all filters/orderers, restoring the default ordering
- `:album <name>` - Only display albums matching `name` (case-insensitive)
- `:artist <name>` - Only display albums of the artist matching `name` (case-insensitive)
- `:loved <min=0.0> <max=1.0>` - Display albums in order of fraction of tracks loved. You may optional specify the minimum or maximum fraction of loved tracks for an album to be displayed
- `:playcount <min=0.0> <max=None>` - Display albums in order of fractional playcount (i.e. number of scrobbles / number of tracks).  Note that this number can be greater than 1
- `:banned <remove_banned=true>` - Penalize (or remove) albums with banned tracks from the library
- `:sort` - Sort albums using the string 'artist - album'
- `:unorder` - Remove all orderings
- `:love` - Mark the selected album/track loved in LastFM
- `:unlove` - Mark the selected album/track unloved in LastFM


Configuration
=============

`suggestive` looks for a configuration file in the following places (in-order):

1. `$PWD/.suggestive.conf`
2. `$HOME/.suggestive.conf`
3. `/etc/suggestive.conf`

Before you can run `suggestive`, you must supply two pieces of information: your Last.FM username and a Last.FM API key.  You can sign up for an API key [here](http://www.last.fm/api/accounts).

Here is a minimal `suggestive` configuration file:

```
[lastfm]
user = my_lastfm_user
api_key = 0123456789abcdefghijklmnopqrstuv
```

A sample configuration file is included with suggestive.
