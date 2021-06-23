from . import database, src_apis, twitch_apis

logger = logging.getLogger(__name__)

def track_game(game_name, discord_channel):
  if database.get_game_ids(game_name)[0]:
    raise ValueError(f'Already tracking game {game_name}')
    return # Game is already tracked

  src_game_id = src_apis.get_game_id(game_name)
  twitch_game_id = twitch_apis.get_game_id(game_name)
  database.add_game(game_name, twitch_game_id, src_game_id, discord_channel)

  # In order for the bot to post messages, it needs the "send_messages" permission.
  # Please use this link in to grant the permissions to a server you administrate.
  # (This is my bot's client ID. You'll need to change it to your bot's if you forked this repo.)
  # https://discord.com/oauth2/authorize?scope=bot&permissions=2048&client_id=683472204280889511
  return (twitch_game_id, src_game_id) # Same as database.get_game_ids, to save a SQL read


def get_speedrunners_for_game2(game_names):
  twitch_game_ids = []
  src_game_ids = {}
  for game_name in game_names:
    twitch_game_id, src_game_id = database.get_game_ids(game_name)
    if not twitch_game_id:
      logger.error(f'Failed to find game IDs for game {game_name}. Skipping.')
      continue
    twitch_game_ids.append(twitch_game_id)
    src_game_ids[game_name] = src_game_id
    logger.info(f'Getting speedrunners for game {game_name} ({twitch_game_id} | {src_game_id})')

  streams = twitch_apis.get_live_game_streams2(twitch_game_ids)

  logger.info('id|username            |game name           |status')
  logger.info('--+--------------------+--------------------+--------------------------------------')
  for i, stream in enumerate(streams):
    twitch_username = stream['user_name']
    game_name = stream['game_name']

    prefix = str(i).ljust(2) + '|' + twitch_username.ljust(20) + '|' + game_name.ljust(20) + '|'

    src_id = src_apis.get_src_id(twitch_username)
    if src_id is None:
      logger.info(f'{prefix}is not a speedrunner')
      continue

    if not src_apis.runner_runs_game(twitch_username, src_id, src_game_ids[game_name]):
      logger.info(f'{prefix}is a speedrunner, but not of this game')
      continue

    logger.info(f'{prefix}is a speedrunner, and runs this game')
    yield {
      'preview': stream['thumbnail_url'].format(width=320, height=180),
      'url': f'https://www.twitch.tv/{twitch_username}',
      'name': twitch_username,
      'title': stream['title'],
      'viewcount': stream['viewer_count'],
      'game_name': game_name,
    }
