import requests
import json
from pathlib import Path

with (Path(__file__).parent / 'token2.txt').open() as f:
  token = f.read().strip()
client_id = 'xxl8mgqo1ep3dvpq9wlilotwwwd8o3'

params = {
  'grant_type': 'client_credentials',
  'client_id': client_id,
  'client_secret': token,
  'scope': 'analytics:read:games user:read:broadcast channel:manage:broadcast',
}
j = requests.post('https://id.twitch.tv/oauth2/token', params=params).json()
headers = {
  'client-id': 'xxl8mgqo1ep3dvpq9wlilotwwwd8o3',
  'Authorization': 'Bearer ' + j['access_token'],
}

class Cache(object):
  def __init__(self, name):
    self.path = Path(__file__).parent / name
    if not self.path.exists():
      self.cache = {}
    else:
      self.cache = json.load(self.path.open('r'))

  def get(self, name):
    return self.cache.get(name, None)

  def set(self, name, value):
    self.cache[name] = value
    json.dump(self.cache, self.path.open('w'))

twitch_cache    = Cache('twitch_cache.json')
twitch_game_ids = Cache('twitch_game_ids.json')
src_game_ids    = Cache('src_game_ids.json')
games_cache     = Cache('games_cache.json')


def get_streamers_for_game(twitch_game_id):
  j = requests.get('https://api.twitch.tv/helix/streams', params={'game_id': twitch_game_id}, headers=headers).json()
  return [stream['user_name'] for stream in j['data'] if stream['type'] == 'live']


def get_src_id(twitch_id):
  if src_id := twitch_cache.get(twitch_username):
    return src_id

  j = requests.get(f'https://www.speedrun.com/api/v1/users?twitch={twitch_username}').json()
  if len(j['data']) == 0:
    return None
  src_id = j['data'][0]['id']
  twitch_cache.set(twitch_username, src_id)


def runner_runs_game(src_id, src_game_id):
  if games := games_cache.get(src_id):
    if src_game_id in games:
      return True

  pbs = r.get(f'https://www.speedrun.com/api/v1/users/{runner}/personal-bests').json()
  games = {pb['data']['run']['game'] for pb in pbs}
  games_cache.set(src_id, games)
  return src_game_id in games


def get_twich_game_id(name):
  if twich_game_id := twitch_game_ids.get(name):
    return twich_game_id

  j = requests.get('https://api.twitch.tv/helix/games', params={'name': name}, headers=headers).json()
  twitch_game_id = j['data'][0]['id']
  twitch_game_ids.set(name, twitch_game_id)
  return twitch_game_id


def get_src_game_id(name):
  if src_game_id := src_game_ids.get(name):
    return src_game_id

  j = requests.get('https://www.speedrun.com/api/v1/games', params={'name': name}).json()
  src_game_id = j['data'][0]['id']
  src_game_ids.set(name, src_game_id)
  return src_game_id


if __name__ == '__main__':
  twitch_game_id = get_twich_game_id('The Witness')
  src_game_id = get_src_game_id('The Witness')
  streams = get_streamers_for_game(twitch_game_id)
  for twitch_id in streams:
    src_id = get_src_id(twitch_id)
    if src_id is None:
      continue # Not actually a speedrunner

    if runner_runs_game(src_id, src_game_id):
      print(runner)
