import logging
import requests

def get_json(url, params=None, headers=None):
  r = requests.get(url, params=params, headers=headers)
  logging.info(f'Completed GET request to {r.url} with code {r.status_code}')
  if r.status_code >= 500 and r.status_code <= 599:
    raise requests.exceptions.ConnectionError('Server Unavailable')
  return r.json()

def post_json(url, params=None, headers=None):
  r = requests.post(url, params=params, headers=headers)
  if r.status_code >= 500 and r.status_code <= 599:
    raise requests.exceptions.ConnectionError('Server Unavailable')
  # NB: Strip postdata arguments from the URL since they usually contain secrets.
  logging.info(f'Completed POST request to {r.url.split("?")[0]} with code {r.status_code}')
  return r.json()
