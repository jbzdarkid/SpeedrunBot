import requests

def get_json(url, params=None, headers=None):
  r = requests.get(url, params=params, headers=headers)
  print(f'Completed network request to {r.url} with code {r.status_code}')
  return r.json()
