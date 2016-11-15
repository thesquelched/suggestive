import suggestive.widget as widget
import suggestive.mstat as mstat
import suggestive.signals as signals
from suggestive.error import CommandError
from suggestive.mvc.base import View, Model, Controller, TrackModel
from suggestive.buffer import Buffer
from mpd import CommandError as MpdCommandError
from suggestive.action import lastfm_love_track

import urwid
from math import floor, log10
import logging


logger = logging.getLogger('suggestive.playlist')
logger.addHandler(logging.NullHandler())


######################################################################
# Models
######################################################################

class PlaylistModel(Model):

    def __init__(self):
        super(PlaylistModel, self).__init__()
        self._tracks = []
        self._mpd_playlist = []
        self._playlist_tracks = {}
        self._now_playing = None

    def __repr__(self):
        return '<PlaylistModel>'

    @property
    def tracks(self):
        return self._tracks

    @tracks.setter
    def tracks(self, newtracks):
        self._tracks = newtracks
        self.update_playlist_tracks()
        self.update()

    @property
    def now_playing(self):
        return self._now_playing

    @now_playing.setter
    def now_playing(self, value):
        self._now_playing = value

    @property
    def mpd_playlist(self):
        return self._mpd_playlist

    @mpd_playlist.setter
    def mpd_playlist(self, tracks):
        self._mpd_playlist = tracks
        self.update_playlist_tracks()

    def track_ids(self, tracks):
        return [track.db_track.id for track in tracks]

    def update_playlist_tracks(self):
        self._playlist_tracks = {
            item['id']: track
            for item, track in zip(self.mpd_playlist, self.tracks)
        }

    @property
    def playlist_tracks(self):
        return self._playlist_tracks


######################################################################
# Controllers
######################################################################

class PlaylistController(Controller):

    def __init__(self, model, conf, loop):
        super(PlaylistController, self).__init__(model, conf, loop)
        self._conf = conf

        # Connections
        self._mpd = mstat.initialize_mpd(conf)

        # Initialize
        self.update_model()

    @property
    def playlist_size(self):
        return len(self.model.tracks)

    # Signal handler
    @mstat.mpd_retry
    def play_track(self, view):
        logger.info('Play playlist track: {}'.format(view.canonical_text))
        self._mpd.play(view.model.number)

    @mstat.mpd_retry
    def delete_track(self, view):
        logger.info('Delete playlist track: {}'.format(view.canonical_text))
        self._mpd.delete(view.model.number)
        self.update_model()

    # Signal handler
    def love_track(self, view):
        logger.info('Toggle loved for playlist track: {}'.format(
            view.canonical_text))

        db_track = view.model.db_track
        if not db_track.id:
            logger.error('Can not mark invalid track loved')
            return

        loved = db_track.lastfm_info.loved if db_track.lastfm_info else False

        self.async_run(lastfm_love_track, self.conf, db_track, not loved)
        mstat.db_track_love(self.conf, db_track, loved=not loved)

        new_track = mstat.get_db_track(self.conf, db_track.id)
        view.model.db_track = new_track

        # Update expanded track model
        lib_ctrl = self.controller_for('library')
        track_model = lib_ctrl.model.track_model_for(db_track)
        if track_model:
            track_model.db_track = new_track

    @mstat.mpd_retry
    def clear(self):
        self._mpd.stop()
        self._mpd.clear()
        self.update_model()

    @mstat.mpd_retry
    def load_playlist(self, name):
        self._mpd.stop()
        self._mpd.clear()
        self._mpd.load(name)

    @mstat.mpd_retry
    def save_playlist(self, name):
        try:
            self._mpd.rm(name)
        except Exception:
            pass

        self._mpd.save(name)

    @mstat.mpd_retry
    def mpd_playlist(self):
        return self._mpd.playlistinfo()

    @mstat.mpd_retry
    def now_playing(self):
        current = self._mpd.currentsong()
        if current and 'pos' in current:
            return int(current['pos'])
        else:
            return None

    def playlist_tracks(self, playlist, positions):
        logger.debug('Get playlist tracks from db')

        db_tracks = mstat.database_tracks_from_mpd(self.conf, playlist)

        logger.debug('Create models')
        return [
            TrackModel(db_track, position)
            for db_track, position in zip(db_tracks, positions)
        ]

    def track_models(self, playlist, current_tracks):
        """
        Construct a list of TrackModels from the current playlist and the
        current list of track models
        """
        new_tracks = [None] * len(playlist)
        missing = []
        for position, item in enumerate(playlist):
            if item['id'] in current_tracks:
                track = TrackModel(
                    current_tracks[item['id']].db_track,
                    position)
                new_tracks[position] = track
            else:
                missing.append((position, item))

        if missing:
            positions, missing_playlist = zip(*missing)
            for track in self.playlist_tracks(missing_playlist, positions):
                new_tracks[track.number] = track

        assert None not in new_tracks

        logger.debug('Track models: {}'.format([t.name for t in new_tracks]))

        return new_tracks

    def update_model(self):
        logger.debug('Begin playlist model update')
        playlist = self.mpd_playlist()
        now_playing = self.now_playing()
        if (playlist == self.model.mpd_playlist and
                now_playing == self.model.now_playing):
            logger.debug('No playlist changes; aborting')
            return

        logger.debug('Get current tracks')
        current_tracks = self.model.playlist_tracks

        logger.debug('Set model playlist')

        # Update the playlist immediately so that extraneous attempts to update
        # the playlist will be ignored
        self.model.mpd_playlist = playlist
        self.model.now_playing = now_playing

        logger.debug('Get track models')
        models = self.track_models(playlist, current_tracks)

        logger.debug('Set track models')
        self.model.tracks = models
        logger.debug('Finished playlist model update')

    def track_model_for(self, db_track):
        return next(
            (track for track in self.model.tracks if
             track.db_track.id == db_track.id),
            None
        )

    @mstat.mpd_retry
    def seek(self, position):
        try:
            self._mpd.seekcur(str(position))
        except MpdCommandError as ex:
            logger.error('Could not seek to {}; {}'.format(position, ex))

    @mstat.mpd_retry
    def next_track(self, view):
        self._mpd.next()

    @mstat.mpd_retry
    def previous_track(self, view):
        self._mpd.previous()


