import logging
import logging.handlers
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from uuid import uuid4

from source import database, generics, twitch_apis, src_apis, discord_apis, discord_websocket_apis, exceptions
from source.utils import seconds_since_epoch, parse_time

# TODO: Add a test for 'what if a live message got deleted'
# TODO: <t:1626594025> is apparently a thing discord supports. Maybe useful somehow?
#   See https://discord.com/developers/docs/reference#message-formatting
# TODO: Consider batching SRC user lookups (when gsfg calls get_src_id). Not super relevant (since I'm working with niche games) but will matter for bigger games.

# We maintain a global list of admins (since it's used by both the websocket client and the REST client).
# This value is fetched during websocket startup, so there may be a brief period of time where there are no admins registered.
client = discord_websocket_apis.WebSocket()
admins = []

def on_direct_message(message):
  if message['author']['id'] not in admins:
    return # DO NOT process DMs from non-admins (For safety. It might be fine to process all DMs, I just don't want people spamming the bot without my knowledge.)

  on_message_internal(message)


def on_message(message):
  if message['author']['id'] == client.user['id']:
    return # DO NOT process our own messages
  elif any(client.user['id'] == mention['id'] for mention in message['mentions']):
    pass # DO process messages which mention us, no matter which channel they're sent
  elif len(database.get_games_for_channel(message['channel_id'])) == 0:
    return # DO NOT process messages in unwatched channels

  on_message_internal(message)


