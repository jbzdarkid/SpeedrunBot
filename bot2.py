import requests
import json
from pathlib import Path
from sys import argv

with (Path(__file__).parent / 'twitch_token.txt').open() as f:
  token = f.read().strip()
with (Path(__file__).parent / 'twitch_client.txt').open() as f:
  client_id = f.read().strip()

def debug(*args, **kwargs):
  pass

r = requests.post('https://id.twitch.tv/oauth2/token', params={
  'grant_type': 'client_credentials',
  'client_id': client_id,
  'client_secret': token,
  'scope': 'analytics:read:games user:read:broadcast channel:manage:broadcast',
})
headers = {
  'client-id': client_id,
  'Authorization': 'Bearer ' + r.json()['access_token'],
}

class Cache(object):
  def __init__(self, name):
    self.path = Path(__file__).parent / name
    if not self.path.exists():
      self.cache = {}
    else:
      self.cache = json.load(self.path.open('r'))
      debug(f'Loaded cache for {self.path.name}')

  def get(self, name):
    return self.cache.get(name, None)

  def set(self, name, value):
    self.cache[name] = value
    json.dump(self.cache, self.path.open('w'))
    debug(f'Saved cache for {self.path.name}')

twitch_cache    = Cache('twitch_cache.json')
twitch_game_ids = Cache('twitch_game_ids.json')
src_game_ids    = Cache('src_game_ids.json')
games_cache     = Cache('games_cache.json')
debug('Loaded all caches')

def get_streamers_for_game(twitch_game_id):
  j = requests.get('https://api.twitch.tv/helix/streams', params={'game_id': twitch_game_id}, headers=headers).json()
  return [stream['user_name'] for stream in j['data'] if stream['type'] == 'live']


def get_src_id(twitch_username):
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

  pbs = requests.get(f'https://www.speedrun.com/api/v1/users/{src_id}/personal-bests').json()
  games = {pb['run']['game'] for pb in pbs['data']}
  games_cache.set(src_id, list(games))
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


def get_speedrunners_for_game(name):
  twitch_game_id = get_twich_game_id(name)
  src_game_id = get_src_game_id(name)
  debug(f'Found game IDs for game {name}.\nTwitch: {twitch_game_id}\nSRC: {src_game_id}')
  streams = get_streamers_for_game(twitch_game_id)
  debug(f'There are currently {len(streams)} streamers of {name}')
  for twitch_username in streams:
    src_id = get_src_id(twitch_username)
    if src_id is None:
      debug(f'Streamer {twitch_username} is not a speedrunner')
      continue # Not actually a speedrunner

    if runner_runs_game(src_id, src_game_id):
      debug(f'Streamer {twitch_username} actually runs {name}')
      yield (src_id, twitch_username)
    else:
      debug(f'Streamer {twitch_username} is a speedrunner, but not of {name}')

if __name__ == '__main__':
  if '--debug' in argv:
    def debug(*args, **kwargs):
      print(*args, **kwargs)

  print(list(get_speedrunners_for_game('Grand Theft Auto IV')))