######################################################################
# Views
######################################################################

@widget.signal_map({
    'd': signals.DELETE,
    'enter': signals.PLAY,
    'm': signals.MOVE,
    'L': signals.LOVE,
})
class TrackView(urwid.WidgetWrap, View, widget.Searchable):
    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.PLAY, signals.DELETE, signals.MOVE, signals.LOVE]

    TRACK_FORMAT = '{artist} - {album} - {title}{suffix}'

    def __init__(self,
                 model,
                 controller,
                 conf,
                 playing=False,
                 show_bumper=False,
                 focused=False):
        View.__init__(self, model)

        self._controller = controller

        self._show_bumper = show_bumper

        self.content = model.db_track
        self._icon = urwid.SelectableIcon(self.text)

        styles = self.styles(playing, focused)

        super(TrackView, self).__init__(
            urwid.AttrMap(self._icon, *styles))

    def styles(self, playing, focused):
        if focused and playing:
            return ('focus playing',)
        elif focused:
            return ('focus playlist',)
        elif playing:
            return ('playing', 'focus playing')
        else:
            return ('playlist', 'focus playlist')

    @property
    def controller(self):
        return self._controller

    def add_bumper(self, text):
        size = self.controller.playlist_size
        digits = (floor(log10(size)) + 1) if size else 0

        bumper = str(self.model.number)

        return [
            ('bumper', bumper.ljust(digits + 1, ' ')),
            text
        ]

    @property
    def text(self):
        model = self.model
        if model.loved:
            suffix = ' [L]'
        else:
            suffix = ''

        text = self.TRACK_FORMAT.format(
            artist=model.db_artist.name,
            album=model.db_album.name,
            title=model.name,
            suffix=suffix)

        if self._show_bumper:
            return self.add_bumper(text)
        else:
            return text

    @property
    def canonical_text(self):
        model = self.model
        return self.TRACK_FORMAT.format(
            artist=model.db_artist.name,
            album=model.db_album.name,
            title=model.name,
            suffix='')

    @property
    def searchable_text(self):
        return self.canonical_text

    def update(self):
        self._w.original_widget.set_text(self.text)