def on_message_internal(message):
  def is_mention(word):
    # @member @&role #channel
    return re.fullmatch('<(@|@&|#)\d{15,20}>', word)
  # Since mentions can appear anywhere in the message, strip them out entirely for command processing.
  # User and channel mentions can still be accessed via message.mentions and message.channel_mentions

  args = [arg.strip() for arg in message['content'].split(' ') if not is_mention(arg)]

  def get_channel():
    # https://github.com/Rapptz/discord.py/blob/master/discord/message.py#L892
    channel_mentions = [m[1] for m in re.findall('<#([0-9]{15,20})>', message['content'])]
    if len(channel_mentions) == 0:
      return message['channel_id']
    if len(channel_mentions) == 1:
      return channel_mentions[0]
    if len(channel_mentions) > 1:
      raise exceptions.CommandError('Response mentions more than one channel. Please mention at most one channel name at a time.')

  def assert_args(usage, *required_args, example=None):
    if any((arg == None or arg == '') for arg in required_args):
      error = f'Usage of {args[0]}: `{args[0]} {usage}`'
      if example:
        error += f'\nFor example: `{args[0]} {example}`'
      raise exceptions.UsageError(error)

  # Actual commands here
  def track_game(channel_id, game_name):
    assert_args('#channel Game Name', channel_id, game_name)
    src_game = src_apis.get_game(game_name)
    src_game_id = src_game['id']
    twitch_game_id = twitch_apis.get_game_id(src_game['names']['twitch'])
    database.add_game(game_name, twitch_game_id, src_game_id, channel_id)
    return f'Will now announce runners of `{game_name}` in channel <#{channel_id}>.'
  def untrack_game(channel_id, game_name):
    assert_args('#channel Game Name', channel_id, game_name)
    database.remove_game(game_name)
    return f'No longer announcing runners of `{game_name}` in channel <#{channel_id}>.'
  def moderate_game(channel_id, game_name):
    assert_args('#channel Game Name', channel_id, game_name)
    src_game_id = src_apis.get_game(game_name)['id']
    database.moderate_game(game_name, src_game_id, channel_id)
    return f'Will now announce newly submitted runs of `{game_name}` in channel <#{channel_id}>.'
  def unmoderate_game(channel_id, game_name):
    assert_args('#channel Game Name', channel_id, game_name)
    database.unmoderate_game(game_name)
    return f'No longer announcing newly submitted runs of `{game_name}` in channel <#{channel_id}>.'
  def restart(code=0):
    discord_apis.add_reaction(message, '💀')
    logging.info(f'Killing the bot with code {code}')
    # Calling sys.exit from a thread does not kill the main process, so we must use os.kill
    import os
    os.kill(os.getpid(), int(code))
  def log_streams():
    for _ in generics.get_speedrunners_for_game():
      pass
    send_last_lines('log_streams')
  def verifier_stats(game_name):
    assert_args('Game Name', game_name)
    return generics.get_verifier_stats(game_name, 24)
  def announce(channel_id, twitch_username=None, src_username=None):
    assert_args('twitch_username src_username', twitch_username, src_username, example='jbzdarkid darkid')
    data = database.get_games_for_channel(channel_id)
    if not data:
      raise exceptions.UsageError(f'There are no games currently associated with <#{channel_id}>. Please call this command in a channel which is announcing streams.')

    twitch_apis.get_user_id(twitch_username) # Will throw if there is any ambiguity about the twich username
    src_id = src_apis.search_src_user(src_username) # Will throw if there is any ambiguity about the src username
    database.add_user(twitch_username, src_id)
    for d in data:
      database.add_personal_best(src_id, d['src_game_id'])

    games = ' or '.join(f'`{d["game_name"]}`' for d in data)
    return f'Will now announce `{twitch_username}` when they go live on twitch playing {games}.'
  def forget(twitch_username=None):
    assert_args('twitch_username', twitch_username)
    twitch_apis.get_user_id(twitch_username) # Will throw if there is any ambiguity about the twich username
    database.remove_user(twitch_username)
    return f'Removed PBs and user data for {twitch_username}. You will need to unlink your SRC to prevent future announcements.'
  def get_servers():
    servers = discord_apis.get_servers()
    output = f'This bot has presence in {len(servers)} servers:\n'
    for server in servers:
      output += f'Server `{server["name"]}` (ID {server["id"]})\n'
    return output
  def about():
    data = database.get_games_for_channel(message['channel_id'])
    games = ' or '.join(f'`{d["game_name"]}`' for d in data) if data else 'any tracked game'
    response = 'Speedrunning bot, created by darkid#1647.\n'
    response += f'The bot will search for twitch streams of {games}, then check to see if the given streamer is on speedrun.com, then check to see if the speedrunner has a PB in that game.\n'
    response += 'If so, it announces their stream in this channel.\n'
    response += 'For more info, see the readme at <https://github.com/jbzdarkid/SpeedrunBot>'
    return response
  def help():
    all_commands = [f'`{key}`' for key in commands]
    if message['author']['id'] in admins:
      all_commands += [f'`{key}`' for key in admin_commands]
    return 'Available commands: ' + ', '.join(all_commands)
  def personal_best(twitch_username, game_name=None):
    assert_args('Twitch username', twitch_username)
    user = database.get_user(twitch_username)
    if not user:
      raise exceptions.CommandError(f'Could not find user `{twitch_username}` in the database')

    if not game_name:
      for stream in database.get_announced_streams():
        if stream['name'] == twitch_username:
          game_name = stream['game']
          break
      else:
        raise exceptions.CommandError(f'User {twitch_username} is not live, please provide the game name as the second argument.')

    src_game_id = src_apis.get_game(game_name)['id']
    personal_bests = src_apis.get_personal_bests(user['src_id'], src_game_id, embed=src_apis.embeds) # Embeds are required for run_to_string
    output = f'Streamer {twitch_username} has {len(personal_bests)} personal bests in {game_name}:'
    for entry in personal_bests[:10]:
      run = entry['run']
      run.update(entry) # Embeds are side-by-side with the run from this API, for some reason.
      output += '\n' + src_apis.run_to_string(run)
    return output
  def list_tracked_games():
    tracked_games_db = list(database.get_all_games())
    i = 0
    tracked_games = f'SpeedrunBot is currently tracking {len(tracked_games_db)} games:\n'
    for game_name, twitch_game_id, src_game_id in tracked_games_db:
      i += 1
      tracked_games += f'{i:>2}. {game_name} ({twitch_game_id} | {src_game_id})\n'
    return tracked_games

  admin_commands = {
    '!track_game': lambda: track_game(get_channel(), ' '.join(args[1:])),
    '!untrack_game': lambda: untrack_game(get_channel(), ' '.join(args[1:])),
    '!moderate_game': lambda: moderate_game(get_channel(), ' '.join(args[1:])),
    '!unmoderate_game': lambda: unmoderate_game(get_channel(), ' '.join(args[1:])),
    '!restart': lambda: restart(*args[1:2]),
    '!git_update': lambda: f'```{git_update()}```',
    '!send_last_lines': lambda: send_last_lines('admin_command'),
    '!log_streams': lambda: log_streams(),
    '!verifier_stats': lambda: verifier_stats(' '.join(args[1:])),
    '!forget': lambda: forget(*args[1:2]), # Admin command to prevent abuse
    '!servers': lambda: get_servers(),
    '!list_tracked_games': lambda: list_tracked_games(),
  }
  commands = {
    '!announce_me': lambda: announce(get_channel(), *args[1:3]),
    '!about': lambda: about(),
    '!help': lambda: help(),
    '!pb': lambda: personal_best(*args[1:2], ' '.join(args[2:])),
  }

  if len(args) == 0:
    return
  elif message['author']['id'] in admins and args[0] in admin_commands:
    command = admin_commands[args[0]] # Allow admin versions of normal commands
  elif args[0] in commands:
    command = commands[args[0]]
  elif args[0].startswith('!'):
    discord_apis.send_message_ids(message['channel_id'], f'Unknown command: `{args[0]}`')
    return
  else:
    return # Not a command

  discord_apis.add_reaction(message, '🕐') # In case processing takes a while, ack that we've gotten the message.
  try:
    response = command()
    if response:
      discord_apis.add_reaction(message, '🔇')
      discord_apis.send_message_ids(message['channel_id'], response)
  except exceptions.UsageError as e: # Usage errors
    discord_apis.send_message_ids(message['channel_id'], str(e))
  except exceptions.CommandError as e: # User errors
    discord_apis.send_message_ids(message['channel_id'], f'Error: {e}')
  except exceptions.NetworkError as e: # Server / connectivity errors
    logging.exception('Network error')
    discord_apis.send_message_ids(message['channel_id'], f'Failed due to network error, please try again: {e}')
  except Exception: # Coding errors
    logging.exception(f'General error during {args[0]}')
    send_last_lines('response-general')

  discord_apis.remove_reaction(message, '🕐')


