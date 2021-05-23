import asyncio
import unittest
import inspect
import bot3 as bot
from time import sleep
from unittest.mock import patch

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
    self.started = False
    self.tracked_games = {
      'game1': MockChannel(),
      'game2': MockChannel(),
    }
    self.live_channels = {}
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

class BotTests(unittest.TestCase):
  async def testNoChannels(self):
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 0)

  async def testOneChannelGoesLive(self):
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

  async def testOneChannelGoesLiveThenOffline(self):
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 0)

  async def testChannelStillLiveOnStartup(self):
    stream = MockStream('bar')
    stream['message'] = MockMessage().id
    bot.client.live_channels = {stream['name']: stream}

    await bot.on_parsed_streams([MockStream('bar')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['bar']['message'] == stream['message'])

  async def testChannelChangesGame(self):
    stream = MockStream('foo')

    await bot.on_parsed_streams([stream], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['foo']['game'] == 'game1')

    await bot.on_parsed_streams([stream], 'game2', bot.client.tracked_games['game2'])
    self.assertTrue(len(bot.client.live_channels) == 0) # Not ideal, but the channels goes offline on both, briefly

    await bot.on_parsed_streams([stream], 'game2', bot.client.tracked_games['game2'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['foo']['game'] == 'game2')

  async def testMultipleChannelsMultipleGames(self):
    stream = MockStream('foo')
    stream2 = MockStream('bar')
    stream2['game'] = 'game2'

    await bot.on_parsed_streams([stream], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['foo']['game'] == 'game1')

    await bot.on_parsed_streams([stream2], 'game2', bot.client.tracked_games['game2'])
    self.assertTrue(len(bot.client.live_channels) == 2)
    self.assertTrue(bot.client.live_channels['foo']['game'] == 'game1')
    self.assertTrue(bot.client.live_channels['bar']['game'] == 'game2')

    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['bar']['game'] == 'game2')

    await bot.on_parsed_streams([], 'game2', bot.client.tracked_games['game2'])
    self.assertTrue(len(bot.client.live_channels) == 0)

  async def testGoesOffline(self):
    bot.client.MAX_OFFLINE = 5
    # Stream goes live
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream still live after 4 consecutive 'offline' checks
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream finally offline after 5th consecutive
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 0)

    # Stream stays offline (duh)
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 0)

  async def testStreamDowntime(self):
    bot.client.MAX_OFFLINE = 5
    # Stream goes live
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream still live after 4 consecutive 'offline' checks
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream comes back online -- still live
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream almost goes down again
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

class BotTestsWithStdout(unittest.TestCase):
  async def testLiveDuration(self, get_stdout):
    await bot.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    sleep(2.5) # Sleeping for the assert below about "went offline after [duration]

    await bot.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 0)

    stdout = get_stdout()
    self.assertTrue('went offline after 0:00:02' in stdout)

  async def testChannelChangesTitle(self, get_stdout):
    stream = MockStream('foo')
    await bot.on_parsed_streams([stream], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['foo']['title'] == 'foo_title')

    print('===midpoint===')

    stream['title'] = 'new_title'
    await bot.on_parsed_streams([stream], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['foo']['title'] == 'new_title')

    stdout = get_stdout()
    stdout = stdout.split('===midpoint===')
    self.assertTrue('foo\\_title' in stdout[0])
    self.assertTrue('new\\_title' in stdout[1])


class SrcTests(unittest.TestCase):
  def test_ambiguous_game_id(self, mock_http):
    mock_http.return_value = {'data': [
      {'names': {'twitch': 'foobar'}, 'id': 0},
      {'names': {'twitch': 'foo'},    'id': 1},
      {'names': {'twitch': 'barfoo'}, 'id': 2},
    ]}

    from source import src_apis
    game_id = src_apis.get_game_id('foo')
    self.assertTrue(game_id == 1)

if __name__ == '__main__':
  bot.discord.Embed = MockEmbed

  loop = asyncio.get_event_loop()
  def is_test(method):
    return inspect.ismethod(method) and method.__name__.startswith('test')

  for test in inspect.getmembers(BotTests(), is_test):
    # Test setup
    print('---', test[0], 'started')
    bot.client = MockClient()
    bot.client.live_channels = {}

    # Test body
    loop.run_until_complete(test[1]())

    # Test teardown
    print('===', test[0], 'passed')

  for test in inspect.getmembers(BotTestsWithStdout(), is_test):
    # Test setup
    print('---', test[0], 'started')
    bot.client = MockClient()
    bot.client.live_channels = {}

    # Hook -- parsing stdout to confirm that the offline message notes the duration
    from io import TextIOWrapper, BytesIO
    import sys
    sys.stdout = TextIOWrapper(BytesIO(), sys.stdout.encoding)

    # Unhook, called within tests so they can assert on data
    def get_stdout():
      sys.stdout.seek(0)
      out = sys.stdout.read()
      sys.stdout = sys.__stdout__
      print(out, end='')
      return out

    # Test body
    loop.run_until_complete(test[1](get_stdout))

    # Test teardown
    print('===', test[0], 'passed')

  loop.close()


  for test in inspect.getmembers(SrcTests(), is_test):
    # Test setup
    print('---', test[0], 'started')

    # Test body
    with patch('source.src_apis.get_json') as mock_http:
      test[1](mock_http)

    # Test teardown
    print('===', test[0], 'passed')

