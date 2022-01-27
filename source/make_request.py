import logging
import requests
from time import sleep

from . import exceptions

def make_request_unsafe(method, url, *args, json=True, retry=True, **kwargs):
  r = requests.request(method, url, *args, **kwargs)
  logging.info(r.status_code, r.text)
  if retry and r.status_code == 429 and 'Retry-After' in r.headers:
    # Try again exactly once when we are told to do so.
    sleep(int(r.headers['Retry-After']))
    r = requests.request(method, url, *args, **kwargs)

  if method == 'POST': # Strip postdata arguments from the URL since they usually contain secrets.
    url = url.partition('?')[0]
  logging.info(f'Completed {r.request.method} request to {url} with code {r.status_code}')

  r.raise_for_status() # Raise an exception for any 400 or 500 class response

  if r.status_code == 204: # 204 NO CONTENT
    return ''
  elif json:
    return r.json()
  else:
    return r.text


backoff = 1
def make_request(method, url, *args, json=True, retry=True, **kwargs):
  global backoff

  try:
    response = make_request_unsafe(method, url, *args, json=json, retry=retry, **kwargs)
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
