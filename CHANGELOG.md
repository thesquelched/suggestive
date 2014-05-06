Development
===========

Improvements
------------
- Greatly improved responsiveness for playlist commands, e.g. enqueue, delete,
  play
- Added database indexes to generally speed up database lookups
- Various logging improvements

Bug Fixes
---------
- Fixed some database locking issues that would occur during updates


Version 0.3.0
=============

Improvements
------------
- Search can now be performed forward or backward
- Playlist now supports search and shares the same pattern with the library
- Save/load playlists
- You may now rearrange items in the playlist using the `m` binding
- Added custom orderer commands, similar to the 'default_orderer' option
- Added a 'recent scrobbles' buffer that also lists tracks played in the
  current session
- Replaced the `love` and `unlove` commands with the `L` binding, which toggles
  the loved status on the focused item

Bug Fixes
---------
- Improved reliability due to a large-scale refactor
- Collapsing an album now properly focuses on that album, instead of the next
  one
- The library attempts to remember the last selected album when the album list
  is updated
- Search works properly when library is updated or albums are expanded
- Fixed adding/removing buffers in vertical orientation
- Loved ordering no longer reintroduces filtered-out albums
- Cycling through buffers works when the next buffer won't accept focus
- Fixed several bugs with database updates


Version 0.2.1
=============

Improvements
------------
- Playlist displays whether a track is loved or banned
- Playlist now has go-to-top/bottom bindings (`g` and `G`, respectively)
- Toggle whether or not to display album order scores in the library

Bug Fixes
----------
- Expanding an album now puts the album at the top of the screen, so that
  all of the tracks are visible
- (Un)loving a track in the playlist will be reflected in the corresponding
  expanded album in the library, if any
- Added missing alembic package data
- Fixed issue in which tracks from different albums with the same name were
  associated with the same album
- `suggestive` database updates now correctly wait for the MPD database to
  finish updating


Version 0.2.0
=============

Improvements
-------------
- Added database migrations to make future releases smoother

Bug Fixes
----------
- Removed some slowness when updating the playlist
