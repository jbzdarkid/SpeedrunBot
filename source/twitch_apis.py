from pathlib import Path
import requests

with (Path(__file__).parent / 'twitch_token.txt').open() as f:
  token = f.read().strip()
with (Path(__file__).parent / 'twitch_client.txt').open() as f:
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

def get_live_game_streams(twitch_game_id):
  streams = []
  params = {'game_id': twitch_game_id, 'first': 100}
  headers = {'client-id': client_id, 'Authorization': 'Bearer ' + access_token}
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


# FIXME
def get_twich_game_id(game_name):
  if twich_game_id := twitch_game_ids.get(game_name):
    return twich_game_id

  j = requests.get('https://api.twitch.tv/helix/games', params={'name': game_name}, headers=headers).json()
  twitch_game_id = j['data'][0]['id']
  twitch_game_ids.set(game_name, twitch_game_id)
  return twitch_game_id


# FIXME: This should live in bot.py
def get_speedrunners_for_game(game_name):
  game = database.get_game(game_name)
  debug(f'Found game IDs for game {name}.\nTwitch: {twitch_game_id}\nSRC: {src_game_id}')

  streams = get_live_game_streams(twitch_game_id)
  debug(f'There are currently {len(streams)} live streams of {game_name}')
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
