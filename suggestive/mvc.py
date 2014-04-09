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

    def update(self):
        pass

    @property
    def model(self):
        return self._model
