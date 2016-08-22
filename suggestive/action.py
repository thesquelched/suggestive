from suggestive import mstat


def lastfm_love_track(conf, track, loved):
    """Blocking; call only with `run_in_executor`"""
    lastfm = mstat.initialize_lastfm(conf)
    mstat.lastfm_love(lastfm, track, loved)
