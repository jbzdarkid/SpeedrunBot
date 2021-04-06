import requests

def get_json(url, params=None, headers=None):
  r = requests.get(url, params=params, headers=headers)
  print(f'Completed GET request to {r.url} with code {r.status_code}')
  return r.json()

def post_json(url, params=None, headers=None):
  r = requests.post(url, params=params, headers=headers)
  # NB: Strip postdata arguments from the URL since they usually contain secrets.
  print(f'Completed POST request to {r.url.split("?")[0]} with code {r.status_code}')
  return r.json()
