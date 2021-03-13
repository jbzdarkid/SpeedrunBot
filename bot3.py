import discord
import json
from asyncio import sleep
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import database
import generics

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
  if message.channel.id not in client.tracked_games:
    return # Only listen for commands in channels we're assigned to
  handle_command(message.channel, message.content.split(' '))


# TODO: !force_pb ? What do I use for the user ID? SRC ID is hard to know, but usernames suck to handle.
async def handle_command(channel, args):
  response = None
  if args[0] == '!link':
    if len(args) != 3:
      response = 'Usage of !link: `!link twitch_username src_username`\nE.g. `!link jbzdarkid darkid`'
    else:
      users = src_apis.search_src_user(args[2])
      if len(users) == 0:
        response = f'Error: No speedrun.com users found matching {args[2]}'
      elif len(users) == 1:
        username, src_id = users[0]
        database.add_user(args[1], src_id)
        response = f'Successfully linked twitch user {args[1]} to speedrun.com user {username}'
      elif len(users) > 1:
        # TODO: What if the target username is a subset of the exact username? E.g. !link foo bar
        # but there's "bar" and "barbell" as SRC users. We *can't* be more specific!
        message = f'Error: Found {len(users)} possible matches for {args[2]}. Please input one of these speedrun.com users:'
        for username, _ in users:
          message += f'\n{username}'
        response = message

  elif args[0] == '!about':
    game = client.tracked_games.get(channel, 'this game')
    # You might want to change this username if you fork the code, too.
    response = 'Speedrunning bot, created by darkid#1647.\n'
    response += 'The bot will search for twitch streams of {game}, then check to see if the given streamer is a speedrunner, then check to see if the speedrunner has a PB in this game.\n'
    response += 'If so, it announces their stream in this channel.'

  elif args[0] == '!help':
    response = 'Available commands: `!link`, `!about`, `!help`'

  if response:
    await channel.send(response)


@client.event
async def on_ready():
  if client.started: # This function may be called multiple times. We only should run setup once, though.
    return
  client.started = True

  debug(f'Logged in as {client.user.name} (id: {client.user.id})')

  for game_name, _, __, channel_id, in database.get_all_games():
    if not client.get_channel(channel_id):
      print(f'Error: Could not locate channel {channel_id} for game {game_name}')
      continue
    client.tracked_games[channel_id] = game_name

  if len(client.tracked_games) == 0:
    print('Error: Found no valid channels')
    await client.close()
    return

  with Path(__file__).with_name('live_channels2.txt').open() as f:
    client.live_channels = json.load(f)

  while 1: # This while loop doesn't expect to return.
    for channel_id, game in client.tracked_games.items():
      streams = get_speedrunners_for_game(game)

      if channel := client.get_channel(channel_id)
        await on_parsed_streams(streams, game, channel)

    # Due to bot instability, we write this every loop, just in case we crash.
    with Path(__file__).with_name('live_channels2.txt').open('w') as f:
      json.dump(client.live_channels, f)

    await sleep(60)


async def on_parsed_streams(streams, game, channel):
  def get_embed(stream):
    embed = discord.Embed(title=stream['title'], url=stream['url'])
    # Add random data to the end of the image URL to force Discord to regenerate it.
    embed.set_image(url=stream['preview'] + '?' + uuid4().hex)
    return embed

  offline_streams = set(client.live_channels.keys())

  for stream in streams:
    name = stream['name']
    # A missing discord message is essentially equivalent to a new stream;
    # if we didn't send a message, then we weren't really live.
    if (name not in client.live_channels) or ('message' not in client.live_channels[name]):
      print(f'Stream {name} started at {datetime.now().ctime()}')
      content = stream['name'] + ' just went live at ' + stream['url']
      message = await channel.send(content=content, embed=get_embed(stream))
      stream['message'] = message.id
      stream['start'] = datetime.now().timestamp()
      stream['game'] = game
      client.live_channels[name] = stream
    else:
      stream = client.live_channels[name]
      offline_streams.remove(name)
      stream['offline'] = 0 # Number of consecutive times observed as offline
      debug(f'Stream {name} is not offline')

    if 'game' in stream and game == stream['game']:
      debug(f'Stream {name} is still live at {datetime.now().ctime()}')
      # Always edit the message so that the preview updates.
      message = await channel.fetch_message(stream['message'])
      await message.edit(embed=get_embed(stream))
    else:
      debug(f'Stream {name} changed games at {datetime.now().ctime()}')
      # Send the stream offline, then it will come back online with the new game,
      # to be announced in another channel.
      offline_streams.add(name)
      stream['offline'] = 9999
      stream['game'] = game

  for name in offline_streams:
    stream = client.live_channels[name]
    if stream['game'] != game:
      continue # Only parse offlines for streams of the current game.

    if 'offline' not in stream:
      stream['offline'] = 1
    else:
      stream['offline'] += 1
    debug(f'Stream {name} has been offline for {stream["offline"]} consecutive checks')

    if stream['offline'] < 5: # MAX_OFFLINE
      continue

    # Stream has been offline for (5) consecutive checks, close down the post
    print(f'Stream {name} went offline at {ctime()}')
    duration_sec = int(time() - client.live_channels[name]['start'])
    content = f'{name} went offline after {timedelta(seconds=duration_sec)}.\r\n'
    content += 'Watch their latest videos here: <' + stream['url'] + '/videos?filter=archives>'
    message = await channel.fetch_message(stream['message'])
    await message.edit(content=content, embed=None)
    del client.live_channels[name]


if __name__ == '__main__':
  import sys
  if 'subtask' not in sys.argv:
    import subprocess
    while 1:
      print(f'Starting subtask at {datetime.now()}')
      subprocess.run([sys.executable, __file__, 'subtask'] + sys.argv[1:])

  else:
    with Path(__file__).with_name('discord_token.txt').open() as f:
      token = f.read().strip()

    client.run(token, reconnect=True)
