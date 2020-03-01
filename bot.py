import discord
import config
import requests
import asyncio
from html.parser import HTMLParser
import json

# TODO: Test this.

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
client.channel = None

@client.event
async def on_ready():
  if client.started: # @Hack: Properly deal with disconnection / reconnection
    await client.close()
    return
  client.started = True

  print(f'Logged in as {client.user.name} (id: {client.user.id})')

  client.channel = client.get_channel(config.target_channel_id)
  if not client.channel:
    print(f'Error: Could not locate channel {config.target_channel_id}')
    await client.close()
    return

  global live_channels
  try:
    with open('live_channels.txt') as f:
      live_channels = json.load(f)
    print(f'Loaded {len(live_channels)} live channels')
  except FileNotFoundError:
    print('live_channels.txt does not exist')
  except json.decoder.JSONDecodeError:
    print('live_channels.txt was not parsable')

  while 1:
    print('Fetching streams')
    url = 'https://www.speedrun.com/ajax_streams.php?game=' + config.game
    url += '&haspb=on'
    out = requests.get(url).text

    print('Parsing streams')
    p = StreamParser()
    p.feed(out)
    print('Found', len(p.streams), 'streams')

    print('Sending live messages')
    await on_parsed_streams(p.streams)

    with open('live_channels.txt', 'w') as f:
      json.dump(live_channels, f)
    print('Saved live channels')

    # Speedrun.com throttling limit is 100 requests/minute
    await asyncio.sleep(60)
  await client.close()

# live_channels is a map of name: stream data
live_channels = {}

async def on_parsed_streams(streams):
  global live_channels
  for stream in live_channels.values():
    stream['offline'] = True

  for stream in streams:
    name = stream['name']
    if name not in live_channels:
      print('Stream started:', name)
      message = await client.channel.send(stream['name'] + ' just went live at ' + stream['url'])
    elif 'message' not in live_channels[name]:
      print('No message for', name)
      message = await client.channel.send(stream['name'] + ' just went live at ' + stream['url'])
    else:
      print('Stream still live:', name)
      message = await client.channel.fetch_message(live_channels[name]['message'])

    embed = discord.Embed(title=stream['title'], url=stream['url'])
    embed.set_image(url=stream['preview'])
    await message.edit(embed=embed)
    stream['message'] = message.id
    stream['offline'] = False
    live_channels[name] = stream

  for name in list(live_channels.keys()):
    stream = live_channels[name]
    if not stream['offline']:
      continue
    print('Stream now offline:', name)
    content = name + ' is now offline. See their latest videos here: <' + stream['url'] + '/videos?filter=archives>'
    message = await client.channel.fetch_message(stream['message'])
    await message.edit(content=content, embed=None)
    del live_channels[name]

if __name__ == '__main__':
  client.run(config.token)