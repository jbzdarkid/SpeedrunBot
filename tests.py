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
    print('---', inspect.currentframe().f_code.co_name)
    bot.live_channels = {}
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 0)

  async def testOneChannelGoesLive(self):
    print('---', inspect.currentframe().f_code.co_name)
    bot.live_channels = {}
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

  async def testOneChannelGoesLiveThenOffline(self):
    print('---', inspect.currentframe().f_code.co_name)
    bot.live_channels = {}
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 0)

  async def testChannelStillLiveOnStartup(self):
    print('---', inspect.currentframe().f_code.co_name)
    stream = MockStream('bar')
    stream['message'] = MockMessage().id
    bot.live_channels = {stream['name']: stream}

    await bot.on_parsed_streams([MockStream('bar')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['bar']['message'] == stream['message'])

  async def testChannelChangesTitle(self):
    print('---', inspect.currentframe().f_code.co_name)
    bot.live_channels = {}
    stream = MockStream('foo')
    await bot.on_parsed_streams([stream], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    stream['title'] = 'new_title'
    await bot.on_parsed_streams([stream], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)
    self.assertTrue(bot.live_channels['foo']['title'] == 'new_title')

  async def testChannelChangesGame(self):
    print('---', inspect.currentframe().f_code.co_name)
    bot.live_channels = {}
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
    print('---', inspect.currentframe().f_code.co_name)
    bot.live_channels = {}
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
    print('---', inspect.currentframe().f_code.co_name)
    bot.live_channels = {}
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 1)

    sleep(2.5)

    await bot.on_parsed_streams([], 'game1', bot.client.channels['game1'])
    self.assertTrue(len(bot.live_channels) == 0)
    # We don't hold on to messages, so it's not easy to assert that time is being printed.
    # Just look at stdout, for now.

if __name__ == '__main__':
  bot.client = MockClient()
  bot.discord.Embed = MockEmbed
  global once
  once = True
  tests = Tests()

  loop = asyncio.get_event_loop()
  def l(method):
    return inspect.ismethod(method) and method.__name__.startswith('test')
  for test in inspect.getmembers(tests, l):
    loop.run_until_complete(test[1]())
  loop.close()