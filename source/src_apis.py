from datetime import datetime
import requests
import database

ONE_HOUR = (3600)
ONE_DAY  = (3600 * 24)
ONE_WEEK = (3600 * 24 * 7)

### Functions which talk to the Speedrun.com APIs
def get_src_id(twitch_username):
  if user := database.get_user(twitch_username):
    if user['src_id']:
      # Streamer found, is a known speedrunner.
      return user['src_id']
    # Streamer is found, but not a speedrunner.
    if datetime.now().timestamp() < user['fetch_time'] + ONE_WEEK:
      # Last check was <1 week ago, return cached.
      return user['src_id']

  # Make a network call to determine if the streamer is a speedrunner.
  j = requests.get('https://www.speedrun.com/api/v1/users' params={'twitch', twitch_username}).json()
  if len(j['data']) == 0:
    return None
  src_id = j['data'][0]['id']
  database.add_user(twitch_username, src_id)


def track_game(game_name, discord_channel):
  if game := database.get_game(game_name):
    return

  j = requests.get('https://www.speedrun.com/api/v1/games', params={'name': game_name}).json()
  src_game_id = j['data'][0]['id']
  database.add_game(game_name, src_game_id, discord_channel)
  # https://discord.com/oauth2/authorize?scope=bot&permissions=2048&client_id=683472204280889511


def runner_runs_game(src_id, src_game_id):
  if database.has_personal_best(src_id, src_game_id):
    return True

  # ... last fetch time?

  pbs = requests.get(f'https://www.speedrun.com/api/v1/users/{src_id}/personal-bests').json()
  games = {pb['run']['game'] for pb in pbs['data']}
  games_cache.set(src_id, list(games))
  # fix me
  return src_game_id in games

