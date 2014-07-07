import suggestive.mstat as mstat

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
    the 'controller_for' method.  The registered name is the lowercase class
    name without the 'Controller' suffix.  For example, 'LibraryController'
    registers as 'library'.  If the class name does not end with 'Controller',
    a TypeError will be raised.

    Note that controllers should be de facto singletons.  If you instantiate
    more than one instance of any controller, it will be registered in place of
    the existing controller.
    """

    _registry = {}

    def __init__(self, model, conf, async_runner):
        self._model = model
        self._conf = conf
        self._async_runner = async_runner

        # The registered name (for the purpose of using 'controller_for') is
        # the lowercase class name without the 'Controller' suffix.  For
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

    @property
    def conf(self):
        return self._conf

    @property
    def async_runner(self):
        return self._async_runner

    def session(self, **kwArgs):
        return mstat.session_scope(self.conf, **kwArgs)

    def controller_for(self, name):
        return self._registry[name.lower()]

    def run_async(self, func):
        self._async_runner.run_async(func)

    def asynchronous(func):
        """
        Make the decorated function asynchronous
        """
        def wrapper(self, *args, **kwArgs):
            self.run_async(lambda: func(self, *args, **kwArgs))
        return wrapper


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

    @db_track.setter
    def db_track(self, track):
        self._db_track = track
        self.update()

    @property
    def db_album(self):
        return self.db_track.album

    @property
    def db_artist(self):
        return self.db_track.artist

    @property
    def name(self):
        return self.db_track.name

    @property
    def loved(self):
        info = self.db_track.lastfm_info
        return info and info.loved

    @property
    def banned(self):
        info = self.db_track.lastfm_info
        return info and info.banned

    @property
    def number(self):
        return self._number
