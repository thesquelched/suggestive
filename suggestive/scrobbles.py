import urwid
import suggestive.signals as signals
from suggestive.mvc import View, Model, Controller
import suggestive.mstat as mstat
import suggestive.widget as widget
from suggestive.buffer import Buffer
import logging
from mpd import CommandError as MpdCommandError
from itertools import groupby


logger = logging.getLogger('suggestive.scrobbles')
logger.addHandler(logging.NullHandler())


######################################################################
# Models
######################################################################

class DayModel(Model):

    def __init__(self, date):
        super(DayModel, self).__init__()
        self._date = date

    @property
    def date(self):
        return self._date


class PlayModel(Model):

    def __init__(self, db_track):
        super(PlayModel, self).__init__()
        self._db_track = db_track

    @property
    def db_track(self):
        return self._db_track

    @property
    def db_artist(self):
        return self._db_track.artist

    @property
    def db_album(self):
        return self._db_track.album

    @property
    def loved(self):
        info = self._db_track.lastfm_info
        return info and info.loved

    @property
    def banned(self):
        info = self._db_track.lastfm_info
        return info and info.banned


class ScrobbleModel(Model):

    def __init__(self, db_scrobble):
        super(ScrobbleModel, self).__init__()
        self._db_scrobble = db_scrobble

    @property
    def db_scrobble(self):
        return self._db_scrobble

    @db_scrobble.setter
    def db_scrobble(self, scrobble):
        self._db_scrobble = scrobble
        self.update()

    @property
    def date(self):
        return self.db_scrobble.time.date()

    @property
    def db_track(self):
        return self._db_scrobble.track

    @property
    def db_artist(self):
        return self.db_track.artist

    @property
    def db_album(self):
        return self.db_track.album

    @property
    def loved(self):
        info = self.db_track.lastfm_info
        return info and info.loved

    @property
    def banned(self):
        info = self.db_track.lastfm_info
        return info and info.banned


class ScrobbleListModel(Model):

    def __init__(self):
        super(ScrobbleListModel, self).__init__()

        self._scrobbles = []  # Last.FM scrobbles
        self._plays = []  # Local plays that may not have been scrobbled

    def __repr__(self):
        return '<ScrobbleListModel>'

    @property
    def scrobbles(self):
        return self._scrobbles

    @scrobbles.setter
    def scrobbles(self, newscrobbles):
        self._scrobbles = newscrobbles
        self.update()

    @property
    def plays(self):
        return self._plays

    @plays.setter
    def plays(self, newplays):
        self._plays = newplays
        self.update()


######################################################################
# Controller
######################################################################

class ScrobbleListController(Controller):

    def __init__(self, model, conf, async_runner):
        super(ScrobbleListController, self).__init__(model, conf, async_runner)
        self.current_song_id = None

    def load_more_scrobbles(self, position):
        n_items = len(self.model.scrobbles)
        n_load = 1 + position - n_items

        # TODO: Convert using just conf
        scrobbles = mstat.get_scrobbles(self.conf, n_load, n_items)
        models = [ScrobbleModel(scrobble) for scrobble in scrobbles]
        if models:
            self.model.scrobbles += models

    def reload(self):
        """Re-fetch the list of scrobbles from the database"""
        logger.debug('Reload scrobbles')
        scrobbles = mstat.get_scrobbles(
            self.conf, len(self.model.scrobbles), 0)
        models = [ScrobbleModel(scrobble) for scrobble in scrobbles]
        self.model.scrobbles = models

    def insert_new_song_played(self):
        mpd = mstat.initialize_mpd(self.conf)
        status = mpd.status()

        songid = status.get('songid')
        if songid != self.current_song_id:
            try:
                info = mpd.playlistid(songid)[0]
                db_track = mstat.database_track_from_mpd(
                    self.conf,
                    info)

                play_model = PlayModel(db_track)
                self.model.plays.insert(0, play_model)
                self.model.update()
                logger.debug('Plays: {}'.format(self.model.plays))

                self.current_song_id = songid
            except (MpdCommandError, IndexError):
                pass


######################################################################
# Views
######################################################################

class DayView(urwid.WidgetWrap, View):

    def __init__(self, model):
        View.__init__(self, model)

        icon = urwid.Text(self.text)
        view = urwid.AttrMap(icon, 'scrobble date')
        urwid.WidgetWrap.__init__(self, view)

    @property
    def text(self):
        return self.model.date.strftime('%Y-%m-%d')


