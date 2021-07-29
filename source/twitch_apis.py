import logging
from pathlib import Path

from .make_request import make_request

api = 'https://api.twitch.tv/helix'

cached_headers = None
def get_headers():
  global cached_headers
  if not cached_headers:
    with Path(__file__).with_name('twitch_token.txt').open() as f:
      token = f.read().strip()
    with Path(__file__).with_name('twitch_client.txt').open() as f:
      client_id = f.read().strip()

    j = make_request('POST', 'https://id.twitch.tv/oauth2/token', params={
      'grant_type': 'client_credentials',
      'client_id': client_id,
      'client_secret': token,
    })
    cached_headers = {
      'client-id': client_id,
      'Authorization': 'Bearer ' + j['access_token']
    }
  return cached_headers


# game_ids is an array of twitch game ids. (max: 100)
def get_live_game_streams2(game_ids):
  if len(game_ids) == 0 or len(game_ids) > 100:
    raise ValueError(f'Invalid number of game IDs: {len(game_ids)}')

  streams = []
  params = {'game_id': game_ids, 'first': 100}
  while 1:
    j = make_request('GET', f'{api}/streams', params=params, headers=get_headers())
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
  j = make_request('GET', f'{api}/games', params={'name': game_name}, headers=get_headers())
  if len(j['data']) == 0:
    raise ValueError(f'Could not find game {game_name} on Twitch')
  return j['data'][0]['id']


def get_user_id(username):
  j = make_request('GET', f'{api}/users', params={'login': username}, headers=get_headers())
  if len(j['data']) == 0:
    raise ValueError(f'Could not find user {username} on Twitch')
  return j['data'][0]['id']
