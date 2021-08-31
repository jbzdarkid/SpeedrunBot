import logging
from datetime import datetime, timedelta

from . import database, exceptions
from .make_request import make_request

ONE_HOUR  = (3600)
ONE_DAY   = (3600 * 24)
ONE_WEEK  = (3600 * 24 * 7)
ONE_MONTH = (3600 * 24 * 7 * 30)

api = 'https://www.speedrun.com/api/v1'

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
  try:
    j = make_request('GET', f'{api}/users', params={'twitch': twitch_username})
  except exceptions.NetworkError:
    return None

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
  j = make_request('GET', f'{api}/users/{src_id}/personal-bests', params={'game': src_game_id})
  if len(j['data']) == 0:
    return False

  database.add_personal_best(src_id, src_game_id)
  return True


def get_game_id(game_name):
  j = make_request('GET', f'{api}/games', params={'name': game_name})
  if len(j['data']) == 0:
    raise exceptions.CommandError(f'Could not find game `{game_name}` on Speedrun.com')

  if len(j['data']) == 1:
    return j['data'][0]['id']

  possible_matches = []
  for game in j['data']:
    possible_match = game['names']['international'] # This used to be game['names']['twitch'], so !add_game might break now. Not sure.
    if possible_match == game_name:
      return game['id']
    possible_matches.append(f'`{possible_match}`')

  suggestions = ', '.join(possible_matches[:10]) # Only show a max of 10 matches, for brevity's sake
  raise exceptions.CommandError(f'Found {len(possible_matches)} possible matches for game `{game_name}` on Speedrun.com -- Try one of these options:\n' + suggestions)


def search_src_user(username):
  j = make_request('GET', f'{api}/users', params={'name': username})
  if len(j['data']) == 0:
    raise exceptions.CommandError(f'Could not find user {username} on Speedrun.com')

  if len(j['data']) == 1:
    return j['data'][0]['id']

  possible_matches = []
  for user in j['data']:
    possible_match = user['names']['international']
    if possible_match == username:
      return user['id']
    possible_matches.append(f'`{possible_match}`')

  suggestions = ', '.join(possible_matches[:10]) # Only show a max of 10 matches, for brevity's sake
  raise exceptions.CommandError(f'Found {len(possible_matches)} possible matches for user {username} on Speedrun.com -- Try one of these options:\n' + suggestions)


def get_runs(**params):
  if 'game' not in params and 'category' not in params:
    raise exceptions.CommandError('You can only get Speedrun.com runs with a game or a category')

  params['offset'] = 0
  params['max'] = 100 # Undocumented parameter, gets 100 runs at once.
  params['embed'] = 'players,level,category,category.variables'

  runs = []
  j = make_request('GET', f'{api}/runs', params=params)
  while 1:
    runs += j['data']

    for link in j['pagination']['links']:
      if link['rel'] == 'next':
        j = make_request('GET', link['uri'])
        continue
    break # No more results

  return runs


# NOTE: Run data must be fetched with all parameters in get_runs above
def run_to_string(run):
    category = run['category']['data']['name']

    if isinstance(run['level']['data'], dict):
      category = run['level']['data']['name'] + f': {category}'

    subcategories = {}
    for variable in run['category']['data']['variables']['data']:
      if not variable['is-subcategory']:
        continue
      subcategories[variable['id']] = variable['values']['values']

    for subcategory_id, value_id in run['values'].items():
      if subcategory := subcategories.get(subcategory_id, None):
        category += f' ({subcategory[value_id]["label"]})'

    time = timedelta(seconds=run['times']['primary_t'])

    def get_name(player):
      return player['names']['international'] if player['rel'] == 'user' else player['name']
    runners = ', '.join(map(get_name, run['players']['data']))

    weblink = run['weblink']

    return f'`{category}` in {time} by {runners}: <{weblink}>'


# Undocumented PHP APIs:

# Get latest runs for a game series (note: needs numeric ID, which comes from ???)
# https://www.speedrun.com/ajax_latestleaderboard.php?series=18748
# Get latest runs for all games (personalized if signed in)
# https://www.speedrun.com/ajax_latestleaderboard.php?amount=100
# Get the latest runs for a set of games (note: needs numeric IDs)
# https://www.speedrun.com/ajax_latestleaderboard.php?games=1545,1546,1547,4158,1548,1549,2147,2048,2222,2223,2224,6353,2225,7967

# Get game streams
# https://www.speedrun.com/ajax_streams.php?game=talos_principle&country=&haspb=on&following=off&start=0


# Edit run / Submit run
# When you submit a run, you are granted an ID (temporary, I assume) on page load. It lives in the <form id="editform"> object, and NOWHERE ELSE.
# Also, you are given a CSRF token, as a <meta> attribute, and also inside a few <input type="hidden" name="csrftoken"> objects.
# playerselect=0 means "I am an admin, I was not part of this run". Otherwise, 1-4 means "I was player # whatever".
# The variable IDs are visible in the page HTML, if nothing else.
# POST https://www.speedrun.com/ajax_editrun.php?id=abcd1234&game=2364&action=submit
# category=All_Sigils
# &player1=foo&playerselect=0
# &hour=1&minute=4&second=23&milliseconds=
# &loadshour=1&loadsminute=4&loadssecond=23&loadsmilliseconds=
# &variable16422=54487
# &variable12500=42106
# &platform=31
# &date=2021-06-12
# &video=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dsomething
# &splitsio=
# &comment=URL+encoded+comment%0D%0AWith+Octets
# &csrftoken=probably-important
