import requests
from datetime import datetime
from . import database

ONE_HOUR = (3600)
ONE_DAY  = (3600 * 24)
ONE_WEEK = (3600 * 24 * 7)

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
  j = requests.get('https://www.speedrun.com/api/v1/users', params={'twitch': twitch_username}).json()
  if len(j['data']) == 0:
    return None
  src_id = j['data'][0]['id']
  if not user:
    # When initially adding a user, we set the fetch_time to 0 so that further lookups will fetch their PBs.
    database.add_user(twitch_username, src_id, 0)
  return src_id


def runner_runs_game(src_id, src_game_id):
  if database.has_personal_best(src_id, src_game_id):
    return True

  if user := database.get_user_by_src(src_id):
    if datetime.now().timestamp() < user['fetch_time'] + ONE_DAY:
      # Last check was <1 day ago, don't fetch again
      return False

  pbs = requests.get(f'https://www.speedrun.com/api/v1/users/{src_id}/personal-bests').json()
  games = {pb['run']['game'] for pb in pbs['data']}
  if src_game_id in games:
    database.add_personal_best(src_id, src_game_id)
    return True
  return False


def get_game_id(game_name):
  j = requests.get('https://www.speedrun.com/api/v1/games', params={'name': game_name}).json()
  return j['data'][0]['id']


def search_src_user(username):
  j = requests.get('https://www.speedrun.com/api/v1/users', params={'name': username}).json()
  if len(j['data']) == 0:
    return []

  return [(user["names"]["international"], user["id"]) for user in j['data']]
