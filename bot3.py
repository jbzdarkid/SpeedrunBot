import discord
import json
import logging
import logging.handlers
import re
import subprocess
import sys
from asyncio import sleep
from datetime import datetime, timedelta
from pathlib import Path
from requests.exceptions import ConnectionError
from uuid import uuid4

from source import database, generics, twitch_apis, src_apis

# TODO: [nosrl] (and associated tests)
# TODO: Add a test for 'what if a live message got deleted'
# TODO: Threading for user lookups will save a lot of time, especially as the list of games grows
# TODO: Try to improve performance by creating a thread for each runner
# TODO: Add tests for the database (using in-memory storage?)
#  Can mock the network via make_request.py
# TODO: Consider refactoring the core bot logic so that we don't need to filter streams by game
#  Specifically, I want to simplify on_parsed_streams so that it is only called once, with the complete list of streams.
# TODO: Discord is not renaming embeds? Or, I'm not changing the embed title correctly on edits.
#   Definitely broken. Try without discord.py
# TODO: Stop using select (*) wrong
# TODO: Stop hardcoding the admins list
#   Ensure that "self" (owner of the discord API token) is an admin by default.
#   Change client.admins to a function (is_admin?)
#   Provide !op <user> and !deop <user>
# TODO: Move client.live_channels into a database? It's OK if all we ever do with it is full read / full write.
# TODO: Try to wean off of discord.py? (I guess also create source/discord_apis.py)
#   Start with the simple stuff (send a message, edit a message, get a channel)
#   Move on to the harder stuff (on_message, HTTP errors, auth errors)
# TODO: I can use ?embed=property to ask SRC APIs to expand the property (and include it in the results).
#   https://github.com/speedruncomorg/api/blob/master/version1/embedding.md
#   https://www.speedrun.com/api/v1/runs/ydr4xdjz?embed=players,platforms,variables,game,category
#   Should mean I no longer need category/variable DB (for !moderate_game announcements)
# TODO: <t:1626594025> is apparently a thing discord supports. Maybe useful somehow?
#   See https://github.com/Rapptz/discord.py/commit/d1a2ee46209917000e57612c0bdce29b5035e15a

# Globals
client = discord.Client()
client.started = False # Single-shot boolean to know if we've started up already
client.tracked_games = {} # Map of channel_id : game name
client.live_channels = {} # Contains twitch streams which are actively running (or have recently closed).
client.MAX_OFFLINE = 5 # Consecutive minutes of checks after which a stream is announced as offline.
client.admins = [83001199959216128]


@client.event
async def on_message(message):
  if not client.started:
    return
  elif message.author.id == client.user.id:
    return # DO NOT process our own messages
  elif client.user in message.mentions:
    pass # DO process messages which mention us, no matter where they're sent
  elif message.channel.type == discord.ChannelType.private:
    if message.channel.recipient.id not in client.admins:
      return # DO NOT process DMs from non-admins (For safety. It might be fine to process all DMs.)
  elif message.channel.id not in client.tracked_games:
    return # DO NOT process messages in unwatched channels

  def is_mention(word):
    # Match length according to discord.py
    return re.fullmatch('<(@!|@&|#)\d{17,20}>', word)
  # Since mentions can appear anywhere in the message, strip them out entirely for command processing.
  # User and channel mentions can still be accessed via message.mentions and message.channel_mentions
  args = [arg.strip() for arg in message.content.split(' ') if not is_mention(arg)]

  try:
    response = on_message_internal(message, args)
    if response:
      try:
        await message.add_reaction('🔇')
      except discord.errors.Forbidden: # Bot may or may not have permission to add reactions
        pass
      await message.channel.send(response)
  except AttributeError as e: # Usage errors
    await message.channel.send(str(e))
  except ValueError as e: # Actual errors
    logging.exception('Non-fatal command error')
    await message.channel.send(f'Error: {e}')


