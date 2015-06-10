from suggestive.threads import PriorityEventQueue


def test_unique_different_priorities():
    queue = PriorityEventQueue()
    queue.put((0, 'player'))
    queue.put((1, 'player'))

    assert queue.qsize() == 1
    assert queue.get() == (0, 'player')
    assert queue.empty(), 'Queue is not empty'


def test_unique_same_priority():
    queue = PriorityEventQueue()
    queue.put((0, 'player'))
    queue.put((0, 'player'))

    assert queue.qsize() == 1
    assert queue.get() == (0, 'player')
    assert queue.empty(), 'Queue is not empty'


def test_nonunique():
    queue = PriorityEventQueue()
    queue.put((1, 'myevent'))
    queue.put((0, 'myevent'))

    assert queue.qsize() == 2
    assert queue.get() == (0, 'myevent')
    assert queue.get() == (1, 'myevent')
    assert queue.empty(), 'Queue is not empty'
