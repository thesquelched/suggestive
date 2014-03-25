from suggestive.threads import PriorityEventQueue

from unittest import TestCase


class TestQueue(TestCase):

    def test_unique_different_priorities(self):
        queue = PriorityEventQueue()
        queue.put((0, 'player'))
        queue.put((1, 'player'))

        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.get(), (0, 'player'))
        self.assertTrue(queue.empty())

    def test_unique_same_priority(self):
        queue = PriorityEventQueue()
        queue.put((0, 'player'))
        queue.put((0, 'player'))

        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.get(), (0, 'player'))
        self.assertTrue(queue.empty())

    def test_nonunique(self):
        queue = PriorityEventQueue()
        queue.put((1, 'myevent'))
        queue.put((0, 'myevent'))

        self.assertEqual(queue.qsize(), 2)
        self.assertEqual(queue.get(), (0, 'myevent'))
        self.assertEqual(queue.get(), (1, 'myevent'))
        self.assertTrue(queue.empty())
