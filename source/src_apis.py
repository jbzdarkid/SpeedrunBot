from datetime import datetime
from . import database
from .make_request import get_json

ONE_HOUR  = (3600)
ONE_DAY   = (3600 * 24)
ONE_WEEK  = (3600 * 24 * 7)
ONE_MONTH = (3600 * 24 * 7 * 30)

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
  j = get_json('https://www.speedrun.com/api/v1/users', params={'twitch': twitch_username})
  if len(j['data']) == 0:
    database.add_user(twitch_username, None)
    return None
  src_id = j['data'][0]['id']
  if not user:
    # When initially adding a user, we set the fetch_time to 0 so that further lookups will fetch their PBs.
    database.add_user(twitch_username, src_id, 0)
  return src_id


def runner_runs_game(twitch_username, src_id, src_game_id):
  if database.has_personal_best(src_id, src_game_id):
    return True

  if user := database.get_user(twitch_username):
    if datetime.now().timestamp() < user['fetch_time'] + ONE_DAY:
      # Last check was <1 day ago, don't fetch again
      return False

  database.update_user_fetch_time(twitch_username)
  j = get_json(f'https://www.speedrun.com/api/v1/users/{src_id}/personal-bests', params={'game': src_game_id})
  if len(j['data']) == 0:
    return False

  database.add_personal_best(src_id, src_game_id)
  return True


def get_game_id(game_name):
  j = get_json('https://www.speedrun.com/api/v1/games', params={'name': game_name})
  if len(j['data']) == 0:
    raise ValueError(f'Could not find game {game_name} on Speedrun.com')

  if len(j['data']) == 1:
    return j['data'][0]['id']

  possible_matches = []
  for game in j['data']:
    possible_match = game['names']['twitch']
    if possible_match == game_name:
      return game['id']
    possible_matches.append(possible_match)

  suggestions = ', '.join(possible_matches[:10]) # Only show a max of 10 matches, for brevity's sake
  raise ValueError(f'Found {len(possible_matches)} possible matches for game {game_name} on Speedrun.com -- Try one of these options:\n' + suggestions)


def search_src_user(username):
  j = get_json('https://www.speedrun.com/api/v1/users', params={'name': username})
  if len(j['data']) == 0:
    raise ValueError(f'Could not find user {username} on Speedrun.com')

  if len(j['data']) == 1:
    return j['data'][0]['id']

  possible_matches = []
  for user in j['data']:
    possible_match = user['names']['international']
    if possible_match == username:
      return user['id']
    possible_matches.append(possible_match)

  suggestions = ', '.join(possible_matches[:10]) # Only show a max of 10 matches, for brevity's sake
  raise ValueError(f'Found {len(possible_matches)} possible matches for user {username} on Speedrun.com -- Try one of these options:\n' + suggestions)

# Undocumented PHP APIs:

# Get latest runs for a game series (note: needs numeric ID, which comes from ???)
# https://www.speedrun.com/ajax_latestleaderboard.php?series=18748
# Get latest runs for all games (personalized if signed in)
# https://www.speedrun.com/ajax_latestleaderboard.php?amount=100
# Get the latest runs for a set of games (note: needs numeric IDs)
# https://www.speedrun.com/ajax_latestleaderboard.php?games=1545,1546,1547,4158,1548,1549,2147,2048,2222,2223,2224,6353,2225,7967

# Get game streams
# https://www.speedrun.com/ajax_streams.php?game=talos_principle&country=&haspb=on&following=off&start=0
