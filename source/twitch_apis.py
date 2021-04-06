import requests
from pathlib import Path
from .make_request import get_json, post_json

cached_headers = None
def get_headers():
  global cached_headers
  if not cached_headers:
    with Path(__file__).with_name('twitch_token.txt').open() as f:
      token = f.read().strip()
    with Path(__file__).with_name('twitch_client.txt').open() as f:
      client_id = f.read().strip()

    j = post_json('https://id.twitch.tv/oauth2/token', params={
      'grant_type': 'client_credentials',
      'client_id': client_id,
      'client_secret': token,
      # analytics:read:games is for enumerating streams
      # user:read:broadcast is for reading stream titles
      # channel:manage:broadcast is for ...?
      'scope': 'analytics:read:games user:read:broadcast channel:manage:broadcast',
    })
    access_token = j['access_token']
    cached_headers = {'client-id': client_id, 'Authorization': 'Bearer ' + access_token}
  return cached_headers


# game_ids is an array of twitch game ids. (max: 100)
def get_live_game_streams2(game_ids):
  if len(game_ids) == 0 or len(game_ids) > 100:
    raise ValueError(f'Invalid number of game IDs: {len(game_ids)}')

  streams = []
  params = {'game_id': game_ids, 'first': 100}
  while 1:
    j = get_json('https://api.twitch.tv/helix/streams', params=params, headers=get_headers())
    if 'data' not in j:
      break
    streams += [stream for stream in j['data'] if stream['type'] == 'live']
    if len(j['data']) < 100:
      break
    if 'cursor' not in j['pagination']:
      break
    params['after'] = j['pagination']['cursor']
  return streams


def get_game_id(game_name):
  j = get_json('https://api.twitch.tv/helix/games', params={'name': game_name}, headers=get_headers())
  if len(j['data']) == 0:
    raise ValueError(f'Could not find game {game_name} on Twitch')
  return j['data'][0]['id']


def get_user_id(username):
  j = get_json('https://api.twitch.tv/helix/users', params={'login': username}, headers=get_headers())
  if len(j['data']) == 0:
    raise ValueError(f'Could not find user {username} on Twitch')
  return j['data'][0]['id']
