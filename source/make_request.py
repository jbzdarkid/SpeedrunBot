import logging
import requests
from time import sleep

from . import exceptions

backoff = 1

def handle_completed_request(r):
  if r.request.method == 'POST': # Strip postdata arguments from the URL since they usually contain secrets.
    url = r.url.split('?')[0]
  else:
    url = r.url
  logging.info(f'Completed {r.request.method} request to {url} with code {r.status_code}')

  global backoff
  # Probably a bit overzealous but we'll see if it's every actually a problem.
  if (r.status_code >= 400 and r.status_code <= 599):
    sleep(backoff)
    backoff *= 2
    logging.info(f'Response: {r.text}')
    raise exceptions.NetworkError(f'{r.status_code} {r.reason.upper()}')

  if backoff > 1:
    backoff //= 2

  if r.status_code >= 400 and r.status_code <= 499:
    logging.error(f'Client error while talking to {url}: {r.text}')

  if r.status_code == 204: # 204 NO CONTENT
    return ''
  else:
    return r.json()


def make_request(method, url, *args, **kwargs):
  r = requests.request(method, url, *args, **kwargs)
  return handle_completed_request(r)
