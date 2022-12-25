import logging
import requests
from time import sleep

from . import exceptions

backoff = 1
def success():
  global backoff
  backoff = max(1, backoff // 2)
def failure():
  global backoff
  sleep(backoff)
  backoff = min(60, backoff * 2)


def make_request_internal(method, url, *args, retry=True, allow_4xx=False, **kwargs):
  logging_url = url
  if method == 'POST': # Strip postdata arguments from the URL since they usually contain secrets.
    logging_url = url.partition('?')[0]

  if get_headers := kwargs.pop('get_headers', None):
    kwargs['headers'] = get_headers()

  try:
    r = requests.request(method, url, *args, **kwargs)
    
    if retry and r.status_code == 429 and 'Retry-After' in r.headers:
      # Try again exactly once when we are told to do so due to rate limiting.
      sleep(int(r.headers['Retry-After']) * 2)
      r = requests.request(method, url, *args, **kwargs)

    if retry and get_headers and r.status_code == 401:
      # Try again with new headers when we get an UNAUTHORIZED exception.
      kwargs['headers'] = get_headers()
      sleep(5)
      r = requests.request(method, url, *args, **kwargs)

  except requests.exceptions.RequestException as e:
    failure()
    raise exceptions.NetworkError(f'{method} {logging_url} failed: {e}')

  if 200 <= r.status_code and r.status_code <= 399:
    success()
    logging.info(f'Completed {method} request to {logging_url} with code {r.status_code}')
    return r
  elif allow_4xx and 400 <= r.status_code and r.status_code <= 499:
    failure() # Even if the caller allows client errors, it's still a failure and we should take care not to throttle.
    logging.info(f'Completed {method} request to {logging_url} with code {r.status_code}')
    return r
  else:
    failure()
    raise exceptions.NetworkError(f'{method} {logging_url} returned {r.status_code} {r.reason.upper()}: {r.text}')


def make_request(method, url, *args, retry=True, **kwargs):
  r = make_request_internal(method, url, *args, retry=retry, **kwargs)

  if r.status_code == 204: # 204 NO CONTENT
    return ''
  return r.json()


def make_head_request(url, *args, retry=True, **kwargs):
  kwargs.setdefault('allow_redirects', False)
  r = make_request_internal('HEAD', url, *args, retry=retry, **kwargs)
  return (r.status_code, r.headers)
