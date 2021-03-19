import requests

def get_json(url, params=None, headers=None):
  log_string = f'Making a network call to {url}'
  if params:
    log_string += '?' + '&'.join(f'{key}={params[key]}' for key in params)
  print(log_string)
  return requests.get(url, params=params, headers=headers).json()