send_error = Path(__file__).with_name('send_error.py')
def send_last_lines(cause):
  output = subprocess.run([sys.executable, send_error, cause], stderr=subprocess.STDOUT, stdout=subprocess.PIPE, text=True)
  if output.returncode != 0:
    logging.error('Sending last lines failed:')
    logging.error(output.stdout)


parent_cwd = Path(__file__).parent
def git_update():
  output = subprocess.run(['git', 'pull', '--ff-only'], capture_output=True, text=True, cwd=parent_cwd)
  return output.stdout + ('\n' if (output.stderr or output.stdout) else '') + output.stderr

def announce_new_runs():
  """
  We have, as input:
  - A list of runs which were unverified at last iteration (according to the database)
  - A list of runs that are still not verified (according to the API)

  1. Iterate the list of API-unverified runs & remove all previously known.
    -> The remaining runs from the API are announced
  2. Iterate the list of database-unverified runs
    a. Remove all which are still known to be unverified (from the SRC API)
    b. API call to check the status of the remaining runs
  """

  for game_name, src_game_id, channel_id in database.get_all_moderated_games():
    db_unverified = database.get_unverified_runs(src_game_id)
    src_unverified = src_apis.get_runs(game=src_game_id, status='new')
    logging.info(f'Found {len(db_unverified)} unverified runs in the database for {game_name}')
    logging.info(f'Found {len(src_unverified)} unverified runs according to SRC for {game_name}')

    for run in src_unverified:
      run_id = run['id']
      if run_id in db_unverified:
        # This run was previously known to be unverified, and it still is. Remove from both lists.
        del db_unverified[run_id]
        continue

      current_pb = src_apis.get_current_pb(run)
      message = discord_apis.send_message_ids(channel_id, f'New run submitted: {src_apis.run_to_string(run, current_pb)}')

      logging.info(f'Tracking new unverified run {run_id}')
      database.add_unverified_run(
        run_id=run_id,
        src_game_id=src_game_id,
        submitted=parse_time(run['submitted'], '%Y-%m-%dT%H:%M:%SZ'),
        channel_id=channel_id,
        message_id=message['id'],
      )

    # All remaining runs are likely verified (accept or reject)
    for run_id, run in db_unverified.items():
      run_status = src_apis.get_run_status(run_id)
      logging.info(f'Run {run_id} is no longer status=new, now status={run_status}')
      if run_status == 'rejected':
        discord_apis.add_reaction_ids(run['channel_id'], run['message_id'], '👎')
      elif run_status == 'verified':
        discord_apis.add_reaction_ids(run['channel_id'], run['message_id'], '👍')
      elif run_status == 'deleted':
        discord_apis.add_reaction_ids(run['channel_id'], run['message_id'], '🗑')
      elif run_status == 'new':
        continue # Somehow not listed via get_runs, but whatever, we can just ignore it here
      else:
        raise exceptions.InvalidApiResponseError(f'Run {run_id} was somehow status {run_status}')

      database.delete_unverified_run(run_id)


