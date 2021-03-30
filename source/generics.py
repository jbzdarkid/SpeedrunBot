from . import database, src_apis, twitch_apis

def track_game(game_name, discord_channel):
  if database.get_game_ids(game_name)[0]:
    print(f'Already tracking game {game_name}')
    return # Game is already tracked

  src_game_id = src_apis.get_game_id(game_name)
  twitch_game_id = twitch_apis.get_game_id(game_name)
  database.add_game(game_name, twitch_game_id, src_game_id, discord_channel)

  # In order for the bot to post messages, it needs the "send_messages" permission.
  # Please use this link in to grant the permissions to a server you administrate.
  # (This is my bot's client ID. You'll need to change it to your bot's if you forked this repo.)
  # https://discord.com/oauth2/authorize?scope=bot&permissions=2048&client_id=683472204280889511
  return (twitch_game_id, src_game_id) # Same as database.get_game_ids, to save a SQL read


def get_speedrunners_for_game(game_name):
  twitch_game_id, src_game_id = database.get_game_ids(game_name)
  if not twitch_game_id:
    print('Failed to find game IDs for game {game_name}. Skipping.')
    raise StopIteration() # This might not be the correct way to indicate an empty iterator.
  print(f'Getting speedrunners for game {game_name} ({twitch_game_id} | {src_game_id})')

  streams = twitch_apis.get_live_game_streams(twitch_game_id)
  print(f'There are currently {len(streams)} live streams of {game_name}:')
  for i, stream in enumerate(streams):
    twitch_username = stream['user_name']
    src_id = src_apis.get_src_id(twitch_username)
    prefix = f'({str(i+1).ljust(2)}) {twitch_username.ljust(20)}'
    if src_id is None:
      print(f'{prefix}is not a speedrunner')
      continue

    if not src_apis.runner_runs_game(twitch_username, src_id, src_game_id):
      print(f'{prefix}is a speedrunner, but not of {game_name}')
      continue

    print(f'{prefix}is a speedrunner, and runs {game_name}')
    yield {
      'preview': stream['thumbnail_url'].format(width=320, height=180),
      'url': f'https://www.twitch.tv/{twitch_username}',
      'name': twitch_username,
      'title': stream['title'],
      'viewcount': stream['viewer_count'],
    }
