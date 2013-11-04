Development
===========

Improvements
------------
- Search can now be performed forward or backward
- Playlist now supports search and shares the same pattern with the library
- Save/load playlists

Bug Fixes
---------
- Search works properly when library is updated or albums are expanded
- Fixed adding/removing buffers in vertical orientation


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
