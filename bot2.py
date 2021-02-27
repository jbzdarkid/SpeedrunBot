import discord
import json
import requests
from pathlib import Path
from sys import argv

# TODO: Decide on throttling limits for each API call.
#  - "get streams" is once/minute
#  - get_src_id is once/week? People don't *become* speedrunners very often.
#  - runner_runs_game is once/day. If a speedrunner is streaming a game, they submit their first run pretty quick.
# TODO: Real database? JSON files are gonna get large otherwise. Maybe a local DB file would be good for this, to prepare for future webhosting.
# TODO: AWS hosting? Maybe.

with (Path(__file__).parent / 'twitch_token.txt').open() as f:
  token = f.read().strip()
with (Path(__file__).parent / 'twitch_client.txt').open() as f:
  client_id = f.read().strip()

def debug(*args, **kwargs):
  if '--debug' in argv:
    print(*args, **kwargs)

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

def get_live_game_streams(twitch_game_id):
  streams = []
  params = {'game_id': twitch_game_id, 'first': 100}
  while 1:
    j = requests.get('https://api.twitch.tv/helix/streams', params=params, headers=headers).json()
    if 'data' not in j:
      break
    streams += [stream for stream in j['data'] if stream['type'] == 'live']
    if len(j['data']) < 100:
      break
    if 'cursor' not in j['pagination']:
      break
    params['after'] = j['pagination']['cursor']
  return streams


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

  streams = get_live_game_streams(twitch_game_id)
  debug(f'There are currently {len(streams)} live streams of {name}')
  for stream in streams:
    twitch_username = stream['user_name']
    src_id = get_src_id(twitch_username)
    if src_id is None:
      debug(f'Streamer {twitch_username} is not a speedrunner')
      continue # Not actually a speedrunner

    if not runner_runs_game(src_id, src_game_id):
      debug(f'Streamer {twitch_username} is a speedrunner, but not of {name}')
    else:
      debug(f'Streamer {twitch_username} runs {name}')
      yield {
        'preview': stream['thumbnail_url'].format(width=320, height=180),
        'url': 'https://www.twitch.tv/' + twitch_username,
        'name': discord.utils.escape_markdown(twitch_username),
        'title': discord.utils.escape_markdown(stream['title']),
      }

if __name__ == '__main__':
  print(list(get_speedrunners_for_game('Super Mario Odyssey')))
