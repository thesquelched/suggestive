import logging


logger = logging.getLogger('suggestive')
logger.addHandler(logging.NullHandler())


class Model(object):

    """
    Model superclass.  A model may be registered with one or more views, which
    will be updated when the model is.
    """

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

    """
    View superclass.  Views always register themselves with the model that they
    represent so that, when the model is updated, the view also updates.
    """

    def __init__(self, model):
        self._model = model
        model.register(self)

    def update(self):
        pass

    @property
    def model(self):
        return self._model


class Controller(object):

    """
    Controller superclass.  Any controller instances derived from this are
    automatically registered, so that any controller can access another with
    the 'controller_for' method.

    Note that controllers should be de facto singletons.  If you instantiate
    more than one instance of any controller, it will be registered in place of
    the existing controller.
    """

    _registry = {}

    def __init__(self, model):
        self._model = model

        # The registered name (for the purpose of using 'controller_for') is
        # the lowerclass class name without the 'Controller' suffix.  For
        # example, LibraryController -> library
        name = self.__class__.__name__
        if not name.endswith('Controller'):
            raise TypeError("Invalid controller name: {}; controller class "
                            "names must end with 'Controller'".format(name))

        controller_name = name[:-len('Controller')].lower()

        self._registry[controller_name] = self

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, newmodel):
        self._model = newmodel

    def controller_for(self, name):
        return self._registry[name.lower()]


######################################################################
# Common models
######################################################################

class TrackModel(Model):

    """
    Represents an album track with LastFM metadata.
    """

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
