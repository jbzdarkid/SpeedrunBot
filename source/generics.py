import logging

from . import database, src_apis, twitch_apis
from .utils import parse_time, seconds_since_epoch

def get_speedrunners_for_game():
  twitch_game_ids = []
  src_game_ids = {}
  for game_name, twitch_game_id, src_game_id in database.get_all_games():
    twitch_game_ids.append(twitch_game_id)
    src_game_ids[twitch_game_id] = src_game_id
    logging.info(f'Getting speedrunners for game {game_name} ({twitch_game_id} | {src_game_id})')

  if len(twitch_game_ids) == 0:
    logging.info('There are no games being tracked, so we are not calling twitch.')
    return

  # We iterate the list of games into one list so that we can make a single network call here.
  # Otherwise, we would have to make one call to twitch per game, which is slow.
  streams = twitch_apis.get_live_streams(game_ids=twitch_game_ids)

  logging.info('id|username            |game name           |status')
  logging.info('--+--------------------+--------------------+--------------------------------------')
  for i, stream in enumerate(streams):
    twitch_username = stream['name']
    game_name = stream['game']
    twitch_game_id = stream['twitch_game_id']

    prefix = f'{i:<2}|{twitch_username:<20}|{game_name:<20}|'

    if twitch_game_id not in src_game_ids:
      logging.info(f'{prefix}is not streaming a tracked game... somehow')
      continue

    if 'nosrl' in stream['title']:
      logging.info(f'{prefix}is explicitly not doing speedruns')
      continue

    src_id = src_apis.get_src_id(twitch_username)
    if src_id is None:
      logging.info(f'{prefix}is not a speedrunner')
      continue

    if not src_apis.runner_runs_game(twitch_username, src_id, src_game_ids[twitch_game_id]):
      logging.info(f'{prefix}is a speedrunner, but not of this game')
      continue

    logging.info(f'{prefix}is a speedrunner, and runs this game')
    yield stream


def get_verifier_stats(game_name, since_months=24):
  src_game_id = src_apis.get_game(game_name)['id']

  runs = src_apis.get_runs(game=src_game_id, status='verified', orderby='verify-date', direction='desc')
  logging.info(f'Found {len(runs)} total verified runs for {game_name}')
  runs.sort(key=lambda run: run['submitted'], reverse=True) # I don't trust SRC's API ordering, so re-sort

  players = {}
  for run in runs:
    for player in run['players']['data']:
      player_id = player.get('id', None)
      if player_id and player_id not in players:
        players[player_id] = src_apis.parse_name(player)

  def summarize(runs):
    verifier_counts = {}

    for run in runs:
      verifier = run['status']['examiner']
      verifier_counts[verifier] = verifier_counts.get(verifier, 0) + 1
    total_runs = len(runs)

    logging.info(f'Found {total_runs} runs in the past {since_months} months, verified by {len(verifier_counts)} verifiers')

    sorted_counts = []
    for verifier, count in verifier_counts.items():
      if verifier not in players:
        # In some rare cases, a verifier might not have any runs on the leaderboard themselves. Insert a placeholder in this case.
        players[verifier] = f'src_id={verifier}'
      sorted_counts.add((count, players[verifier]))
    sorted_counts.sort(reverse=True)

    output = ''
    for count, verifier in sorted_counts:
      percent = round(count * 100.0 / total_runs, 2)
      output += f'{verifier} has verified {count} runs ({percent}%)\n'
    return output

  # now actually build the output
  time_threshold = seconds_since_epoch() - 60*60*24*30*since_months # Approximately the number of seconds in a month. Whatever.
  runs_since_threshold = []
  for run in runs:
    submitted = parse_time(run['submitted'], '%Y-%m-%dT%H:%M:%SZ')
    if submitted.timestamp() > time_threshold:
      runs_since_threshold.append(run)

  output = f'Verifier statistics for {game_name} in the past 2 years:\n'
  output += summarize(runs_since_threshold)

  last_100_runs = runs[:100]
  output += f'\nVerifier statistics for the last 100 runs of {game_name}:\n'
  output += summarize(last_100_runs)

  return output

