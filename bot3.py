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

# WANT
# TODO: [nosrl] (and associated tests)
# TODO: Reactions with :eyes: and :thumpsup: for verifiers

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

# Global, since it's referenced in both systems. Actually, client isn't. Hmm....
# This feels odd. We're implicitly relying on client.user being fetched early?
# Or are we? Maybe we could provide client inside the callback to make this clearer. I think admins is the only global, in fact.
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
  elif database.get_game_for_channel(message['channel_id']) == None:
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
  def restart(code=0):
    discord_apis.add_reaction(message, '💀')
    # Calling sys.exit from a thread does not kill the main process, so we must use os.kill
    import os
    os.kill(os.getpid(), int(code))
  def git_update():
    output = subprocess.run(['git', 'pull', '--ff-only'], capture_output=True, text=True, cwd=Path(__file__).parent)
    return '```' + output.stdout + ('\n' if (output.stderr or output.stdout) else '') + output.stderr + '```'
  def announce(channel_id, twitch_username=None, src_username=None):
    assert_args('twitch_username src_username', twitch_username, src_username, example='jbzdarkid darkid')
    data = database.get_game_for_channel(channel_id)
    if data == None:
      raise exceptions.UsageError(f'There is no game currently associated with <#{channel_id}>. Please call this command in a channel which is announcing streams.')

    twitch_apis.get_user_id(twitch_username) # Will throw if there is any ambiguity about the twich username
    src_id = src_apis.search_src_user(src_username) # Will throw if there is any ambiguity about the src username
    database.add_user(twitch_username, src_id)
    database.add_personal_best(src_id, data['src_game_id'])
    return f'Will now announce `{twitch_username}` when they go live on twitch playing `{data["game_name"]}`.'
  def about():
    data = database.get_game_for_channel(message['channel_id'])
    game = data['game_name'] if data else 'this game'
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
    '!restart': lambda: restart(*args[1:]),
    '!git_update': lambda: git_update(),
    '!send_last_lines': lambda: send_last_lines(),
  }
  commands = {
    '!announce_me': lambda: announce(get_channel(), *args[1:3]),
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
  except Exception as e: # Coding errors
    logging.exception(f'General error during {args[0]}')
    send_last_lines()

  discord_apis.remove_reaction(message, '🕐')


send_error = Path(__file__).with_name('send_error.py')
def send_last_lines():
  output = subprocess.run([sys.executable, send_error], stderr=subprocess.STDOUT, stdout=subprocess.PIPE, text=True)
  if output.returncode != 0:
    logging.error('Sending last lines failed:')
    logging.error(output.stdout)


def announce_new_runs():
  for game_name, src_game_id, channel_id, last_update in database.get_all_moderated_games():
    for content in generics.get_new_runs(game_name, src_game_id, last_update):
      discord_apis.send_message_ids(channel_id, content)


def get_embed(stream):
  return {
    'type': 'image',
    'color': 0x6441A4, # Twitch branding color
    'title': discord_apis.escape_markdown(stream['title']),
    'url': stream['url'],
    # Add random data to the end of the image URL to force Discord to regenerate the preview.
    'image': {
      'url': stream['preview'] + '?' + uuid4().hex,
    }
  }


def announce_live_channels():
  # We coalesce this into a list so that we can make database operations during iteration.
  streams = list(generics.get_speedrunners_for_game2())
  logging.info(f'There are {len(streams)} live streams')

  for stream in streams:
    stream['name'] = discord_apis.escape_markdown(stream['name'])
    
    if announced_stream := database.get_announced_stream(stream['name'], stream['game']):
      # If the stream was already announced, update the title and update the message
      announced_stream['title'] = stream['title']

      logging.info(f'Stream {stream["name"]} is still live')
      # Edit the message so that the embedded picture updates.
      discord_apis.edit_message_ids(
        channel_id=announced_stream['channel_id'],
        message_id=announced_stream['message_id'],
        embed=get_embed(announced_stream),
      )
      database.update_announced_stream(announced_stream)
    else:
      # If the stream is new, announce it
      logging.info(f'Stream {stream["name"]} started')
      content = f'{stream["name"]} is now doing runs of {stream["game"]} at {stream["url"]}'
      channel_id = database.get_channel_for_game(stream['game'])
      message = discord_apis.send_message_ids(channel_id, content, get_embed(stream))

      database.add_announced_stream(
        name=stream['name'],
        game=stream['game'],
        title=stream['title'],
        url=stream['url'],
        preview=stream['preview'],
        channel_id=channel_id,
        message_id=message['id'],
      )

  # get_announced_streams returns an iterator which keeps the database active.
  # Coalesce it into a list so that we can call delete_announced_stream during iteration.
  announced_streams = list(database.get_announced_streams())
  for announced_stream in announced_streams:
    stream_offline_for = datetime.now().timestamp() - announced_stream['last_live']
    if stream_offline_for > 1*60:
      logging.info(f'Stream {announced_stream["name"]} has been offline for {timedelta(seconds=stream_offline_for)}')
    if stream_offline_for < 5*60:
      continue # Streams go offline after 5 minutes

    # Make a network call to the actual twitch webpage to see if this stream is still online.
    stream_is_really_offline = not twitch_apis.is_stream_online(announced_stream['channel_id'])
    if not stream_is_really_offline:
      database.update_announced_stream(announced_stream) # Reset the timer
      continue

    stream_duration = int(datetime.now().timestamp() - announced_stream['start'])
    content = f'{announced_stream["name"]} went offline after {timedelta(seconds=stream_duration)}.\r\n'
    content += 'Watch their latest videos here: <' + announced_stream['url'] + '/videos?filter=archives>'
    discord_apis.edit_message_ids(
      channel_id=announced_stream['channel_id'],
      message_id=announced_stream['message_id'],
      content=content,
      embed=[], # Remove the embed
    )
    database.delete_announced_stream(announced_stream)


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
    def forever_thread(func, sleep_time):
      while 1: # This loop does not exit
        try:
          func()
        except exceptions.NetworkError:
          pass
        except:
          logging.exception('catch-all for forever_thread')
          send_last_lines()

        sleep(sleep_time)

    threading.Thread(target=forever_thread, args=(announce_live_channels, 60)).start()
    threading.Thread(target=forever_thread, args=(announce_new_runs,      600)).start()

    client.callbacks['on_message'] = on_message
    client.callbacks['on_direct_message'] = on_direct_message
    try:
      admins = [discord_apis.get_owner()['id']] # This can throw, and if it does, we have no recompense.
      client.run()
    except:
      logging.exception('catch-all for client.run')
      send_last_lines()
      import os
      os.kill(os.getpid(), 1) # I don't think it shuts down the threads otherwise.
