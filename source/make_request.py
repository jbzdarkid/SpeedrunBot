import requests
import logging

logger = logging.getLogger(__name__)

def get_json(url, params=None, headers=None):
  r = requests.get(url, params=params, headers=headers)
  logger.info(f'Completed GET request to {r.url} with code {r.status_code}')
  if r.status_code >= 500 and r.status_code <= 599:
    raise ValueError('Server Unavailable')
  return r.json()

def post_json(url, params=None, headers=None):
  r = requests.post(url, params=params, headers=headers)
  # NB: Strip postdata arguments from the URL since they usually contain secrets.
  logger.info(f'Completed POST request to {r.url.split("?")[0]} with code {r.status_code}')
  return r.json()
