import requests

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
