import discord
import json
import re
import sys
from asyncio import sleep
from datetime import datetime, timedelta
from pathlib import Path
from requests.exceptions import ConnectionError
from uuid import uuid4

from source import database, generics, twitch_apis, src_apis

# TODO: !force_pb ? What do I use for the user ID? SRC ID is hard to know, but usernames suck to handle.
# TODO: [nosrl] (and associated tests)
# TODO: Add a test for 'what if a live message got deleted'
# TODO: Threading for user lookups will save a lot of time, especially as the list of games grows
# TODO: Add tests for the database (using in-memory storage?)
#  Can mock the network via make_request.py
# TODO: Try to improve performance by creating a thread for each runner
# TODO: Consider refactoring the core bot logic so that we don't need to filter streams by game
# TODO: Discord is not renaming embeds? Or, I'm not changing the embed title correctly on edits.
# TODO: Stop using select (*) wrong

# Globals
client = discord.Client()
client.started = False # Single-shot boolean to know if we've started up already
client.tracked_games = {} # Map of channel_id : game name
client.live_channels = {} # Contains twitch streams which are actively running (or have recently closed).
client.MAX_OFFLINE = 5 # Consecutive minutes of checks after which a stream is announced as offline.

@client.event
async def on_message(message):
  if not client.started:
    return
  if message.author.id == client.user.id:
    return # Do not process our own messages

  # Only listen to posts in tracked channels or posts where we were explicitly mentioned.
  if client.user in message.mentions:
    await message.add_reaction('🔇')
  elif message.channel.id not in client.tracked_games:
    return

  args = message.content.split(' ')
  def is_mention(word):
    return re.fullmatch('<(@!|#)\d{18}>', word)
  args = [arg for arg in args if not is_mention(arg)]

  if len(args) == 0:
    return

  print(args)

  response = None
  try:
    if message.author.id == 83001199959216128: # Authorized commands
      if args[0] == '!track_game':
        if len(args) < 2:
          response = 'Usage of !track_game: `@SpeedrunBot !track_game Game Name` or `@SpeedrunBot !track_game #channel Game Name`\nE.g. `@SpeedrunBot !track_game The Witness` or `@SpeedrunBot !track_game #streams The Witness`'
        else:
          game_name = ' '.join(args[1:])
          if len(message.channel_mentions) > 1:
            response = 'Error: Response mentions more than one channel. Please provide only one channel name to `!track_game`'
          else:
            channel = message.channel_mentions[0] if (len(message.channel_mentions) == 1) else message.channel
            generics.track_game(game_name, channel.id)
            response = f'Will now announce runners of {game_name} in channel <#{channel.id}>.'

      elif args[0] == '!untrack_game':
        if len(args) < 2:
          response = 'Usage of !untrack_game: `!untrack_game Game Name`\nE.g. `!untrack_game The Witness`'
        else:
          game_name = ' '.join(args[1:])
          channel = message.channel
          database.remove_game(game_name)
          response = f'No longer announcing runners of {game_name} in channel <#{channel.id}>'

      elif args[0] == '!moderate_game':
        if len(args) < 2:
          response = 'Usage of !moderate_game: `@SpeedrunBot !moderate_game Game Name` or `@SpeedrunBot !moderate_game #channel Game Name`\nE.g. `@SpeedrunBot !moderate_game The Witness` or `@SpeedrunBot !moderate_game #streams The Witness`'
        else:
          game_name = ' '.join(args[1:])
          if len(message.channel_mentions) > 1:
            response = 'Error: Response mentions more than one channel. Please provide only one channel name to `!moderate_game`'
          else:
            channel = message.channel_mentions[0] if (len(message.channel_mentions) == 1) else message.channel
            generics.moderate_game(game_name, channel.id)
            response = f'Will now announce newly submitted runs of {game_name} in channel <#{channel.id}>.'

      elif args[0] == '!unmoderate_game':
        print(len(args))
        if len(args) < 2:
          response = 'Usage of !unmoderate_game: `!unmoderate_game Game Name`\nE.g. `!unmoderate_game The Witness`'
        else:
          game_name = ' '.join(args[1:])
          channel = message.channel
          database.unmoderate_game(game_name)
          response = f'No longer announcing newly submitted runs of {game_name} in channel <#{channel.id}>'

      elif args[0] == '!restart':
        sys.exit(int(args[1]) if len(args) > 1 else 0)

    elif args[0] == '!link':
      if len(args) != 3:
        response = 'Usage of !link: `!link twitch_username src_username`\nE.g. `!link jbzdarkid darkid`'
      else:
        twitch_apis.get_user_id(args[1]) # Will throw if there is
        src_id = src_apis.search_src_user(args[2])
        database.add_user(args[1], src_id)
        response = f'Successfully linked twitch user {args[1]} to speedrun.com user {args[2]}'

    elif args[0] == '!about':
      game = client.tracked_games.get(message.channel, 'this game')
      # You might want to change this username if you fork the code, too.
      response = 'Speedrunning bot, created by darkid#1647.\n'
      response += f'The bot will search for twitch streams of {game}, then check to see if the given streamer is a speedrunner, then check to see if the speedrunner has a PB in {game}.\n'
      response += 'If so, it announces their stream in this channel.'

    elif args[0] == '!help':
      response = 'Available commands: `!link`, `!about`, `!help`'

  except ValueError as e:
    response = f'Error: {e}'

  if response:
    await message.channel.send(response)


