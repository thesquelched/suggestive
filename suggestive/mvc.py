import logging


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


class Model(object):

    def __init__(self):
        self._views = []

    @property
    def views(self):
        return self._views

    def register(self, view):
        self._views.append(view)

    def update(self):
        logger.debug('{} updated'.format(repr(self)))
        for view in self.views:
            view.update()


class View(object):

    def __init__(self, model):
        self._model = model
        model.register(self)

    def update(self):
        pass

    @property
    def model(self):
        return self._model


class Controller(object):

    _registry = {}

    def __init__(self, model):
        self._model = model
        self._registry[self.__class__.__name__] = self

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, newmodel):
        self._model = newmodel

    def controller_for(self, name):
        return self._registry[name]


######################################################################
# Common models
######################################################################

class TrackModel(Model):

    def __init__(self, db_track, number):
        super(TrackModel, self).__init__()
        self._db_track = db_track
        self._number = number

    @property
    def db_track(self):
        return self._db_track

    @property
    def db_album(self):
        return self._db_track.album

    @property
    def db_artist(self):
        return self._db_track.artist

    @property
    def name(self):
        return self._db_track.name

    @property
    def loved(self):
        info = self._db_track.lastfm_info
        return info and info.loved

    @property
    def banned(self):
        info = self._db_track.lastfm_info
        return info and info.banned

    @property
    def number(self):
        return self._number
