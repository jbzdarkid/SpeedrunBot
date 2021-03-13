from pathlib import Path
import requests

with Path(__file__).with_name('twitch_token.txt').open() as f:
  token = f.read().strip()
with Path(__file__).with_name('twitch_client.txt').open() as f:
  client_id = f.read().strip()

r = requests.post('https://id.twitch.tv/oauth2/token', params={
  'grant_type': 'client_credentials',
  'client_id': client_id,
  'client_secret': token,
  # analytics:read:games is for enumerating streams
  # user:read:broadcast is for reading stream titles
  # channel:manage:broadcast is for ...?
  'scope': 'analytics:read:games user:read:broadcast channel:manage:broadcast',
})
access_token = r.json()['access_token']
headers = {'client-id': client_id, 'Authorization': 'Bearer ' + access_token}

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


def get_game_id(game_name):
  j = requests.get('https://api.twitch.tv/helix/games', params={'name': game_name}, headers=headers).json()
  return j['data'][0]['id']