def get_embed(stream):
  return {
    'type': 'image',
    'color': 0x6441A4, # Twitch branding color
    'title': discord_apis.escape_markdown(stream['title']),
    'url': stream['url'],
    'image': {
      # Add random data to the end of the image URL to force Discord to regenerate the preview.
      'url': stream['preview'] + '?' + uuid4().hex
    }
  }


def announce_live_channels():
  """
  We have, as input:
  - A list of streams which were live at last iteration
  - A list of streams that are still live (in the same game)

  1. Iterate the list of live streams & remove all previously known.
    -> The remaining streams go online
  2. Iterate the list of known streams & remove all offline
  a. Double check for stream still live (according to preview headers)
  b. Double check for game change (according to twitch API)
  -> The remaining streams go offline
  """

  # First, fetch the existing & new streams
  existing_streams = {stream['name']: stream for stream in database.get_announced_streams()}
  logging.info(f'Existing streams: {existing_streams}')

  live_streams = {stream['name']: stream for stream in generics.get_speedrunners_for_game()}
  logging.info(f'Live streams: {live_streams}')

  # Next, determine which streams have just gone live
  for stream_name, stream in live_streams.items():
    if stream_name not in existing_streams or stream['game'] != existing_streams[stream_name]['game']:
      logging.info(f'Stream {stream_name} started')
      content = '{name} is now doing runs of {game} at {url}'.format(
        name=discord_apis.escape_markdown(stream_name),
        game=stream['game'],
        url=stream['url'])
      channel_id = database.get_channel_for_game(stream['twitch_game_id'])
      message = discord_apis.send_message_ids(channel_id, content, get_embed(stream))
      metadata = twitch_apis.get_preview_metadata(stream['preview'])

      database.add_announced_stream(
        name=stream_name,
        game=stream['game'],
        title=stream['title'],
        url=stream['url'],
        preview=stream['preview'],
        channel_id=channel_id,
        message_id=message['id'],
        preview_expires=metadata['expires'],
      )

  # Then, determine which streams are still online
  streams_that_went_offline = []
  streams_that_may_be_offline = []
  streams_that_are_still_live = []

  for stream_name, stream in existing_streams.items():
    if stream_name in live_streams:
      if stream['game'] == live_streams[stream_name]['game']:
        logging.info(f'Stream {stream_name} is still live')
        streams_that_are_still_live.append(stream_name)
      else:
        # The stream has changed games to another, tracked game.
        # We have already made another announcement for the new stream, send this one offline.
        streams_that_went_offline.append(stream_name)
    else:
      # The stream has potentially gone offline. However, the twitch APIs are not the most consistent,
      # so we double-check the stream preview image, which redirects to a 404 when a channel goes offline.
      metadata = twitch_apis.get_preview_metadata(stream['preview'])
      if metadata['redirect']:
        logging.info(f'Stream {stream_name} has gone offline according to both the APIs and the preview image')
        streams_that_went_offline.append(stream_name)
      else:
        streams_that_may_be_offline.append(stream_name)

  # The preview image check is generic, and doesn't account for streamers changing games.
  # So, we make another API call for streams that are still online, to see what their current game is.
  if streams_that_may_be_offline != []:
    for stream in twitch_apis.get_live_streams(user_logins=streams_that_may_be_offline):
      stream_name = stream['name']
      previous_game = existing_streams[stream_name]['game']
      if stream['game'] == previous_game:
        logging.info(f'Even though stream {stream_name} appears offline in the APIs, the preview image indicates that it is still live')
        streams_that_are_still_live.append(stream_name)
        live_streams[stream_name] = stream # Manually add the stream to the live_streams list, as it would not be there otherwise
      else:
        logging.info(f'Stream {stream_name} has changed games from {previous_game} to {stream["game"]}, sending it offline')
        streams_that_went_offline.append(stream_name)

  for stream_name in streams_that_are_still_live:
    existing_stream = existing_streams[stream_name]
    live_stream = live_streams[stream_name]

    if title_changed := live_stream['title'] != existing_stream['title']:
      logging.info(f'Stream {stream_name} title changed, editing')
      existing_stream['title'] = live_stream['title']
    if preview_expired := seconds_since_epoch() > existing_stream['preview_expires']:
      logging.info(f'Stream {stream_name} preview image expired, refreshing')
      metadata = twitch_apis.get_preview_metadata(stream['preview'])
      live_stream['preview_expires'] = metadata['expires']

    if title_changed or preview_expired:
      success = discord_apis.edit_message_ids(
        channel_id=existing_stream['channel_id'],
        message_id=existing_stream['message_id'],
        embed=get_embed(existing_stream),
      )
      if success:
        database.update_announced_stream(existing_stream)
      else:
        database.delete_announced_stream(existing_stream) # The message was deleted or otherwise invalid. Recreate it.

  for stream_name in streams_that_went_offline:
    stream = existing_streams[stream_name]

    stream_duration = int(seconds_since_epoch() - stream['start'])
    content = f'{discord_apis.escape_markdown(stream_name)} went offline after {timedelta(seconds=stream_duration)}.\n'
    content += f'Watch their latest videos here: <{stream["url"]}/videos?filter=archives>'
    discord_apis.edit_message_ids(
      channel_id=stream['channel_id'],
      message_id=stream['message_id'],
      content=content,
      embed=[], # Remove the embed
    )

    # If there's a network error, we DON'T want to delete (so that we *do* delete on the next pass)
    # However, if the edit failed, we DO want to delete (since the message is gone)
    database.delete_announced_stream(stream)


