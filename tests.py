import bot
import asyncio
import unittest

_id = 0
def get_id():
  global _id
  _id += 1
  return _id

class MockMessage:
  def __init__(self, id=None):
    if id:
      self.id = id
    else:
      self.id = get_id()

  def __str__(self):
    return f'Message({self.id})'

  async def edit(self, content=None, embed=None):
    print(f'Edited {self} with content {content} and embed {embed}')

class MockChannel:
  async def send(self, content=None):
    message = MockMessage()
    print(f'Sent {message} with content "{content}"')
    return message

  async def fetch_message(self, id):
    return MockMessage(id)

class MockClient:
  def __init__(self):
    self.channel = MockChannel()

def MockStream(name):
  return {
    'name': name,
    'url': 'twitch.tv/' + name,
    'title': name + '_title',
    'preview': 'preview.com/' + name
  }

class MockEmbed():
  def __init__(self, title=None, url=None):
    self.title = title
    self.url = url

  def __str__(self):
    return f'Embed(title={self.title} url={self.url} image={self.image})'

  def set_image(self, url=None):
    self.image = url

class Tests(unittest.TestCase):
  async def testNoChannels(self):
    bot.live_channels = {}
    await bot.on_parsed_streams([])
    self.assertTrue(len(bot.live_channels) == 0)

  async def testOneChannelGoesLive(self):
    bot.live_channels = {}
    await bot.on_parsed_streams([MockStream('foo')])
    self.assertTrue(len(bot.live_channels) == 1)

  async def testOneChannelGoesLiveThenOffline(self):
    bot.live_channels = {}
    await bot.on_parsed_streams([MockStream('foo')])
    self.assertTrue(len(bot.live_channels) == 1)
    await bot.on_parsed_streams([])
    self.assertTrue(len(bot.live_channels) == 0)

  async def testChannelStillLiveOnStartup(self):
    stream = MockStream('bar')
    stream['message'] = MockMessage().id
    bot.live_channels = {stream['name']: stream}

    await bot.on_parsed_streams([MockStream('bar')])
    self.assertTrue(len(bot.live_channels) == 1)
    print(bot.live_channels['bar'])
    self.assertTrue(bot.live_channels['bar']['message'] == stream['message'])

  async def testChannelChangesTitle(self):
    bot.live_channels = {}
    stream = MockStream('foo')
    await bot.on_parsed_streams([stream])
    self.assertTrue(len(bot.live_channels) == 1)

    stream['title'] = 'new_title'
    await bot.on_parsed_streams([stream])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['foo']['title'] == 'new_title')

if __name__ == '__main__':
  bot._debug = True
  bot.client = MockClient()
  bot.discord.Embed = MockEmbed
  tests = Tests()

  loop = asyncio.get_event_loop()
  print('---')
  loop.run_until_complete(tests.testNoChannels())
  print('---')
  loop.run_until_complete(tests.testOneChannelGoesLive())
  print('---')
  loop.run_until_complete(tests.testOneChannelGoesLiveThenOffline())
  print('---')
  loop.run_until_complete(tests.testChannelStillLiveOnStartup())
  print('---')
  loop.run_until_complete(tests.testChannelChangesTitle())
  print('---')
  loop.close()