def on_message_internal(message, args):
  def get_channel():
    if len(message.channel_mentions) == 0:
      return message.channel
    if len(message.channel_mentions) == 1:
      return message.channel_mentions[0]
    if len(channel_mentions) > 1:
      raise ValueError('Response mentions more than one channel. Please mention at most one channel name at a time.')

  def assert_args(usage, *required_args, example=None):
    if any(arg == None for arg in required_args):
      error = f'Usage of {args[0]}): `{args[0]} {usage}`'
      if example:
        error += f'\nFor example: `{args[0]} {example}`'
      raise AttributeError(error)

  # Actual commands here
  def track_game(channel, game_name):
    assert_args('#channel Game Name', channel, game_name)
    generics.track_game(game_name, channel.id)
    return f'Will now announce runners of {game_name} in channel <#{channel.id}>.'
  def untrack_game(channel, game_name):
    assert_args('#channel Game Name', channel, game_name)
    database.remove_game(game_name)
    return f'No longer announcing runners of {game_name} in channel <#{channel.id}>.'
  def moderate_game(channel, game_name):
    assert_args('#channel Game Name', channel, game_name)
    generics.moderate_game(game_name, channel.id)
    return f'Will now announce newly submitted runs of {game_name} in channel <#{channel.id}>.'
  def unmoderate_game(channel, game_name):
    assert_args('#channel Game Name', channel, game_name)
    generics.unmoderate_game(game_name, channel.id)
    return f'No longer announcing newly submitted runs of {game_name} in channel <#{channel.id}>.'
  def restart():
    sys.exit(int(args[1]) if len(args) > 1 else 0)
  def git_update():
    output = subprocess.run(['git', 'pull', '--ff-only'], capture_output=True, text=True, cwd=Path(__file__).parent)
    return '```' + output.stdout + ('\n' if (output.stderr or output.stdout) else '') + output.stderr + '```'
  def send_last_lines(num_lines=None):
    subprocess.run([sys.executable, Path(__file__).with_name('send_error.py'), str(client.admins[0])])
  def link(twitch_username, src_username):
    assert_args('twitch_username src_username', twitch_username, src_username, example='jbzdarkid darkid')
    twitch_apis.get_user_id(twitch_username) # Will throw if there is any ambiguity about the twich username
    src_id = src_apis.search_src_user(src_username)
    database.add_user(twitch_username, src_id)
    return f'Successfully linked twitch user {twitch_username} to speedrun.com user {src_username}'
  def about():
    game = client.tracked_games.get(message.channel, 'this game')
    response = 'Speedrunning bot, created by darkid#1647.\n'
    response += f'The bot will search for twitch streams of {game}, then check to see if the given streamer is a speedrunner, then check to see if the speedrunner has a PB in {game}.\n'
    response += 'If so, it announces their stream in this channel.'
    return response
  def help():
    all_commands = [f'`{key}`' for key in commands]
    if message.author.id in client.admins:
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
  }
  commands = {
    '!link': lambda: link(*args[1:3]),
    '!about': lambda: about(),
    '!help': lambda: help(),
  }

  if len(args) == 0:
    return
  elif message.author.id in client.admins and args[0] in admin_commands:
    return admin_commands[args[0]]() # Allow admin versions of normal commands
  elif args[0] in commands:
    return commands[args[0]]()
  return None


@client.event
async def on_ready():
  if client.started: # This function may be called multiple times. We only should run once, though.
    return
  client.started = True

  logging.info(f'Logged in as {client.user.name} (id: {client.user.id})')

  p = Path(__file__).with_name('live_channels.txt')
  if p.exists():
    with p.open('r') as f:
      client.live_channels = json.load(f)

  while 1: # This while loop doesn't expect to return.
    for game_name, channel_id in database.get_all_games():
      if not client.get_channel(channel_id):
        logging.error(f'Could not locate channel {channel_id} for game {game_name}')
        continue
      client.tracked_games[channel_id] = game_name

    tracked_games = list(client.tracked_games.values())
    try:
      streams = list(generics.get_speedrunners_for_game2(tracked_games))
    except ConnectionError:
      logging.exception('Network connection error occurred while fetching streams')
      continue # The message will be posted next pass.

    for game_name, channel_id, in database.get_all_games():
      # For simplicity, we just filter this list down for each respective game.
      # It's not (that) costly, and it saves me having to refactor the core bot logic.
      game_streams = [stream for stream in streams if stream['game_name'] == game_name]
      logging.info(f'There are {len(game_streams)} streams of {game_name}')

      if channel := client.get_channel(channel_id):
        await on_parsed_streams(game_streams, game_name, channel)

    # Due to bot instability, we write this every loop, just in case we crash.
    with Path(__file__).with_name('live_channels.txt').open('w') as f:
      json.dump(client.live_channels, f)

    for game_name, src_game_id, discord_channel, last_update in database.get_all_moderated_games():
      channel = client.get_channel(discord_channel)
      if not channel:
        logging.error(f'Could not locate channel {discord_channel} for game {game_name}', file=sys.stderr)
        continue

      try:
        for content in generics.get_new_runs(game_name, src_game_id, last_update):
          await channel.send(content=content)
      except (discord.errors.HTTPException, ConnectionError):
        logging.execption('Network connection error occurred while fetching new runs')
        continue # The message will be posted next pass.

    await sleep(60)