class ScrobbleView(urwid.WidgetWrap, View, widget.Searchable):
    __metaclass__ = urwid.signals.MetaSignals
    signals = []

    TRACK_FORMAT = '{artist} - {album} - {title}{suffix}'
    STYLES = ('scrobble', 'focus scrobble')

    def __init__(self, model, controller):
        View.__init__(self, model)

        self._controller = controller
        self._icon = urwid.SelectableIcon(self.text)

        view = urwid.AttrMap(self._icon, *self.STYLES)
        urwid.WidgetWrap.__init__(self, view)

    @property
    def text(self):
        model = self.model
        if model.loved:
            suffix = ' [L]'
        elif model.banned:
            suffix = ' [B]'
        else:
            suffix = ''

        return self.TRACK_FORMAT.format(
            artist=model.db_artist.name,
            album=model.db_album.name,
            title=model.db_track.name,
            suffix=suffix)

    @property
    def canonical_text(self):
        model = self.model
        return self.TRACK_FORMAT.format(
            artist=model.db_artist.name,
            album=model.db_album.name,
            title=model.name,
            suffix='')


class ScrobbleListWalker(urwid.ListWalker):

    def __init__(self, model, controller, conf):
        # I think plays are local plays, not scrobbles
        self._model = model
        self._controller = controller
        self._conf = conf

        self.focus = 0
        self.views = self._generate_plays()

        # TODO: Hook in conf.initial_scrobbles()

    @property
    def controller(self):
        return self._controller

    @property
    def model(self):
        return self._model

    def __iter__(self):
        return iter(self.views)

    def size(self):
        return len(self.model.scrobbles)

    def __len__(self):
        return len(self.views)

    def _generate_plays(self):
        if not self.model.plays:
            return []

        plays = [ScrobbleView(model, self.controller)
                 for model in self.model.plays]
        header = urwid.AttrMap(urwid.Text('Plays'), 'scrobble date')

        return [header] + plays

    def _generate_views(self, models):
        last_date = None
        #last_date = next(
        #    (v.model.date for v in self.views if isinstance(v, DayView)),
        #    None)

        for date, group in groupby(models, lambda model: model.date):
            group = list(group)
            if date != last_date:
                last_date = date
                yield DayView(DayModel(date))

            for model in group:
                yield ScrobbleView(model, self.controller)

    def _load_more(self, position):
        self.controller.load_more_scrobbles(position)

    def update_views(self):
        views = self._generate_plays()
        views.extend(self._generate_views(self.model.scrobbles))
        self.views = views

    # ListWalker Overrides
    def __getitem__(self, idx):
        return urwid.SelectableIcon(str(idx))

    def get_focus(self):
        return self._get(self.focus)

    def set_focus(self, focus):
        self.focus = focus
        self._modified()

    def get_next(self, current):
        return self._get(current + 1)

    def get_prev(self, current):
        return self._get(current - 1)

    def _get(self, pos):
        if pos < 0:
            return None, None

        if pos >= len(self.views):
            logger.debug('Position {} >= {}'.format(pos, len(self.views)))
            self._load_more(pos)

        if pos >= len(self.views):
            return None, None

        return self.views[pos], pos


class ScrobbleListView(widget.SuggestiveListBox, View):
    __metaclass__ = urwid.signals.MetaSignals
    signals = [signals.NEXT_TRACK, signals.PREVIOUS_TRACK]

    def __init__(self, model, controller, conf):
        View.__init__(self, model)
        self._controller = controller
        self._conf = conf

        # TODO: parameters
        walker = self.create_walker()
        widget.SuggestiveListBox.__init__(self, walker)

    def create_walker(self):
        return ScrobbleListWalker(
            self.model,
            self._controller,
            self._conf)

    def update(self):
        self.body.update_views()


class ScrobbleBuffer(Buffer):

    def __init__(self, conf, async_runner):
        self.conf = conf

        self.model = ScrobbleListModel()
        self.controller = ScrobbleListController(
            self.model, conf, async_runner)
        self.view = ScrobbleListView(self.model, self.controller, conf)

        super(ScrobbleBuffer, self).__init__(self.view)

        self.update_status('Scrobbles')
        self.controller.load_more_scrobbles(conf.initial_scrobbles())

    @property
    def body(self):
        return self.contents['body'][0]

    def update(self, *args):
        self.controller.insert_new_song_played()

        # We may have dirtied up the list walker, so force a redraw by
        # invalidating the cached canvas for the body, then setting focus on it
        self.body._invalidate()
        self.set_focus('body')

    def reload(self, *args):
        self.controller.reload()

    def search(self, searcher):
        #self.scrobble_list.search(searcher)
        pass

    def next_search(self):
        #self.scrobble_list.next_search_item()
        pass
