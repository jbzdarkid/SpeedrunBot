import logging
import requests

def on_request_complete(r):
  if r.request.method == 'POST': # Strip postdata arguments from the URL since they usually contain secrets.
    url = r.url.split('?')[0]
  else:
    url = r.url
  logging.info(f'Completed {r.request.method} request to {url} with code {r.status_code}')

  if r.status_code >= 500 and r.status_code <= 599:
    raise requests.exceptions.ConnectionError('Server Unavailable')
  if r.status_code == 420 or r.status_code == 429: # Speedrun.com returns 420 because they can't count, I guess
    raise requests.exceptions.ConnectionError('Server Unavailable')

def get_json(url, params=None, headers=None):
  r = requests.get(url, params=params, headers=headers)
  on_request_complete(r)
  return r.json()

def post_json(url, params=None, headers=None):
  r = requests.post(url, params=params, headers=headers)
  on_request_complete(r)
  return r.json()