@widget.signal_map({
    '>': signals.NEXT_TRACK,
    '<': signals.PREVIOUS_TRACK,
})
class PlaylistView(widget.SuggestiveListBox, View):
    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.NEXT_TRACK, signals.PREVIOUS_TRACK]

    def __init__(self, model, controller, conf):
        View.__init__(self, model)

        self._controller = controller
        self._conf = conf

        walker = self.create_walker()
        super(PlaylistView, self).__init__(walker)

    @property
    def controller(self):
        return self._controller

    def update(self, show_bumper=False):
        logger.debug('Updating PlaylistView')

        previous_position = self.focus_position
        walker = self.body

        walker[:] = self.track_views(show_bumper=show_bumper)

        self.focus_remembered_position(previous_position)

    def focus_remembered_position(self, position):
        if len(self.body) == 0:
            return

        try:
            # Try to focus on the same position in the playlist before we
            # updated
            self.set_focus(position)
        except IndexError:
            # If that failed, the playlist probably shrunk due to a deletion,
            # and we were on the last position before the delete.  Therefore,
            # we should be able to focus on the position before the last
            try:
                self.set_focus(position - 1)
            except IndexError:
                # There are no tracks left; don't bother setting focus
                pass

    def track_views(self, show_bumper=False):
        current = self.controller.now_playing()
        focus = self.focus_position if show_bumper else None

        if not self.model.tracks:
            body = [urwid.AttrMap(urwid.Text('Playlist is empty'), 'track')]
        else:
            body = []
            for track_m in self.model.tracks:
                view = TrackView(
                    track_m,
                    self.controller,
                    self._conf,
                    playing=(track_m.number == current),
                    show_bumper=show_bumper,
                    focused=(track_m.number == focus))

                urwid.connect_signal(
                    view,
                    signals.PLAY,
                    self.controller.play_track)
                urwid.connect_signal(
                    view,
                    signals.DELETE,
                    self.controller.delete_track)
                urwid.connect_signal(
                    view,
                    signals.LOVE,
                    self.controller.love_track)

                body.append(view)

        return body

    def create_walker(self):
        body = self.track_views()
        return urwid.SimpleFocusListWalker(body)

    def move_update_index(self, current, index):
        try:
            items = self.body
            n_items = len(items)

            if index >= n_items:
                raise IndexError

            logger.debug('Temporary move from {} to {}'.format(
                current, index))

            if index > current:
                focus = items[current]
                items.insert(index + 1, focus)
                items.pop(current)
            elif index < current:
                focus = items.pop(current)
                items.insert(index, focus)
        except IndexError:
            logger.error('Index out of range')

    def keypress(self, size, key):
        if key == 'c':
            self.controller.clear()
            super(PlaylistView, self).keypress(size, None)
            return True

        return super(PlaylistView, self).keypress(size, key)


######################################################################
# Buffer
######################################################################

