import logging
from datetime import timedelta

from . import database, exceptions
from .make_request import make_request, make_head_request
from .utils import seconds_since_epoch

ONE_HOUR  = (3600)
ONE_DAY   = (3600 * 24)
ONE_WEEK  = (3600 * 24 * 7)
ONE_MONTH = (3600 * 24 * 7 * 30)

api = 'https://www.speedrun.com/api/v1'
embeds = 'players,level,category,category.variables'

def get_src_id(twitch_username):
  if user := database.get_user(twitch_username):
    if user['src_id']:
      # Streamer found, is a known speedrunner.
      return user['src_id']
    # Streamer is found, but not a speedrunner.
    if seconds_since_epoch() < user['fetch_time'] + ONE_WEEK:
      # Last check was <1 week ago, return cached.
      return user['src_id']

  # Make a network call to determine if the streamer is a speedrunner.
  try:
    j = make_request('GET', f'{api}/users', params={'twitch': twitch_username})
  except exceptions.NetworkError:
    logging.exception(f'Failed to look up src user for twitch_username={twitch_username}, assuming non-runner')
    return None

  if len(j['data']) == 0:
    database.add_user(twitch_username, None)
    return None
  src_id = j['data'][0]['id']
  if not user:
    # When initially adding a user, we set the fetch_time to 0 so that further lookups will fetch their PBs.
    # TODO: This seems like a hack. If I wind up rewriting this to do multi-user-fetch, try to do something smarter.
    database.add_user(twitch_username, src_id, 0)
  return src_id


def runner_runs_game(twitch_username, src_id, src_game_id):
  if database.has_personal_best(src_id, src_game_id):
    return True

  if user := database.get_user(twitch_username):
    if seconds_since_epoch() < user['fetch_time'] + ONE_DAY:
      # Last check was <1 day ago, don't fetch again
      return False

  # If a game was just recently added, the leaderboards might be locked down -- so we won't find any runs.
  # For equity, search for a PB for any game in the series to determine if the streamer is a speedrunner.
  games_in_series = get_games_in_series(src_game_id)
  
  try:
    personal_bests = get_personal_bests(src_id, games_in_series)
  except exceptions.NetworkError:
    logging.exception(f'Could not fetch {src_id} personal bests for any of {games_in_series}, assuming non-speedrunner')
    return False

  database.update_user_fetch_time(twitch_username)

  if len(personal_bests) == 0:
    return False

  database.add_personal_best(src_id, src_game_id)
  return True


def get_games_in_series(src_game_id):
  series_id, fetch_time = database.get_game_series(src_game_id)

  if fetch_time and seconds_since_epoch() < fetch_time + ONE_DAY:
    # Last check was <1 day ago, just return based on database info
    return database.get_games_in_series(series_id)

  if not series_id:
    try:
      j = make_request('GET', f'{api}/games/{src_game_id}')
      series_uri = next((link['uri'] for link in j['data']['links'] if link['rel'] == 'series'), None)
      if series_uri:
        series_id = series_uri.replace('https://www.speedrun.com/api/v1/series/', '')
        database.set_game_series(src_game_id, series_id) # Save the series ID before we go any further

    except exceptions.NetworkError:
      logging.exception(f'Could not find series for in {src_game_id}, assuming no games in series')

  if not series_id:
    return [src_game_id] # No series id, the series is just (this game) and nothing else.

  games_in_series = []
  try:
    j = make_request('GET', f'{api}/series/{series_id}/games')
    games_in_series = [game['id'] for game in j['data']]
    for game_id in games_in_series:
      database.set_game_series(game_id, series_id)

  except exceptions.NetworkError:
    logging.exception(f'Could not find series for in {src_game_id}, assuming no games in series')

  return games_in_series


def get_personal_bests(src_id, src_game_ids, **params):
  # Sadly, there doesn't seem to be a way to call the SRC API to get PBs in multiple games, so we're stuck making one call and sorting through the results.
  j = make_request('GET', f'{api}/users/{src_id}/personal-bests', params=params)
  return [run for run in j['data'] if run['run']['game'] in src_game_ids]


def get_game(game_name):
  j = make_request('GET', f'{api}/games', params={'name': game_name})
  if len(j['data']) == 0:
    raise exceptions.CommandError(f'Could not find game `{game_name}` on Speedrun.com')

  if len(j['data']) == 1:
    return j['data'][0]

  possible_matches = []
  for game in j['data']:
    possible_match = game['names']['international']
    if possible_match == game_name: # If there are multiple options, but one is an exact match, return the exact match.
      return game
    possible_matches.append(f'`{possible_match}`')

  suggestions = ', '.join(possible_matches[:10]) # Only show a max of 10 matches, for brevity's sake
  raise exceptions.CommandError(f'Found {len(possible_matches)} possible matches for game `{game_name}` on Speedrun.com -- Try one of these options:\n' + suggestions)


def search_src_user(username):
  j = make_request('GET', f'{api}/users', params={'name': username})
  if len(j['data']) == 0:
    raise exceptions.CommandError(f'Could not find user `{username}` on Speedrun.com')

  if len(j['data']) == 1:
    return j['data'][0]['id']

  possible_matches = []
  for user in j['data']:
    possible_match = user['names']['international']
    if possible_match == username:
      return user['id']
    possible_matches.append(f'`{possible_match}`')

  suggestions = ', '.join(possible_matches[:10]) # Only show a max of 10 matches, for brevity's sake
  raise exceptions.CommandError(f'Found {len(possible_matches)} possible matches for user `{username}` on Speedrun.com -- Try one of these options:\n' + suggestions)