@client.event
async def on_ready():
  if client.started: # This function may be called multiple times. We only should run once, though.
    return
  client.started = True

  print(f'Logged in as {client.user.name} (id: {client.user.id})')

  p = Path(__file__).with_name('live_channels.txt')
  if p.exists():
    with p.open('r') as f:
      client.live_channels = json.load(f)

  while 1: # This while loop doesn't expect to return.
    for game_name, channel_id in database.get_all_games():
      if not client.get_channel(channel_id):
        print(f'Error: Could not locate channel {channel_id} for game {game_name}', file=sys.stderr)
        continue
      client.tracked_games[channel_id] = game_name

    tracked_games = list(client.tracked_games.values())
    try:
      streams = list(generics.get_speedrunners_for_game2(tracked_games))
    except ConnectionError as e:
      print(e, file=sys.stderr)
      continue # Network connection error occurred while fetching streams, take no action (i.e. do not increase offline count)

    for game_name, channel_id, in database.get_all_games():
      # For simplicity, we just filter this list down for each respective game.
      # It's not (that) costly, and it saves me having to refactor the core bot logic.
      game_streams = [stream for stream in streams if stream['game_name'] == game_name]
      print(f'There are {len(game_streams)} streams of {game_name}')

      if channel := client.get_channel(channel_id):
        await on_parsed_streams(game_streams, game_name, channel)

    # Due to bot instability, we write this every loop, just in case we crash.
    with Path(__file__).with_name('live_channels.txt').open('w') as f:
      json.dump(client.live_channels, f)

    for game_name, src_game_id, discord_channel, last_update in database.get_all_moderated_games():
      channel = client.get_channel(discord_channel)
      if not channel:
        print(f'Error: Could not locate channel {discord_channel} for game {game_name}', file=sys.stderr)
        continue

      try:
        for content in generics.get_new_runs(src_game_id, last_update):
          await channel.send(content=content)
        database.update_game_moderation_time(game_name)
      except discord.errors.HTTPException:
        continue # The message will be posted next pass.

    await sleep(60)


@client.event
async def on_error(event, *args, **kwargs):
  import traceback
  traceback.print_exc(chain=False)
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
      print(f'Stream {name} started at {datetime.now().ctime()}')
      content = f'{name} is now doing runs of {game} at {stream["url"]}'
      try:
        message = await channel.send(content=content, embed=get_embed(stream))
      except discord.errors.HTTPException:
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
        print(f'Stream {name} is still live at {datetime.now().ctime()}')
        # Always edit the message so that the preview updates.
        try:
          message = await channel.fetch_message(stream['message'])
          await message.edit(embed=get_embed(stream))
        except discord.errors.HTTPException:
          continue # The message will be edited next pass.
      else:
        print(f'Stream {name} changed games at {datetime.now().ctime()}')
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
      print(f'Stream {name} has been offline for {stream["offline"]} consecutive checks')
      continue

    # Stream has been offline for (5) consecutive checks, close down the post
    print(f'Stream {name} went offline at {datetime.now().ctime()}')
    duration_sec = int(datetime.now().timestamp() - client.live_channels[name]['start'])
    content = f'{name} went offline after {timedelta(seconds=duration_sec)}.\r\n'
    content += 'Watch their latest videos here: <' + stream['url'] + '/videos?filter=archives>'
    try:
      message = await channel.fetch_message(stream['message'])
      await message.edit(content=content, embed=None)
    except discord.errors.HTTPException:
      continue # The stream can go offline next pass. The offline count will increase, which is OK.
    del client.live_channels[name]


if __name__ == '__main__':
  if 'subtask' not in sys.argv:
    import subprocess
    import time
    # If the file doesn't exist, it's created (a)
    # Data is read and written as bytes (b)
    with Path(__file__).with_name('out.log').open('ab') as logfile:
      while 1:
        print(f'Starting subtask at {datetime.now()}')
        output = subprocess.run([sys.executable, __file__, 'subtask'] + sys.argv[1:], stdout=logfile)
        if output.returncode != 0:
          print('Subprocess crashed, waiting for 60 seconds before restarting')
          time.sleep(60) # Sleep after exit, to prevent losing my token.

  else:
    sys.stdout.reconfigure(encoding='utf-8') # Inelegant, but fixes utf-8 twitch usernames
    with Path(__file__).with_name('discord_token.txt').open() as f:
      token = f.read().strip()

    try:
      client.run(token, reconnect=True)
    except discord.errors.LoginFailure as e:
      print(e)
      sys.exit(1)
