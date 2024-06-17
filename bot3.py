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

from source import database, generics, twitch_apis, src_apis, discord_apis, discord_websocket_apis, exceptions, commands
from source.utils import seconds_since_epoch, parse_time

# TODO: Add a test for 'what if a live message got deleted'
# TODO: Threading for user lookups will save a lot of time, especially as the list of games grows
# TODO: Try to improve performance by creating a thread for each runner
# TODO: <t:1626594025> is apparently a thing discord supports. Maybe useful somehow?
#   See https://discord.com/developers/docs/reference#message-formatting

client = discord_websocket_apis.WebSocket()

# We maintain a global list of admins (to protect our chat-only commands)
admins = []

def on_direct_message(message):
  def is_mention(word):
    # @member @&role #channel
    # https://github.com/Rapptz/discord.py/blob/master/discord/message.py#L892
    return re.fullmatch('<(@|@&|#)\d{15,20}>', word)
  # Since mentions can appear anywhere in the message, strip them out entirely for command processing.
  # User and channel mentions can still be accessed via message.mentions and message.channel_mentions

  args = [arg.strip() for arg in message['content'].split(' ') if not is_mention(arg)]

  if message['author']['id'] not in admins:
    return
  elif len(args) == 0:
    return
  elif not args[0].startswith('!'):
    discord_apis.send_message_ids(message['channel_id'], f'Unknown command: `{args[0]}`')
    return

  def restart():
    discord_apis.add_reaction(message, '💀')
    logging.info('Killing the bot with code 1')
    # Calling sys.exit from a thread does not kill the main process, so we must use os.kill
    import os
    os.kill(os.getpid(), 1)
  def log_streams():
    for _ in generics.get_speedrunners_for_game():
      pass
    send_last_lines('log_streams')
  def verifier_stats(game_name):
    return generics.get_verifier_stats(game_name, 24)
  def get_servers():
    servers = discord_apis.get_servers()
    output = f'This bot has presence in {len(servers)} servers:\n'
    for server in servers:
      output += f'Server `{server["name"]}` (ID {server["id"]})\n'
    return output
  def list_all_tracked_games():
    tracked_games_db = list(database.get_all_games())
    tracked_games = f'SpeedrunBot is currently tracking {len(tracked_games_db)} games:\n'
    for game_name, twitch_game_id, src_game_id in tracked_games_db:
      tracked_games += f'1. {game_name} ({twitch_game_id} | {src_game_id})\n'
    return tracked_games

  admin_commands = {
    '!restart': lambda: restart(*args[1:2]),
    '!git_update': lambda: f'```{git_update()}```',
    '!send_last_lines': lambda: send_last_lines('admin_command'),
    '!log_streams': lambda: log_streams(),
    '!verifier_stats': lambda: verifier_stats(' '.join(args[1:])),
    '!servers': lambda: get_servers(),
    '!list_all_tracked_games': lambda: list_all_tracked_games(),
  }

  discord_apis.add_reaction(message, '🕐') # In case processing takes a while, ack that we've gotten the message.
  try:
    command = admin_commands[args[0]]
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

      try:
        current_pb = src_apis.get_current_pb(run)
        message = discord_apis.send_message_ids(channel_id, f'New run submitted: {src_apis.run_to_string(run, current_pb)}')
      except exceptions.NetworkError:
        logging.exception('There was a network error while trying to announce an unverified run, not adding to database (will be announced next pass)')
        continue

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

  try:
    live_streams = {stream['name']: stream for stream in generics.get_speedrunners_for_game()}
    logging.info(f'Live streams: {live_streams}')
  except exceptions.NetworkError:
    live_streams = existing_streams
    logging.exception('There was a network error while fetching live streams, assuming status quo (no streams changed)')

  # Next, determine which streams have just gone live
  for stream_name, stream in live_streams.items():
    if stream_name not in existing_streams or stream['game'] != existing_streams[stream_name]['game']:
      logging.info(f'Stream {stream_name} started')
      content = '{name} is now doing runs of {game} at {url}'.format(
        name=discord_apis.escape_markdown(stream_name),
        game=stream['game'],
        url=stream['url'])
      channel_id = database.get_channel_for_game(stream['twitch_game_id'])
      try:
        message = discord_apis.send_message_ids(channel_id, content, get_embed(stream))
        metadata = twitch_apis.get_preview_metadata(stream['preview'])
      except exceptions.NetworkError:
        logging.exception('There was a network error while trying to announce a new stream, not adding to database (will be announced next pass)')
        continue

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
      try:
        success = discord_apis.edit_message_ids(
          channel_id=existing_stream['channel_id'],
          message_id=existing_stream['message_id'],
          embed=get_embed(existing_stream),
        )
      except exceptions.NetworkError:
        logging.exception('Failed to edit stream title/preview')
        continue
      if success:
        database.update_announced_stream(existing_stream)
      else:
        database.delete_announced_stream(existing_stream) # The message was deleted or otherwise invalid. Recreate it.

  for stream_name in streams_that_went_offline:
    stream = existing_streams[stream_name]

    stream_duration = int(seconds_since_epoch() - stream['start'])
    content = f'{discord_apis.escape_markdown(stream_name)} went offline after {timedelta(seconds=stream_duration)}.\n'
    content += f'Watch their latest videos here: <{stream["url"]}/videos?filter=archives>'
    try:
      discord_apis.edit_message_ids(
        channel_id=stream['channel_id'],
        message_id=stream['message_id'],
        content=content,
        embed=[], # Remove the embed
      )
    except exceptions.NetworkError:
      logging.exception('Failed to send stream offline')
      continue

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

    client.callbacks['on_direct_message'] = on_direct_message

    # Run some top-level startup code. If this throws, we have to shutdown (there is no fallback).
    try:
      discord_apis.register_all_commands(commands.ALL_COMMANDS)

      admins = [discord_apis.get_owner()['id']] # Only one admin for now (me!)
      client.run()
    except Exception:
      logging.exception('catch-all for client.run')
      send_last_lines('client.run')
      import os
      os.kill(os.getpid(), 1) # I don't think it shuts down the threads otherwise.