def get_run_status(run_id):
  j = make_request('GET', f'{api}/runs/{run_id}', allow_4xx=True)
  if 'status' in j:
    if j['status'] == 404:
      return 'deleted'
    else:
      return j['message']

  run_status = j['data']['status']['status']
  if run_status == 'rejected':
    return 'rejected'
  elif run_status == 'verified':
    return 'verified'

  # The underlying SRC APIs do not actually 'delete' runs, they seem to simply unlink them in their database.
  # Thus, a submission which is deleted by the runner will still show as 'new' (but not be returned by the get_runs call).
  # Double-check that this run was deleted according to the frontend.
  status_code, _ = make_head_request(j['data']['weblink'])
  if status_code == 404:
    return 'deleted'
  else:
    return run_status # probably 'new'


def get_runs(**params):
  if 'game' not in params and 'category' not in params:
    raise exceptions.CommandError('You can only get Speedrun.com runs with a game or a category')

  params['offset'] = 0
  params['max'] = 100 # Undocumented parameter, gets 100 runs at once.
  params['embed'] = embeds

  runs = []
  try:
    j = make_request('GET', f'{api}/runs', params=params)
    while 1:
      runs += j['data']

      next_link = next((link['uri'] for link in j['pagination']['links'] if link['rel'] == 'next'), None)
      if next_link:
        j = make_request('GET', next_link)
        continue
      break # No more results
  except exceptions.NetworkError:
    logging.exception(f'Failed to load runs for {params}, assuming empty')
    return runs

  return runs


def get_leaderboard(game, category, level=None, variables=None):
  params = {}
  if variables is not None:
    params = {f'var-{key}': value['id'] for key, value in variables.items()}
  if level:
    j = make_request('GET', f'{api}/leaderboards/{game}/level/{level}/{category}', params=params)
  else:
    j = make_request('GET', f'{api}/leaderboards/{game}/category/{category}', params=params)

  # This does not support continue, so I assume it just reports the entire leaderboard.
  for run in j['data']['runs']:
    run['run']['place'] = run['place']
    yield run['run']


# NOTE: Run must be fetched with at least embed=category,category.variables
# Returns a mapping of variable_id: {data}, where data is an arbitrary set of properties from SRC, including 'id'.
def get_subcategories(run):
  all_subcategories = {}
  for variable in run['category']['data']['variables']['data']:
    if not variable['is-subcategory']:
      continue
    all_subcategories[variable['id']] = variable['values']['values']

  run_subcategories = {}
  for variable_id, value_id in run['values'].items():
    if variable_id not in all_subcategories:
      continue # Not a subcategory

    value = all_subcategories[variable_id][value_id]
    value['id'] = value_id
    run_subcategories[variable_id] = value

  return run_subcategories


def parse_name(player):
  if 'names' in player:
    return player['names']['international']
  elif 'name' in player:
    return player['name']
  else:
    return player['id']


# NOTE: Run data must be fetched with embeds
def get_current_pb(new_run):
  game = new_run['game']
  category = new_run['category']['data']['id']
  players = set(parse_name(player) for player in new_run['players']['data'])
  time = new_run['times']['primary_t']
  level = new_run['level']['data']['id'] if isinstance(new_run['level']['data'], dict) else None

  subcategories = get_subcategories(new_run)
  try:
    leaderboard = get_leaderboard(game, category, level, subcategories)
  except exceptions.NetworkError:
    logging.exception(f'Failed to load the leaderboard for {game}, assuming no existing PB')
    return None

  for run in leaderboard:
    if 'place' not in new_run and time <= run['times']['primary_t']:
      new_run['place'] = run['place']
    if players == set(parse_name(player) for player in run['players']):
      return run


# NOTE: Run data must be fetched with embeds
def run_to_string(run, current_pb=None):
  category = run['category']['data']['name']

  if isinstance(run['level']['data'], dict):
    category = run['level']['data']['name'] + f': {category}'

  subcategories = get_subcategories(run)
  for value in subcategories.values():
    category += f' ({value["label"]})'

  time = timedelta(seconds=run['times']['primary_t'])

  runners = ', '.join(map(parse_name, run['players']['data']))

  output = f'`{category}` in {time} by {runners}'
  if 'place' in run:
    n = int(run['place'])
    # https://stackoverflow.com/a/36977549
    ordinal = {1:'st', 2:'nd', 3:'rd'}.get(n%100 if n%100<20 else n%10, 'th')
    output += f', which would put them in {n}{ordinal} place'
  if current_pb:
    current_pb_time = timedelta(seconds=current_pb['times']['primary_t'])
    n = int(current_pb['place'])
    # https://stackoverflow.com/a/36977549
    ordinal = {1:'st', 2:'nd', 3:'rd'}.get(n%100 if n%100<20 else n%10, 'th')
    output += f'\nAn improvement over their current PB of {current_pb_time} ({n}{ordinal} place)'
  output += f'\n<{run["weblink"]}>'
  return output


# Undocumented PHP APIs, that I apparently *am* allowed to call.
# https://discord.com/channels/157645920324943872/343897241766854656/902321525263319110
# (Can't access it, but the image says "no support nor api stability provided")
# Hopefully they stop using numeric IDs.

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
