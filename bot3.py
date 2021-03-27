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
# TODO: Threading for user lookups will save a lot of time
# TODO: Consider merging initial fetch by using https://api.twitch.tv/helix/streams
#  Can specify multiple streams with ?game_id=foo&game_id=bar&game_id=baz
# TODO: Add tests for the database (using in-memory storage?)

# Globals
client = discord.Client()
client.started = False # Single-shot boolean to know if we've started up already
client.tracked_games = {} # Map of channel_id : game name
client.live_channels = {} # Contains twitch streams which are actively running (or have recently closed).

@client.event
async def on_message(message):
  if not client.started:
    return
  if message.author.id == client.user.id:
    return # Do not process our own messages

  # Only listen to posts in tracked channels or posts where we were explicitly mentioned.
  if message.channel.id not in client.tracked_games and client.user not in message.mentions:
    return

  args = message.content.split(' ')
  def is_mention(word):
    return re.fullmatch('<(@!|#)\d{18}>', word)
  args = [arg for arg in args if not is_mention(arg)]
  response = None

  try:
    if args[0] == '!track_game':
      if len(args) < 2:
        response = 'Usage of !track_game: `@SpeedrunBot !track_game Game Name` or `@SpeedrunBot !track_game #channel Game Name`\nE.g. `@SpeedrunBot !track_game The Witness` or `@SpeedrunBot !track_game #streams The Witness`'
      else:
        game_name = ' '.join(args[1:])
        if len(message.channel_mentions) > 1:
          response = 'Error: Response mentions more than one channel. Please provide only one channel name to `!track_game`'
        else:
          channel = message.channel_mentions[0] if (len(message.channel_mentions) == 1) else message.channel
          twitch_game_id, src_game_id = generics.track_game(game_name, channel.id)
          response = f'Will now announce runners of {game_name} in channel <#{channel.id}>.'

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
      response += 'The bot will search for twitch streams of {game}, then check to see if the given streamer is a speedrunner, then check to see if the speedrunner has a PB in this game.\n'
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
    for game_name, channel_id, in database.get_all_games():
      if not client.get_channel(channel_id):
        print(f'Error: Could not locate channel {channel_id} for game {game_name}', file=sys.stderr)
        continue
      client.tracked_games[channel_id] = game_name

      try:
        streams = generics.get_speedrunners_for_game(game_name)
      except ConnectionError as e:
        print(e, file=sys.stderr)
        continue # Network connection error occurred while fetching streams, take no action (i.e. do not increase offline count)

      if channel := client.get_channel(channel_id):
        await on_parsed_streams(streams, game_name, channel)

    # Due to bot instability, we write this every loop, just in case we crash.
    with Path(__file__).with_name('live_channels.txt').open('w') as f:
      json.dump(client.live_channels, f)

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
    if stream['offline'] < 5: # MAX_OFFLINE
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
        subprocess.run([sys.executable, __file__, 'subtask'] + sys.argv[1:], stdout=logfile)
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
