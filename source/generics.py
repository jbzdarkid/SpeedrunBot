import datetime
import logging

from . import database, src_apis, twitch_apis

# In order for the bot to post messages, it needs the "send_messages" permission.
# Please use this link in to grant the permissions to a server you administrate.
# (This is my bot's client ID. You'll need to change it to your bot's if you forked this repo.)
# https://discord.com/oauth2/authorize?scope=bot&permissions=2048&client_id=683472204280889511

def track_game(game_name, discord_channel):
  # Cutting this check -- hopefully we'll report errors during the database add.
  # if database.get_game_ids(game_name)[0]:
  #   logging.error(f'Already tracking game {game_name}')
  #   return # Game is already tracked

  src_game_id = src_apis.get_game_id(game_name)
  twitch_game_id = twitch_apis.get_game_id(game_name)
  database.add_game(game_name, twitch_game_id, src_game_id, discord_channel)


def moderate_game(game_name, discord_channel):
  src_game_id = src_apis.get_game_id(game_name)
  database.moderate_game(game_name, src_game_id, discord_channel)


def get_speedrunners_for_game2(game_names):
  twitch_game_ids = []
  src_game_ids = {}
  for game_name in game_names:
    twitch_game_id, src_game_id = database.get_game_ids(game_name)
    if not twitch_game_id:
      logging.error(f'Failed to find game IDs for game {game_name}. Skipping.')
      continue
    twitch_game_ids.append(twitch_game_id)
    src_game_ids[game_name] = src_game_id
    logging.info(f'Getting speedrunners for game {game_name} ({twitch_game_id} | {src_game_id})')

  streams = twitch_apis.get_live_game_streams2(twitch_game_ids)

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
    twitch_username = stream['user_name']
    game_name = stream['game_name']

    prefix = str(i).ljust(2) + '|' + twitch_username.ljust(20) + '|' + game_name.ljust(20) + '|'

    src_id = src_apis.get_src_id(twitch_username)
    if src_id is None:
      logging.info(f'{prefix}is not a speedrunner')
      continue

    if not src_apis.runner_runs_game(twitch_username, src_id, src_game_ids[game_name]):
      logging.info(f'{prefix}is a speedrunner, but not of this game')
      continue

    logging.info(f'{prefix}is a speedrunner, and runs this game')
    yield {
      'preview': stream['thumbnail_url'].format(width=320, height=180),
      'url': f'https://www.twitch.tv/{twitch_username}',
      'name': twitch_username,
      'title': stream['title'],
      'viewcount': stream['viewer_count'],
      'game_name': game_name,
    }


def get_new_runs(game_name, src_game_id, last_update):
  runs = src_apis.get_runs(game=src_game_id, status='new')
  logging.info(f'Found {len(runs)} unverified run{"s"[:len(runs)^1]} for {game_name}')
  new_last_update = last_update

  for run in runs:
    # Only announce runs which are more recent than the last announcement date.
    # Unfortunately, there's no way to suggest this filter to the speedrun.com APIs.
    submitted = datetime.datetime.strptime(run['submitted'], '%Y-%m-%dT%H:%M:%SZ')
    submitted = submitted.replace(tzinfo=datetime.timezone.utc) # strptime assumes local time, which is incorrect here.
    if submitted.timestamp() <= last_update:
      continue

    new_last_update = max(submitted.timestamp(), new_last_update)

    category = src_apis.get_category_name(run['category'])
    for variable in run['values']:
      subcategory = src_apis.get_subcategory_name(variable)
      if subcategory:
        category += f' ({subcategory})'

    weblink = run['weblink']
    time = datetime.timedelta(seconds=run['times']['primary_t'])
    runners = ', '.join(src_apis.get_src_name(player) for player in run['players'])
    yield f'New run submitted: {category} in {time} by {runners}: <{weblink}>'

  database.update_game_moderation_time(game_name, new_last_update)
