Version 0.2.1
=============

Bug Fixes
----------
- Expanding an album now puts the album at the top of the screen, so that
  all of the tracks are visible
- (Un)loving a track in the playlist will be reflected in the corresponding
  expanded album in the library, if any
- Added missing alembic package data

Improvements
------------
- Playlist displays whether a track is loved or banned
- Playlist now has go-to-top/bottom bindings (`g` and `G`, respectively)
- Toggle whether or not to display album order scores in the library


Version 0.2.0
=============

Bug Fixes
----------
- Removed some slowness when updating the playlist

Improvements
-------------
- Added database migrations to make future releases smoother