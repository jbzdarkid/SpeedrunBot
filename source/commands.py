import logging

from collections import defaultdict

from . import database, twitch_apis, src_apis

ALL_COMMANDS = defaultdict(lambda: defaultdict(dict))
CALLBACKS = {}

ARG_TYPE_STRING  = 3
ARG_TYPE_CHANNEL = 7

def add_command(desc):
  def _inner(func):
    CALLBACKS[func.__name__] = func
    ALL_COMMANDS[func.__name__]['name'] = func.__name__
    ALL_COMMANDS[func.__name__]['type'] = 1 # CHAT_INPUT
    ALL_COMMANDS[func.__name__]['description'] = desc
    ALL_COMMANDS[func.__name__]['dm_permission'] = False
    ALL_COMMANDS[func.__name__]['nsfw'] = False
    return func
  return _inner


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


def require_permission(permission):
  def _inner(func):
    permissions = ALL_COMMANDS[func.__name__].get('permissions', 0)
    permissions |= {
      'manage_channels': 0x0000000000000010,
    }[permission]
    ALL_COMMANDS[func.__name__]['permissions'] = permissions
    return func
  return _inner


#######################
# User-level commands #
#######################


"""
@add_command('Explicitly announce your stream when it goes live')
@add_argument('twitch_username', 'Your stream name on twitch.tv')
@add_argument('src_username', 'Your username on speedrun.com')
def announce_me(twitch_username, src_username, channel):
  data = database.get_games_for_channel(channel)
  if not data:
    return f'There are no games currently associated with <#{channel}>. Please call this command in a channel which is announcing streams.'

  twitch_apis.get_user_id(twitch_username) # Will throw if there is any ambiguity about the twich username
  src_id = src_apis.search_src_user(src_username) # Will throw if there is any ambiguity about the src username
  database.add_user(twitch_username, src_id)
  for d in data:
    database.add_personal_best(src_id, d['src_game_id'])

  games = ' or '.join(f'`{d["game_name"]}`' for d in data)
  return f'Will now announce `{twitch_username}` in <#{channel}> when they go live on twitch playing {games}.'


@add_command('Get general information about this bot and how it works')
def about(channel):
  data = database.get_games_for_channel(channel)
  games = ' or '.join(f'`{d["game_name"]}`' for d in data) if data else 'any tracked game'
  response = 'Speedrunning bot, created by `darkid`.\n'
  response += f'The bot will search for twitch streams of {games}, then check to see if the given streamer is on speedrun.com, then check to see if the speedrunner has a PB in that game.\n'
  response += 'If all of that is true, it announces their stream in the associated channel.\n'
  response += 'For more info, see the [GitHub readme](https://github.com/jbzdarkid/SpeedrunBot).'
  return response


@add_command('Get a runner\'s personal best in their current game')
@add_argument('twitch_username', 'The runner\'s stream name on twitch.tv')
@add_argument_opt('game_name', 'The game to look up (defaults to the currently streamed game)')
def personal_best(twitch_username, game_name=None):
  user = database.get_user(twitch_username)
  if not user:
    return f'Could not find user `{twitch_username}` in the database'

  if not game_name:
    for stream in database.get_announced_streams():
      if stream['name'] == twitch_username:
        game_name = stream['game']
        break
    else:
      return f'User {twitch_username} is not live, please provide the game name as the second argument.'

  src_game_id = src_apis.get_game(game_name)['id']
  personal_bests = src_apis.get_personal_bests(user['src_id'], src_game_id, embed=src_apis.embeds) # Embeds are required for run_to_string
  output = f'Streamer {twitch_username} has {len(personal_bests)} personal bests in {game_name}:'
  for entry in personal_bests[:10]:
    run = entry['run']
    run.update(entry) # Embeds are side-by-side with the run from this API, for some reason.
    output += '\n' + src_apis.run_to_string(run)
  return output


######################
# Moderator commands #
######################


@add_command('Stop announcing this stream when it goes live')
@add_argument('twitch_username', 'The stream name on twitch.tv')
@require_permission('manage_channels')
def forget(twitch_username):
  twitch_apis.get_user_id(twitch_username) # Will throw if there is any ambiguity about the twich username
  database.remove_user(twitch_username)
  return f'Removed PBs and user data for {twitch_username}. You will need to unlink your SRC to prevent future announcements.'


@add_command('Announce speedrunners of this game when they go live')
@add_argument('game_name', 'The exact name of the game to announce on speedrun.com')
@add_argument_opt('channel', 'The channel to announce runners in (default: current channel)')
@require_permission('manage_channels')
def track_game(game_name, channel):
  src_game = src_apis.get_game(game_name)
  src_game_id = src_game['id']
  twitch_game_id = twitch_apis.get_game_id(src_game['names']['twitch'])
  database.add_game(game_name, twitch_game_id, src_game_id, channel)
  return f'Will now announce runners of `{game_name}` in channel <#{channel}>.'


@add_command('Stop announcing speedrunners for a specific game')
@add_argument('game_name', 'The exact name of the game to stop announcing')
@add_argument_opt('channel', 'The channel to stop announcing in (default: current channel)')
@require_permission('manage_channels')
def untrack_game(game_name, channel):
  database.remove_game(game_name)
  return f'No longer announcing runners of `{game_name}` in channel <#{channel}>.'


@add_command('List currently tracked games in the current channel')
@require_permission('manage_channels')
def list_tracked_games(channel):
  data = database.get_games_for_channel(channel)
  tracked_games = f'SpeedrunBot is currently tracking {len(data)} games:\n'
  for d in data:
    tracked_games += f'1. {d["game_name"]} ({d["twitch_game_id"]} | {d["src_game_id"]})\n'
  return tracked_games


@add_command('Announce newly-submitted runs of this game when they are awaitng verification')
@add_argument('game_name', 'Speedrun.com game to watch for new submissions')
@add_argument_opt('channel', 'The channel to announce runs in (default: current channel)')
@require_permission('manage_channels')
def moderate_game(game_name, channel):
  src_game_id = src_apis.get_game(game_name)['id']
  database.moderate_game(game_name, src_game_id, channel)
  return f'Will now announce newly submitted runs of `{game_name}` in channel <#{channel}>.'

@add_command('Stop announcing newly-submitted runs of this game when they are awaitng verification')
@add_argument('game_name', 'Speedrun.com game to stop watching for new submissions')
@add_argument_opt('channel', 'The channel to stop announcing runs in (default: current channel)')
@require_permission('manage_channels')
def unmoderate_game(game_name, channel):
  database.unmoderate_game(game_name)
  return f'No longer announcing newly submitted runs of `{game_name}` in channel <#{channel}>.'

"""