class PlaylistBuffer(Buffer):

    ITEM_FORMAT = '{artist} - {album} - {title}{suffix}'

    def __init__(self, conf, loop):
        self.conf = conf
        self.model = PlaylistModel()
        self.controller = PlaylistController(self.model, conf, loop)
        self.view = PlaylistView(self.model, self.controller, conf)

        urwid.connect_signal(self.view, signals.NEXT_TRACK,
                             self.controller.next_track)
        urwid.connect_signal(self.view, signals.PREVIOUS_TRACK,
                             self.controller.previous_track)

        self.current_track = None
        self.status_format = conf.playlist.status_format

        super(PlaylistBuffer, self).__init__(self.view)

        self.update_status('Playlist')

    def setup_bindings(self):
        keybinds = super(PlaylistBuffer, self).setup_bindings()
        keybinds.update({
            'm': self.move_track,
        })

        return keybinds

    def search(self, searcher):
        self.view.search(searcher)

    def next_search(self):
        self.view.next_search_item()

    def will_accept_focus(self):
        return len(self.model.tracks) > 0

    def move_track(self):
        logger.debug('Start playlist move')
        self.view.update(show_bumper=True)

        self.move_prompt = widget.PlaylistMovePrompt(
            self.view.focus_position)
        urwid.connect_signal(
            self.move_prompt,
            signals.PROMPT_DONE,
            self.complete_move)
        urwid.connect_signal(
            self.move_prompt,
            signals.UPDATE_INDEX,
            self.view.move_update_index)

        self.update_footer(urwid.AttrMap(self.move_prompt, 'footer'))
        self.update_focus('footer')

    def complete_move(self, value, current_position):
        urwid.disconnect_signal(
            self,
            self.move_prompt,
            signals.PROMPT_DONE,
            self.complete_move)
        urwid.disconnect_signal(
            self,
            self.move_prompt,
            signals.UPDATE_INDEX,
            self.view.move_update_index)

        self.update_focus('body')

        try:
            new_index = int(value)
            logger.debug('Moving playlist track from {} to {}'.format(
                current_position, new_index))

            mpd = mstat.initialize_mpd(self.conf)
            mpd.move(current_position, new_index)
            self.view.focus_position = new_index
        except (TypeError, ValueError):
            logger.error('Invalid move index: {}'.format(value))

        self.view.update()
        self.update()

    def now_playing_index(self, mpd):
        current = mpd.currentsong()
        if current and 'pos' in current:
            return int(current['pos'])
        else:
            return None

    def track_changed(self):
        mpd = mstat.initialize_mpd(self.conf)
        return self.current_track != self.now_playing_index(mpd)

    def update(self, *args):
        self.controller.update_model()

    def update_playing_status(self):
        self.update_status(self.status_text())

    def status_params(self, status, track):
        elapsed_time = int(status.get('time', '0').split(':')[0])
        total_time = int(track.get('time', '0').split(':')[0])

        elapsed_min, elapsed_sec = elapsed_time // 60, elapsed_time % 60
        total_min, total_sec = total_time // 60, total_time % 60

        state = status['state']
        if state == 'play':
            state = 'Now Playing'

        return {
            'status': state[0].upper() + state[1:],
            'time_elapsed': '{}:{}'.format(
                elapsed_min,
                str(elapsed_sec).rjust(2, '0')
            ),
            'time_total': '{}:{}'.format(
                total_min,
                str(total_sec).rjust(2, '0')
            ),
            'title': track.get('title', 'Unknown Track'),
            'artist': track.get('artist', 'Unknown Artist'),
            'album_artist': track.get('album_artist', 'Unknown Artist'),
            'album': track.get('album', 'Unknown Album'),
            'filename': track['file'],
            'track': track.get('track', 'Unknown'),
            'date': track.get('date', 'Unknown'),
        }

    def status_text(self):
        mpd = mstat.initialize_mpd(self.conf)
        status = mpd.status()

        text = ''

        songid = status.get('songid')
        if songid:
            track = mpd.playlistid(songid)
            if track:
                params = self.status_params(status, track[0])
                text = self.status_format.format(**params)
                return 'Playlist | ' + text

        return 'Playlist'

    def clear_mpd_playlist(self):
        self.controller.clear()

    def load_playlist(self, name=None):
        if name is None:
            raise CommandError('Missing parameter: name')

        try:
            self.controller.load_playlist(name)
            self.update_footer('Loaded playlist {}'.format(name))
            return True
        except MpdCommandError as ex:
            logger.debug(ex)
            raise CommandError("Unable to load playlist '{}'".format(
                name))

    def save_playlist(self, name=None):
        if name is None:
            raise CommandError('Missing parameter: name')

        try:
            self.controller.save_playlist(name)
            self.update_footer('Saved playlist {}'.format(name))
            return True
        except MpdCommandError as ex:
            logger.debug(ex)
            raise CommandError("Unable to save playlist '{}'".format(
                name))

    def seek(self, position=None):
        if position is None:
            return

        self.controller.seek(position)
