# Features
import ast
import asyncio
import discord
from html.parser import HTMLParser
import json
from pathlib import Path
import requests
import sys
# - Show stream start time
# - Show stream duration on close
# - Fix preview images not updating
# - Logging should include timestamps

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

  print(f'Logged in as {client.user.name} (id: {client.user.id})')

  with open(Path(__file__).parent / 'config.json', 'r') as f:
    config = ast.literal_eval(f.read())
  for game, channel in config.items():
    channel_data = client.get_channel(channel)
    if not channel_data:
      print(f'Error: Could not locate channel {channel}')
      continue

    game_data = requests.get(f'https://www.speedrun.com/api/v1/games/{game}').json()
    if 'status' in game_data:
      print(game_data['status'], game_data['message'])
      continue

    client.channels[game_data['data']['abbreviation']] = channel_data

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

  try:
    while 1:
      debug('Fetching streams')
      for game, channel in client.channels.items():
        url = f'https://www.speedrun.com/ajax_streams.php?game={game}&haspb=on'
        out = requests.get(url).text

        debug(f'Parsing streams for game {game}')
        p = StreamParser()
        p.feed(out)
        debug(f'Found {len(p.streams)} streams')

        debug('Sending live messages')
        await on_parsed_streams(p.streams, game, channel)

      with open(live_channels_file, 'w') as f:
        json.dump(live_channels, f)
      debug('Saved live channels')

      # Speedrun.com throttling limit is 100 requests/minute
      await asyncio.sleep(60)
  except:
    import traceback
    print(traceback.format_exc())
    pass
  await client.close()

# live_channels is a map of name: stream data
live_channels = {}
live_channels_file = Path(__file__).parent / 'live_channels.txt'

async def on_parsed_streams(streams, game, channel):
  global live_channels
  for stream in live_channels.values():
    stream['offline'] = True

  for stream in streams:
    name = stream['name']
    stream['offline'] = False

    if name not in live_channels:
      print('Stream started:', name)
      content = stream['name'] + ' just went live at ' + stream['url']
      embed = discord.Embed(title=stream['title'], url=stream['url'])
      embed.set_image(url=stream['preview'])
      message = await channel.send(content=content, embed=embed)
      stream['message'] = message.id
    elif 'message' not in live_channels[name]:
      print('No message for:', name)
      content = stream['name'] + ' just went live at ' + stream['url']
      embed = discord.Embed(title=stream['title'], url=stream['url'])
      embed.set_image(url=stream['preview'])
      message = await channel.send(content=content, embed=embed)
      stream['message'] = message.id
    elif stream['title'] != live_channels[name]['title']:
      debug('Title changed for:', name)
      message = await channel.fetch_message(live_channels[name]['message'])
      embed = discord.Embed(title=stream['title'], url=stream['url'])
      embed.set_image(url=stream['preview'])
      await message.edit(embed=embed)
      stream['message'] = message.id
    elif game != live_channels[name]['game']:
      debug('Stream changed games:', name)
      # Send the stream offline, then it will come back online with the new game.
      stream['offline'] = True
      stream['message'] = live_channels[name]['message']
    else:
      debug('Stream still live:', name)
      stream['message'] = live_channels[name]['message']

    stream['game'] = game
    live_channels[name] = stream

  for name in list(live_channels.keys()):
    stream = live_channels[name]
    if not stream['offline']:
      continue
    if stream['game'] != game:
      continue # Only parse offlines for streams of the current game.
    print('Stream now offline:', name)
    content = name + ' is now offline. See their latest videos here: <' + stream['url'] + '/videos?filter=archives>'
    message = await channel.fetch_message(stream['message'])
    await message.edit(content=content, embed=None)
    del live_channels[name]

if __name__ == '__main__':
  with open(Path(__file__).parent / 'token.txt', 'r') as f:
    token = f.read().strip()
  if '--debug' in sys.argv:
    def debug(*args, **kwargs):
      print(*args, **kwargs)
  client.run(token)