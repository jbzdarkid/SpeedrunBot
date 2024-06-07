import logging

from collections import defaultdict

from . import database, twitch_apis, src_apis

ALL_COMMANDS = defaultdict(lambda: defaultdict(dict))
ADMIN_COMMANDS = {}
USER_COMMANDS = {}

ARG_TYPE_STRING  = 3
ARG_TYPE_CHANNEL = 7

def add_command(desc, is_admin=True):
  def _inner(func):
    if is_admin:
      ADMIN_COMMANDS[func.__name__] = func
    else:
      USER_COMMANDS[func.__name__] = func
    ALL_COMMANDS[func.__name__]['name'] = func.__name__
    ALL_COMMANDS[func.__name__]['type'] = 1 # CHAT_INPUT
    ALL_COMMANDS[func.__name__]['description'] = desc
    return func
  return _inner


def add_user_command(desc):
  return add_command(desc, is_admin=False)


def add_argument(name, desc, type=ARG_TYPE_STRING, required=True):
  def _inner(func):
    options = ALL_COMMANDS[func.__name__].get('options', [])
    options.append({
      'name': name,
      'description': desc,
      'type': type,
      'required': required,
    })
    options.sort(key = lambda o: 0 if o['required'] else 1) # Required options must come first
    ALL_COMMANDS[func.__name__]['options'] = options
    return func
  return _inner


def add_argument_opt(name, desc, type=ARG_TYPE_STRING):
  return add_argument(name, desc, type, required=False)


## And now, for the actual commands ##

@add_command('Announce speedrunners of a game when they go live')
@add_argument('game_name', 'The exact name of the game to announce on speedrun.com')
@add_argument_opt('channel', 'The channel to announce runners in')
def track_game(game_name, channel):
  src_game = src_apis.get_game(game_name)
  src_game_id = src_game['id']
  twitch_game_id = twitch_apis.get_game_id(src_game['names']['twitch'])
  database.add_game(game_name, twitch_game_id, src_game_id, channel['id'])
  return f'Will now announce runners of `{game_name}` in channel <#{channel["id"]}>.'


@add_command('Stop announcing speedrunners for a specific game')
@add_argument('game_name', 'The exact name of the game to stop announcing')
@add_argument_opt('channel', 'The channel to stop announcing in')
def untrack_game(game_name, channel):
  database.remove_game(game_name)
  return f'No longer announcing runners of `{game_name}` in channel <#{channel["id"]}>.'


@add_command('List currently tracked games')
def list_tracked_games():
  tracked_games_db = list(database.get_all_games())
  tracked_games = f'SpeedrunBot is currently tracking {len(tracked_games_db)} games:\n'
  for game_name, twitch_game_id, src_game_id in tracked_games_db:
    tracked_games += f'1. {game_name} ({twitch_game_id} | {src_game_id})\n'
  return tracked_games




"""
  admin_commands = {
    '!moderate_game': lambda: moderate_game(get_channel(), ' '.join(args[1:])),
    '!unmoderate_game': lambda: unmoderate_game(get_channel(), ' '.join(args[1:])),
    '!restart': lambda: restart(*args[1:2]),
    '!git_update': lambda: f'```{git_update()}```',
    '!send_last_lines': lambda: send_last_lines('admin_command'),
    '!log_streams': lambda: log_streams(),
    '!verifier_stats': lambda: verifier_stats(' '.join(args[1:])),
    '!forget': lambda: forget(*args[1:2]), # Admin command to prevent abuse
    '!servers': lambda: get_servers(),
  }
  commands = {
    '!announce_me': lambda: announce(get_channel(), *args[1:3]),
    '!about': lambda: about(),
    '!help': lambda: help(),
    '!pb': lambda: personal_best(*args[1:2], ' '.join(args[2:])),
  }

"""
