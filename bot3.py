import json
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

# BUGS
# If a user is a speedrunner (but not of a tracked game) we check for PB on every call.

# WANT
# TODO: Consider refactoring the core bot logic so that we don't need to filter streams by game
#  Specifically, I want to simplify on_parsed_streams so that it is only called once, with the complete list of streams.
#  That way I can also move live_channels into on_parsed_streams, where it belongs.
#  Then move client.live_channels into a database. Just full read/write JSON is ok.
# TODO: Discord is not renaming embeds? Or, I'm not changing the embed title correctly on edits.
#   Definitely broken. Test again now that I'm off discordpy?
# TODO: [nosrl] (and associated tests)

# MAYBE
# TODO: Add a test for 'what if a live message got deleted'
# TODO: Threading for user lookups will save a lot of time, especially as the list of games grows
# TODO: Try to improve performance by creating a thread for each runner
# TODO: Add tests for the database (using in-memory storage?)
#  Can mock the network via make_request.py
# TODO: Stop using select (*) wrong
#  Didn't I fix this? Who knows.
# TODO: <t:1626594025> is apparently a thing discord supports. Maybe useful somehow?
#   See https://discord.com/developers/docs/reference#message-formatting
# TODO: Consider using urrlib3 over requests? I'm barely using requests now.

# Global, since it's referenced in both systems.
tracked_games = {}
client = None
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
  elif message['channel_id'] not in tracked_games:
    return # DO NOT process messages in unwatched channels

  on_message_internal(message)


