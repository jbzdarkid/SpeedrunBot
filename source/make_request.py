import logging
import requests
from time import sleep

from . import exceptions

def make_request_unsafe(method, url, *args, **kwargs):
  r = requests.request(method, url, *args, **kwargs)
  r.raise_for_status() # Raise an exception for any 400 or 500 class response

  if r.request.method == 'POST': # Strip postdata arguments from the URL since they usually contain secrets.
    url = url.split('?')[0]
  logging.info(f'Completed {r.request.method} request to {url} with code {r.status_code}')

  if r.status_code == 204: # 204 NO CONTENT
    return ''
  else:
    return r.json()


backoff = 1
def make_request(method, url, *args, **kwargs):
  global backoff

  try:
    response = make_requests_unsafe(method, url, *args, **kwargs)
    backoff = max(1, backoff // 2)
    return response

  except requests.exceptions.RequestException as e:
    sleep(backoff)
    backoff = min(60, backoff * 2)

    r = e.response
    if r:
      logging.error(f'Error response text: {r.text}')
      raise exceptions.NetworkError(f'{r.status_code} {r.reason.upper()}')
    else:
      raise exceptions.NetworkError(f'{e.request.method.upper()} "{e.request.url}" failed')
