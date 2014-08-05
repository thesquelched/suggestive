from suggestive import mvc
from unittest import TestCase


class TestMVC(TestCase):

    def tearDown(self):
        mvc.Controller._registry = {}

    def test_model_view(self):
        values = []

        class View(mvc.View):
            def update(self):
                values.append(self)

        model = mvc.Model()

        view1 = View(model)
        view2 = View(model)

        self.assertEqual(model.views, [view1, view2])
        self.assertEqual(view1.model, model)
        self.assertEqual(view2.model, model)

        model.update()
        self.assertEqual(values, [view1, view2])

    def test_controller_registration(self):
        class FooController(mvc.Controller):
            pass

        foo1 = FooController(None, None, None)
        self.assertEqual(foo1.controller_for('foo'), foo1)

        foo2 = FooController(None, None, None)
        self.assertEqual(foo2.controller_for('foo'), foo2)

        class BarController(mvc.Controller):
            pass

        bar = BarController(None, None, None)
        self.assertEqual(foo2.controller_for('bar'), bar)
        self.assertEqual(foo2.controller_for('foo'), foo2)
        self.assertEqual(bar.controller_for('bar'), bar)
        self.assertEqual(bar.controller_for('foo'), foo2)

    def test_invalid_controller(self):
        class NotCtrl(mvc.Controller):
            pass

        self.assertRaises(TypeError, NotCtrl, None, None, None)

        try:
            NotCtrl(None, None, None)
        except TypeError as ex:
            self.assertTrue(
                ex.args[0].startswith('Invalid controller name: NotCtrl'))