def on_message_internal(message):
  def is_mention(word):
    # https://github.com/Rapptz/discord.py/blob/master/discord/message.py#L882
    return re.fullmatch('<(@!|@&|#)\d{15,20}>', word)
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
    generics.track_game(game_name, channel_id)
    return f'Will now announce runners of {game_name} in channel <#{channel_id}>.'
  def untrack_game(channel_id, game_name):
    assert_args('#channel Game Name', channel_id, game_name)
    database.remove_game(game_name)
    return f'No longer announcing runners of {game_name} in channel <#{channel_id}>.'
  def moderate_game(channel_id, game_name):
    assert_args('#channel Game Name', channel_id, game_name)
    generics.moderate_game(game_name, channel_id)
    return f'Will now announce newly submitted runs of {game_name} in channel <#{channel_id}>.'
  def unmoderate_game(channel_id, game_name):
    assert_args('#channel Game Name', channel_id, game_name)
    generics.unmoderate_game(game_name, channel_id)
    return f'No longer announcing newly submitted runs of {game_name} in channel <#{channel_id}>.'
  def restart():
    sys.exit(int(args[1]) if len(args) > 1 else 0)
  def git_update():
    output = subprocess.run(['git', 'pull', '--ff-only'], capture_output=True, text=True, cwd=Path(__file__).parent)
    return '```' + output.stdout + ('\n' if (output.stderr or output.stdout) else '') + output.stderr + '```'
  def sql(command, *args):
    return '\n'.join(map(str, database.execute(command, *args)))
  def link(twitch_username, src_username):
    assert_args('twitch_username src_username', twitch_username, src_username, example='jbzdarkid darkid')
    twitch_apis.get_user_id(twitch_username) # Will throw if there is any ambiguity about the twich username
    src_id = src_apis.search_src_user(src_username)
    database.add_user(twitch_username, src_id)
    return f'Successfully linked twitch user {twitch_username} to speedrun.com user {src_username}'
  def about():
    game = tracked_games.get(message['channel_id'], 'this game')
    response = 'Speedrunning bot, created by darkid#1647.\n'
    response += f'The bot will search for twitch streams of {game}, then check to see if the given streamer is a speedrunner, then check to see if the speedrunner has a PB in {game}.\n'
    response += 'If so, it announces their stream in this channel.'
    return response
  def help():
    all_commands = [f'`{key}`' for key in commands]
    if message['author']['id'] in admins:
      all_commands += [f'`{key}`' for key in admin_commands]
    return 'Available commands: ' + ', '.join(all_commands)

  admin_commands = {
    '!track_game': lambda: track_game(get_channel(), ' '.join(args[1:])),
    '!untrack_game': lambda: untrack_game(get_channel(), ' '.join(args[1:])),
    '!moderate_game': lambda: moderate_game(get_channel(), ' '.join(args[1:])),
    '!unmoderate_game': lambda: unmoderate_game(get_channel(), ' '.join(args[1:])),
    '!restart': lambda: restart(),
    '!git_update': lambda: git_update(),
    '!send_last_lines': lambda: send_last_lines(),
    '!sql': lambda: sql(*args[1:]),
  }
  commands = {
    '!link': lambda: link(*args[1:3]),
    '!about': lambda: about(),
    '!help': lambda: help(),
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
  
  try:
    response = command()
    if response:
      discord_apis.add_reaction(message, '🔇')
      discord_apis.send_message_ids(message['channel_id'], response)
  except exceptions.UsageError as e: # Usage errors
    discord_apis.send_message_ids(message['channel_id'], str(e))
  except exceptions.NetworkError as e: # Server / connectivity errors
    logging.exception('Network error')
    raise exceptions.CommandError(f'Could not track game due to network error {e}')
  except exceptions.CommandError as e: # Actual errors
    discord_apis.send_message_ids(message['channel_id'], f'Error: {e}')


send_error = Path(__file__).with_name('send_error.py')
def send_last_lines():
  output = subprocess.run([sys.executable, send_error], stderr=subprocess.STDOUT, stdout=subprocess.PIPE, text=True)
  if output.returncode != 0:
    logging.error('Sending last lines failed:')
    logging.error(output.stdout)


# If we encounter an uncaught exception, we need to log it, and send details.
def uncaught_thread_exception(args):
  if args.exc_type == SystemExit: # Calling sys.exit from a thread does not kill the main process, so we must use os.kill
    import os
    os.kill(os.getpid(), args.exc_value.code)
  logging.exception(f'Uncaught exception in {args.thread.name}')
  send_last_lines()
threading.excepthook = uncaught_thread_exception


def announce_new_runs():
  for game_name, src_game_id, channel_id, last_update in database.get_all_moderated_games():
    for content in generics.get_new_runs(game_name, src_game_id, last_update):
      discord_apis.send_message_ids(channel_id, content)


p = Path(__file__).with_name('live_channels.txt')
def announce_live_channels():
  # Contains twitch streams which are actively running (or have recently closed).
  if not p.exists():
    with p.open('w') as f:
      p.write('{}')

  for game_name, channel_id in database.get_all_games():
    global tracked_games
    tracked_games[channel_id] = game_name

  # Calls to list() make me sad.
  streams = list(generics.get_speedrunners_for_game2(list(tracked_games.values())))

  if streams:
    with p.open('r') as f:
      live_channels = json.load(f)

    for game_name, channel_id, in database.get_all_games():
      # For simplicity, we just filter this list down for each respective game.
      # It's not (that) costly, and it saves me having to refactor the core bot logic.
      game_streams = [stream for stream in streams if stream['game_name'] == game_name]
      logging.info(f'There are {len(game_streams)} streams of {game_name}')

      on_parsed_streams(live_channels, game_streams, game_name, channel_id)

    with p.open('w') as f:
      json.dump(live_channels, f)


def on_parsed_streams(live_channels, streams, game, channel_id):
  def get_embed(stream):
    return {
      'title': discord_apis.escape_markdown(stream['title']),
      'title_link': stream['url'],
      # Add random data to the end of the image URL to force Discord to regenerate the preview.
      'image': stream['preview'] + '?' + uuid4().hex,
      'color': 0x6441A4, # Twitch branding color
    }

  offline_streams = set(live_channels.keys())

  for stream in streams:
    name = discord_apis.escape_markdown(stream['name'])
    # A missing discord message is essentially equivalent to a new stream;
    # if we didn't send a message, then we weren't really live.
    if (name not in live_channels) or ('message' not in live_channels[name]):
      logging.info(f'Stream {name} started at {datetime.now().ctime()}')
      content = f'{name} is now doing runs of {game} at {stream["url"]}'
      try:
        message = discord_apis.send_message_ids(channel_id, content, get_embed(stream))
      except exceptions.NetworkError:
        logging.exception('Network error while announcing new stream')
        continue # The message will be posted next pass.
      stream['message'] = message['id']
      stream['start'] = datetime.now().timestamp()
      stream['game'] = game
      stream['offline'] = 0
      live_channels[name] = stream
    else:
      stream = live_channels[name]
      offline_streams.remove(name)
      stream['offline'] = 0

      if 'game' in stream and game == stream['game']:
        logging.info(f'Stream {name} is still live at {datetime.now().ctime()}')
        try:
          # Always edit the message so that the embed picture updates.
          discord_apis.edit_message_ids(
            channel_id=channel_id,
            message_id=stream['message'],
            embed=get_embed(stream)
          )
        except exceptions.NetworkError:
          logging.exception('Network error while updating stream message')
          continue # The message will be edited next pass.
      else:
        logging.info(f'Stream {name} changed games at {datetime.now().ctime()}')
        # Send the stream offline so that it will come back online with the new game,
        # to be announced in another channel.
        offline_streams.add(name)
        stream['offline'] = 9999
        stream['game'] = game

  for name in offline_streams:
    stream = live_channels[name]
    if stream['game'] != game:
      continue # Only parse offline streams for the current game.

    stream['offline'] = stream.get('offline', 0) + 1
    if stream['offline'] < 5: # MAX_OFFLINE
      logging.info(f'Stream {name} has been offline for {stream["offline"]} consecutive checks')
      continue

    # Stream has been offline for MAX_OFFLINE consecutive checks, close down the post
    logging.info(f'Stream {name} went offline at {datetime.now().ctime()}')
    duration_sec = int(datetime.now().timestamp() - live_channels[name]['start'])
    content = f'{name} went offline after {timedelta(seconds=duration_sec)}.\r\n'
    content += 'Watch their latest videos here: <' + stream['url'] + '/videos?filter=archives>'
    try:
      discord_apis.edit_message_ids(
        channel_id=channel_id,
        message_id=stream['message'],
        content=content,
        embed=[], # Remove the embed
      )
    except exceptions.NetworkError:
      logging.exception('Network error while sending a stream offline')
      continue # The stream can go offline next pass. The offline count will increase, which is OK.
    del live_channels[name]


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
      output = subprocess.run(['git', 'pull', '--ff-only'], capture_output=True, text=True, cwd=Path(__file__).parent)
      if output.stdout:
        logging.info(output.stdout)
      if output.stderr:
        logging.error(output.stderr)
      output = subprocess.run([sys.executable, __file__, 'subtask'] + sys.argv[1:])
      if output.returncode != 0:
        send_last_lines()
        logging.error('Subprocess crashed, waiting for 60 seconds before restarting')
        time.sleep(60) # Sleep after exit, to prevent losing my token.

  else:
    with Path(__file__).with_name('discord_token.txt').open() as f:
      token = f.read().strip()

    def forever_thread(func, sleep_time):
      while 1: # This loop does not exit
        try:
          func()
        except:
          logging.exception('catch-all for forever_thread')
          send_last_lines()

        sleep(sleep_time)

    threading.Thread(target=forever_thread, args=(announce_live_channels, 60)).start()
    threading.Thread(target=forever_thread, args=(announce_new_runs,      600)).start()

    admins = [discord_apis.get_owner()['id']]

    client = discord_websocket_apis.WebSocket(
      on_message = on_message,
      on_direct_message = on_direct_message,
    )
    try:
      client.run()
    except:
      logging.exception('catch-all for client.run')
      send_last_lines()
