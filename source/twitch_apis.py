import logging
from pathlib import Path
from datetime import datetime   

from .make_request import make_request, make_head_request
from . import exceptions

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
def get_live_streams(*, game_ids=None, user_logins=None):
  params = {'first': 100}
  if game_ids:
    if len(game_ids) == 0 or len(game_ids) > 100:
      raise exceptions.CommandError(f'Invalid number of game_ids: {len(game_ids)}')
    if user_logins:
      raise exceptions.CommandError(f'Cannot combine both game_ids and user_logins')

    params['game_id'] = game_ids
  elif user_logins:
    if len(user_logins) == 0 or len(user_logins) > 100:
      raise exceptions.CommandError(f'Invalid number of user_logins: {len(user_logins)}')

    params['user_login'] = user_logins

  streams = []
  while 1:
    j = make_request('GET', f'{api}/streams', params=params, get_headers=get_headers)
    logging.info(j)
    if 'data' not in j:
      break
    streams += [stream for stream in j['data'] if stream['type'] == 'live']
    if len(j['data']) == 0:
      break
    if 'cursor' not in j['pagination']:
      break
    params['after'] = j['pagination']['cursor']
  return streams


def get_game_id(game_name):
  j = make_request('GET', f'{api}/games', params={'name': game_name}, get_headers=get_headers)
  if len(j['data']) == 0:
    raise exceptions.CommandError(f'Could not find game `{game_name}` on Twitch')
  return j['data'][0]['id']


def get_user_id(username):
  j = make_request('GET', f'{api}/users', params={'login': username}, get_headers=get_headers)
  if len(j['data']) == 0:
    raise exceptions.CommandError(f'Could not find user `{username}` on Twitch')
  return j['data'][0]['id']


def get_preview_metadata(preview_url):
  status_code, headers = make_head_request(preview_url)
  expires = datetime.strptime(headers['expires'], '%a, %d %b %Y %H:%M:%S %Z')

  return {
    'redirect': status_code >= 300 and status_code < 400,
    'expires': expires.timestamp(),
  }
