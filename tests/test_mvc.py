from suggestive import mvc

import pytest


@pytest.fixture(autouse=True)
def registry(request):
    request.addfinalizer(mvc.Controller._registry.clear)


def test_model_view():
    values = []

    class View(mvc.View):
        def update(self):
            values.append(self)

    model = mvc.Model()

    view1 = View(model)
    view2 = View(model)

    assert model.views == [view1, view2]
    assert view1.model == model
    assert view2.model == model

    model.update()
    assert values == [view1, view2]


def test_controller_registration():
    class FooController(mvc.Controller):
        pass

    foo1 = FooController(None, None, None)
    assert foo1.controller_for('foo') == foo1

    foo2 = FooController(None, None, None)
    assert foo2.controller_for('foo') == foo2

    class BarController(mvc.Controller):
        pass

    bar = BarController(None, None, None)
    assert foo2.controller_for('bar') == bar
    assert foo2.controller_for('foo') == foo2
    assert bar.controller_for('bar') == bar
    assert bar.controller_for('foo') == foo2


def test_invalid_controller():
    class NotCtrl(mvc.Controller):
        pass

    pytest.raises(TypeError, NotCtrl, None, None, None)

    try:
        NotCtrl(None, None, None)
    except TypeError as ex:
        assert ex.args[0].startswith('Invalid controller name: NotCtrl'), \
            'Incorrect error thrown'
