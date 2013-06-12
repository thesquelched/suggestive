import requests
import json
import logging

APIKEY = 'd9d0efb24aec53426d0f8d144c74caa7'

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

class LastfmError(Exception):
  pass

class LastFM(object):
  """
  Helper class for communicating with Last.FM servers
  """

  URL = 'http://ws.audioscrobbler.com/2.0/'

  def __init__(self, api_key):
    self.key = api_key

  def query_all(self, method, *keys, **kwArgs):
    resp = self.query(method, **kwArgs)

    data = resp
    for key in keys:
      if key in data:
        data = data[key]
      else:
        break

    attrs = data.get('@attr', {})
    n_pages = int(attrs.get('totalPages', 1))

    logger.debug('Query pages: {}'.format(n_pages))

    # Start to yield responses
    yield resp

    for pageno in range(1, n_pages):
      kwArgs.update({'page': pageno})
      yield self.query(method, **kwArgs)

  def query(self, method, **kwArgs):
    """
    Send a Last.FM query for the given method, returing the parsed JSON
    response
    """
    params = dict(
      method = method,
      api_key = self.key,
      format = 'json',
    )
    params.update(kwArgs)

    try:
      resp = requests.post(self.URL, params = params)
      if not resp.ok:
        raise ValueError('Response was invalid')
      return json.loads(resp.text)
    except (ValueError, requests.exceptions.RequestException) as error:
      logger.error('Query resulted in an error: {}', error)
      raise LastfmError("Query '{}' failed".format(method))

  def scrobbles(self, user, last_updated = None):
    args = {
      'limit': 200,
      'user': user,
      'extended': 1
    }

    if last_updated:
      args['from'] = last_updated

    for resp in self.query_all('user.getRecentTracks', 'recenttracks', **args):
      if 'recenttracks' not in resp:
        continue

      recent = resp['recenttracks']
      if 'track' not in recent or not isinstance(recent['track'], list):
        continue

      for track in recent['track']:
        yield track
