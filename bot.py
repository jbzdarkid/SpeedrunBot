from ast import literal_eval
from datetime import timedelta
import discord
from html.parser import HTMLParser
import json
from pathlib import Path
import requests
from sys import argv
from time import time, ctime
from uuid import uuid4
# TODO:
# - Add stream start time to message -> Hard, because time is not client-side, so it will be wrong, for most people.

def debug(*args, **kwargs):
  pass

class StreamParser(HTMLParser):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.streams = []

  def handle_starttag(self, tag, attrs):
    if tag == 'div' and len(attrs) == 1:
      if attrs[0][0] == 'class' and 'listcell' in attrs[0][1]:
        self.streams.append({}) # New stream

    elif tag == 'img' and len(attrs) == 3:
      if attrs[0] == ('class', 'stream-preview'):
        assert(attrs[1][0] == 'src')
        self.streams[-1]['preview'] = attrs[1][1]
    elif tag == 'a' and len(attrs) == 3:
      if attrs[0] == ('target', '_blank'):
        assert(attrs[1][0] == 'href')
        self.streams[-1]['url'] = attrs[1][1]
        self.streams[-1]['name'] = discord.utils.escape_markdown(attrs[1][1].rsplit('/', 1)[1])
        assert(attrs[2][0] == 'title')
        self.streams[-1]['title'] = discord.utils.escape_markdown(attrs[2][1])

client = discord.Client()
client.started = False
client.channels = {}

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

    game_data = requests.get(f'https://www.speedrun.com/api/v1/games/{game}').json()
    if 'status' in game_data:
      print(game_data['status'], game_data['message'])
      continue

    client.channels[game_data['data']['abbreviation']] = channel_id

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

  debug('Fetching streams')
  for game, channel_id in client.channels.items():
    url = f'https://www.speedrun.com/ajax_streams.php?game={game}&haspb=on'
    try:
      out = requests.get(url, timeout=60).text
    except requests.exceptions.Timeout:
      continue

    debug(f'Parsing streams for game {game}')
    p = StreamParser()
    p.feed(out)
    debug(f'Found {len(p.streams)} streams')

    debug(f'Sending live messages for game {game}')
    # Fetch a fresh channel object every time (???)
    channel = client.get_channel(channel_id)
    await on_parsed_streams(p.streams, game, channel)

  with open(live_channels_file, 'w') as f:
    json.dump(live_channels, f)
  debug('Saved live channels')

  await client.close()

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
  for stream in live_channels.values():
    stream['offline'] = True

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

    if 'game' in stream and game == stream['game']:
      debug(f'Stream {name} is still live at {ctime()}')
      # Always edit the message so that the preview updates.
      message = await channel.fetch_message(message_id)
      await message.edit(embed=get_embed(stream))
      stream['offline'] = False
    else:
      debug(f'Stream {name} changed games at {ctime()}')
      # Send the stream offline, then it will come back online with the new game,
      # to be announced in another channel.
      stream['offline'] = True
      stream['game'] = game

  for name in list(live_channels.keys()):
    stream = live_channels[name]
    if not stream['offline']:
      continue
    if stream['game'] != game:
      continue # Only parse offlines for streams of the current game.
    print(f'Stream {name} went offline at {ctime()}')
    duration_sec = int(time() - live_channels[name]['start'])
    content = f'{name} went offline after {timedelta(seconds=duration_sec)}.\r\n'
    content += 'Watch their latest videos here: <' + stream['url'] + '/videos?filter=archives>'
    message = await channel.fetch_message(message_id)
    await message.edit(content=content, embed=None)
    del live_channels[name]

if __name__ == '__main__':
  with open(Path(__file__).parent / 'token.txt', 'r') as f:
    token = f.read().strip()
  if '--debug' in argv:
    def debug(*args, **kwargs):
      print(*args, **kwargs)

  if 'subtask' not in argv:
    import subprocess
    import time
    import sys
    while 1:
      subprocess.run([sys.executable, __file__, 'subtask'] + argv)
      # Speedrun.com throttling limit is 100 requests/minute
      time.sleep(60)
  else:
    client.run(token, reconnect=True)

