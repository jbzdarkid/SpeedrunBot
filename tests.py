import bot
import asyncio
import unittest
import inspect
from time import sleep

_id = 0
def get_id():
  global _id
  _id += 1
  return _id

class MockMessage:
  def __init__(self, id=get_id()):
    self.id = id

  def __str__(self):
    return f'Message({self.id})'

  async def edit(self, content=None, embed=None):
    print(f'Edited {self} with content "{content}" and embed {embed}')

class MockChannel:
  def __init__(self, id=get_id()):
    self.id = id

  async def send(self, content=None, embed=None):
    message = MockMessage()
    print(f'Sent {message} with content "{content}" and embed {embed} to channel {self.id}')
    return message

  async def fetch_message(self, id):
    return MockMessage(id)

class MockClient:
  def __init__(self):
    self.channels = {
      'game1': MockChannel(),
      'game2': MockChannel(),
    }
    self.MAX_OFFLINE = 1

def MockStream(name):
  return {
    'name': name,
    'url': 'twitch.tv/' + name,
    'title': name + '_title',
    'preview': 'preview.com/' + name,
    'game': 'game1',
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
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 0)

  async def testOneChannelGoesLive(self):
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

  async def testOneChannelGoesLiveThenOffline(self):
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 0)

  async def testChannelStillLiveOnStartup(self):
    stream = MockStream('bar')
    stream['message'] = MockMessage().id
    bot.live_channels = {stream['name']: stream}

    await bot.on_parsed_streams([MockStream('bar')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['bar']['message'] == stream['message'])

  async def testChannelChangesTitle(self):
    stream = MockStream('foo')
    await bot.on_parsed_streams([stream], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    stream['title'] = 'new_title'
    await bot.on_parsed_streams([stream], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['foo']['title'] == 'new_title')

  async def testChannelChangesGame(self):
    stream = MockStream('foo')

    await bot.on_parsed_streams([stream], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['foo']['game'] == 'game1')

    await bot.on_parsed_streams([stream], 'game2', bot.client.channels['game2'])
    self.assertTrue(len(bot.live_channels) == 0) # Not ideal, but the channels goes offline on both, briefly

    await bot.on_parsed_streams([stream], 'game2', bot.client.channels['game2'])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['foo']['game'] == 'game2')

  async def testMultipleChannelsMultipleGames(self):
    stream = MockStream('foo')
    stream2 = MockStream('bar')
    stream2['game'] = 'game2'

    await bot.on_parsed_streams([stream], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['foo']['game'] == 'game1')

    await bot.on_parsed_streams([stream2], 'game2', bot.client.channels['game2'])
    self.assertTrue(len(bot.live_channels) == 2)
    self.assertTrue(bot.live_channels['foo']['game'] == 'game1')
    self.assertTrue(bot.live_channels['bar']['game'] == 'game2')

    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['bar']['game'] == 'game2')

    await bot.on_parsed_streams([], 'game2', bot.client.channels['game2'])
    self.assertTrue(len(bot.live_channels) == 0)

  async def testLiveDuration(self):
    # Hook -- parsing stdout to confirm that the offline message notes the duration
    from io import TextIOWrapper, BytesIO
    import sys
    sys.stdout = TextIOWrapper(BytesIO(), sys.stdout.encoding)

    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    sleep(2.5)

    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 0)

    # Unhook
    sys.stdout.seek(0)
    out = sys.stdout.read()
    sys.stdout = sys.__stdout__
    self.assertTrue('went offline after 0:00:02' in out)

  async def testGoesOffline(self):
    bot.client.MAX_OFFLINE = 5
    # Stream goes live
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    # Stream still live after 4 consecutive 'offline' checks
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    # Stream finally offline after 5th consecutive
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 0)

    # Stream stays offline (duh)
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 0)

  async def testStreamDowntime(self):
    bot.client.MAX_OFFLINE = 5
    # Stream goes live
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    # Stream still live after 4 consecutive 'offline' checks
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    # Stream comes back online -- still live
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    # Stream almost goes down again
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

if __name__ == '__main__':
  bot.discord.Embed = MockEmbed
  tests = Tests()

  loop = asyncio.get_event_loop()
  def l(method):
    return inspect.ismethod(method) and method.__name__.startswith('test')
  for test in inspect.getmembers(tests, l):
    # Test setup
    print('---', test[0])
    bot.client = MockClient()
    bot.live_channels = {}

    # Test body
    loop.run_until_complete(test[1]())

    # Test teardown
    pass
  loop.close()