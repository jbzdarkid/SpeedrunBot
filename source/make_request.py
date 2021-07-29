import logging
import requests

def handle_completed_request(r):
  if r.request.method == 'POST': # Strip postdata arguments from the URL since they usually contain secrets.
    url = r.url.split('?')[0]
  else:
    url = r.url
  logging.info(f'Completed {r.request.method} request to {url} with code {r.status_code}')

  if r.status_code >= 500 and r.status_code <= 599:
    raise requests.exceptions.ConnectionError('Server Unavailable')
  if r.status_code == 420 or r.status_code == 429: # Speedrun.com returns 420 because they can't count, I guess
    raise requests.exceptions.ConnectionError('Server Unavailable')
  if r.status_code >= 400 and r.status_code <= 499:
    logging.error(f'Error while talking to {url}: {r.text}')
    
  if r.status_code == 204: # 204 NO CONTENT
    return ''
  else:
    return r.json()


def make_request(method, url, *args, **kwargs):
  r = requests.request(method, url, *args, **kwargs)
  return handle_completed_request(r)


def get_json(url, params=None, headers=None):
  r = requests.get(url, params=params, headers=headers)
  return handle_completed_request(r)


def post_json(url, params=None, json=None, headers=None):
  r = requests.post(url, params=params, json=json, headers=headers)
  return handle_completed_request(r)
