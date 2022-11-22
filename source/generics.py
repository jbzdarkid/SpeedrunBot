import logging

from . import database, src_apis, twitch_apis
from .utils import parse_time

def get_speedrunners_for_game():
  twitch_game_ids = []
  src_game_ids = {}
  for game_name, twitch_game_id, src_game_id in database.get_all_games():
    twitch_game_ids.append(twitch_game_id)
    src_game_ids[game_name] = src_game_id
    logging.info(f'Getting speedrunners for game {game_name} ({twitch_game_id} | {src_game_id})')

  if len(twitch_game_ids) == 0:
    logging.info('There are no games being tracked, so we are not calling twitch.')
    return

  # We iterate the list of games into one list so that we can make a single network call here.
  # Otherwise, we would have to make one call to twitch per game, which is slow.
  streams = twitch_apis.get_live_streams(game_ids=twitch_game_ids)

  # For performance here, instead of directly iterating the streams, pass them into a ThreadPoolExecutor.
  # pool_data = []
  # def pool_func(stream):
  #   output = stream.modify()
  #   pool_data.append(output) # Thread-safety provided by the GIL
  #
  # with ThreadPoolExecutor(8) as pool:
  #   for i, stream in enumerate(pool.map(pool_func, streams)):
  #     # log stuff
  # return pool_data

  logging.info('id|username            |game name           |status')
  logging.info('--+--------------------+--------------------+--------------------------------------')
  for i, stream in enumerate(streams):
    twitch_username = stream['name']
    game_name = stream['game']

    prefix = str(i).ljust(2) + '|' + twitch_username.ljust(20) + '|' + game_name.ljust(20) + '|'

    if game_name not in src_game_ids:
      logging.info(f'{prefix}is not streaming a tracked game... somehow')
      continue

    if 'nosrl' in stream['title']:
      logging.info(f'{prefix}is explicitly not doing speedruns')
      continue

    src_id = src_apis.get_src_id(twitch_username)
    if src_id is None:
      logging.debug(f'{prefix}is not a speedrunner')
      continue

    if not src_apis.runner_runs_game(twitch_username, src_id, src_game_ids[game_name]):
      logging.info(f'{prefix}is a speedrunner, but not of this game')
      continue

    logging.info(f'{prefix}is a speedrunner, and runs this game')
    yield stream


def get_new_runs(game_name, src_game_id, last_update):
  runs = src_apis.get_runs(game=src_game_id, status='new')
  logging.info(f'Found {len(runs)} unverified run{"s"[:len(runs)^1]} for {game_name}')
  new_last_update = last_update

  for run in runs:
    # Only announce runs which are more recent than the last announcement date.
    # Unfortunately, there's no way to suggest this filter to the speedrun.com APIs.
    # It might be possible using one of the undocumented PHP APIs.
    submitted = parse_time(run['submitted'], '%Y-%m-%dT%H:%M:%SZ')
    if submitted.timestamp() <= last_update:
      continue
    current_pb = src_apis.get_current_pb(run)
    yield f'New run submitted: {src_apis.run_to_string(run, current_pb)}'

    new_last_update = max(submitted.timestamp(), new_last_update)

  database.update_game_moderation_time(game_name, new_last_update)