@client.event
async def on_error(event, *args, **kwargs):
  import traceback
  traceback.print_exc(chain=False)
  logging.exception('Fatal error in program')
  sys.exit(1)


async def on_parsed_streams(streams, game, channel):
  def get_embed(stream):
    embed = discord.Embed(title=discord.utils.escape_markdown(stream['title']), url=stream['url'])
    # Add random data to the end of the image URL to force Discord to regenerate the preview.
    embed.set_image(url=stream['preview'] + '?' + uuid4().hex)
    return embed

  offline_streams = set(client.live_channels.keys())

  for stream in streams:
    name = discord.utils.escape_markdown(stream['name'])
    # A missing discord message is essentially equivalent to a new stream;
    # if we didn't send a message, then we weren't really live.
    if (name not in client.live_channels) or ('message' not in client.live_channels[name]):
      logging.info(f'Stream {name} started at {datetime.now().ctime()}')
      content = f'{name} is now doing runs of {game} at {stream["url"]}'
      try:
        message = await channel.send(content=content, embed=get_embed(stream))
      except discord.errors.HTTPException:
        logging.exception('Network error while announcing new stream')
        continue # The message will be posted next pass.
      stream['message'] = message.id
      stream['start'] = datetime.now().timestamp()
      stream['game'] = game
      stream['offline'] = 0
      client.live_channels[name] = stream
    else:
      stream = client.live_channels[name]
      offline_streams.remove(name)
      stream['offline'] = 0

      if 'game' in stream and game == stream['game']:
        logging.info(f'Stream {name} is still live at {datetime.now().ctime()}')
        # Always edit the message so that the preview updates.
        try:
          message = await channel.fetch_message(stream['message'])
          await message.edit(embed=get_embed(stream))
        except discord.errors.HTTPException:
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
    stream = client.live_channels[name]
    if stream['game'] != game:
      continue # Only parse offline streams for the current game.

    stream['offline'] = stream.get('offline', 0) + 1
    if stream['offline'] < client.MAX_OFFLINE:
      logging.info(f'Stream {name} has been offline for {stream["offline"]} consecutive checks')
      continue

    # Stream has been offline for (5) consecutive checks, close down the post
    logging.info(f'Stream {name} went offline at {datetime.now().ctime()}')
    duration_sec = int(datetime.now().timestamp() - client.live_channels[name]['start'])
    content = f'{name} went offline after {timedelta(seconds=duration_sec)}.\r\n'
    content += 'Watch their latest videos here: <' + stream['url'] + '/videos?filter=archives>'
    try:
      message = await channel.fetch_message(stream['message'])
      await message.edit(content=content, embed=None)
    except discord.errors.HTTPException:
      logging.exception('Network error while sending a stream offline')
      continue # The stream can go offline next pass. The offline count will increase, which is OK.
    del client.live_channels[name]


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
  # Set to info so discord/requests don't spam it too much.
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
        subprocess.run([sys.executable, Path(__file__).with_name('send_error.py'), str(client.admins[0])])
        logging.error('Subprocess crashed, waiting for 60 seconds before restarting')
        time.sleep(60) # Sleep after exit, to prevent losing my token.

  else:
    with Path(__file__).with_name('discord_token.txt').open() as f:
      token = f.read().strip()

    try:
      client.run(token, reconnect=True)
    except discord.errors.LoginFailure:
      logging.exception('Discord login failure')
      sys.exit(1)