if __name__ == '__main__':
  # This logging nonsense brought to you by python. Calls to logging.error will go to stderr,
  # and logging.* will be written to a out.log (which overflows into out.log.1)
  # Note that there are separate log files for the bootstrapper and the subtask. This is because python does not share log files between processes.

  # https://stackoverflow.com/a/6692653
  class CustomFormatter(logging.Formatter):
    def format(self, r):
      current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
      location = f'{r.module}.{r.funcName}:{r.lineno}'
      message = f'[{current_time}] {r.thread:05} {location:40} {r.msg}'

      if r.exc_info and not r.exc_text:
        r.exc_text = self.formatException(r.exc_info)
      if r.exc_text:
        message += '\n' + r.exc_text

      return message

  logfile = Path(__file__).with_name('out.log' if 'subtask' in sys.argv else 'out-parent.log')
  file_handler = logging.handlers.RotatingFileHandler(logfile, maxBytes=5_000_000, backupCount=1, encoding='utf-8', errors='replace')
  file_handler.setLevel(logging.INFO)
  file_handler.setFormatter(CustomFormatter())

  stream_handler = logging.StreamHandler(sys.stderr)
  stream_handler.setLevel(logging.ERROR)
  stream_handler.setFormatter(logging.Formatter('Error: %(message)s'))

  # The level here acts as a global level filter. Why? I dunno.
  # Set to info so requests doesn't spam it too much.
  logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

  if 'subtask' not in sys.argv:
    import time
    while 1:
      logging.info(f'Starting subtask at {datetime.now()}')
      logging.info(git_update())
      output = subprocess.run([sys.executable, __file__, 'subtask'] + sys.argv[1:])
      if output.returncode != 0:
        send_last_lines(f'parent: "{output.returncode}"')
        logging.error('Subprocess crashed, waiting for 60 seconds before restarting')
        time.sleep(60) # Sleep after exit, to prevent losing my token.

  else:
    def forever_thread(func, sleep_time):
      while 1: # This loop does not exit
        try:
          func()
        except exceptions.NetworkError:
          logging.exception('A network error occurred')
          send_last_lines('forever-network')
        except Exception:
          logging.exception('catch-all for forever_thread')
          send_last_lines('forever-generic')

        sleep(sleep_time)

    threading.Thread(target=forever_thread, args=(announce_live_channels, 60)).start()
    threading.Thread(target=forever_thread, args=(announce_new_runs,      600)).start()

    client.callbacks['on_message'] = on_message
    client.callbacks['on_direct_message'] = on_direct_message
    try:
      admins = [discord_apis.get_owner()['id']] # This can throw, and if it does, we have no recompense.
      client.run()
    except Exception:
      logging.exception('catch-all for client.run')
      send_last_lines('client.run')
      import os
      os.kill(os.getpid(), 1) # I don't think it shuts down the threads otherwise.
