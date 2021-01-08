import discord
import json
import requests
from ast import literal_eval
from asyncio import sleep
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from sys import argv
from time import time, ctime
from uuid import uuid4
from bot2 import get_speedrunners_for_game
# TODO:
# - Add a test for 'what if a live message got deleted'

def debug(*args, **kwargs):
  if '--debug' in argv:
    print(*args, **kwargs)

client = discord.Client()
client.started = False
client.channels = {}
client.MAX_OFFLINE = 5

@client.event
async def on_ready():
  if client.started: # @Hack: Properly deal with disconnection / reconnection
    await client.close()
    return
  client.started = True

  debug(f'Logged in as {client.user.name} (id: {client.user.id})')

  with open(Path(__file__).parent / 'config.json', 'r') as f:
    config = literal_eval(f.read())
  for game, channel_id in config.items():
    if not client.get_channel(channel_id):
      print(f'Error: Could not locate channel {channel_id}')
      continue

    client.channels[game] = channel_id

  if len(client.channels) == 0:
    print('Error: Found no valid channels')
    await client.close()
    return

  global live_channels
  try:
    with open(live_channels_file) as f:
      live_channels = json.load(f)
    debug(f'Loaded {len(live_channels)} live channels')
  except FileNotFoundError:
    debug('live_channels.txt does not exist')
  except json.decoder.JSONDecodeError:
    debug('live_channels.txt was not parsable')

  while 1:
    debug('Fetching streams')
    for game, channel_id in client.channels.items():
      debug(f'Fetching streams for game {game}')
      streams = list(get_speedrunners_for_game(game))
      debug(f'Found {len(streams)} streams')

      debug(f'Sending live messages for game {game}')
      # Fetch a fresh channel object every time (???)
      channel = client.get_channel(channel_id)
      if channel:
        await on_parsed_streams(streams, game, channel)

    with open(live_channels_file, 'w') as f:
      json.dump(live_channels, f)
    debug('Saved live channels')

    # Speedrun.com throttling limit is 100 requests/minute
    await sleep(60)

# live_channels is a map of name: stream data
live_channels = {}
live_channels_file = Path(__file__).parent / 'live_channels.txt'

def get_embed(stream):
  embed = discord.Embed(title=stream['title'], url=stream['url'])
  # Add random data to the end of the image URL to force Discord to regenerate it.
  embed.set_image(url=stream['preview'] + '?' + uuid4().hex)
  return embed

async def on_parsed_streams(streams, game, channel):
  global live_channels
  offline_streams = set(live_channels.keys())

  for stream in streams:
    name = stream['name']
    # A missing discord message is essentially equivalent to a new stream;
    # if we didn't send a message, then we weren't really live.
    if (name not in live_channels) or ('message' not in live_channels[name]):
      print(f'Stream {name} started at {ctime()}')
      content = stream['name'] + ' just went live at ' + stream['url']
      message = await channel.send(content=content, embed=get_embed(stream))
      stream['message'] = message.id
      stream['start'] = time()
      stream['game'] = game
      live_channels[name] = stream
    else:
      stream = live_channels[name]
      offline_streams.remove(name)
      stream['offline'] = 0 # Number of consecutive times observed as offline
      debug(f'Stream {name} is not offline')

    if 'game' in stream and game == stream['game']:
      debug(f'Stream {name} is still live at {ctime()}')
      # Always edit the message so that the preview updates.
      message = await channel.fetch_message(stream['message'])
      await message.edit(embed=get_embed(stream))
    else:
      debug(f'Stream {name} changed games at {ctime()}')
      # Send the stream offline, then it will come back online with the new game,
      # to be announced in another channel.
      offline_streams.add(name)
      stream['offline'] = 9999
      stream['game'] = game

  for name in offline_streams:
    stream = live_channels[name]
    if stream['game'] != game:
      continue # Only parse offlines for streams of the current game.

    if 'offline' not in stream:
      stream['offline'] = 1
    else:
      stream['offline'] += 1
    debug(f'Stream {name} has been offline for {stream["offline"]} consecutive checks')

    if stream['offline'] < client.MAX_OFFLINE:
      continue

    # Stream has been offline for (5) consecutive checks, close down the post
    print(f'Stream {name} went offline at {ctime()}')
    duration_sec = int(time() - live_channels[name]['start'])
    content = f'{name} went offline after {timedelta(seconds=duration_sec)}.\r\n'
    content += 'Watch their latest videos here: <' + stream['url'] + '/videos?filter=archives>'
    message = await channel.fetch_message(stream['message'])
    await message.edit(content=content, embed=None)
    del live_channels[name]

if __name__ == '__main__':
  with open(Path(__file__).parent / 'discord_token.txt', 'r') as f:
    token = f.read().strip()

  if 'subtask' not in argv:
    import subprocess
    import sys
    while 1:
      subprocess.run([sys.executable, __file__, 'subtask'] + argv)
      # Speedrun.com throttling limit is 100 requests/minute
      sleep(60)
  else:
    client.run(token, reconnect=True)

