import importlib
import inspect
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from unittest.mock import patch

import bot3 as bot
from source import database

_id = 0
def get_id():
  global _id
  _id += 1
  return _id

class MockMessage:
  def __init__(self, content, embed):
    self.id = get_id()
    self.content = content
    self.embed = embed

  def __str__(self):
    return f'Message(id={self.id})'

  def __repr__(self):
    return f'Message("{self.content}", "{self.embed}")'

  def __getitem__(self, key):
    return self.__getattribute__(key)

class MockChannel:
  def __init__(self):
    self.id = get_id()
    self.messages = {}

  def send(self, content=None, embed=None):
    message = MockMessage(content, embed)
    self.messages[message.id] = message
    return message

class MockClient:
  def __init__(self):
    self.channels = {}

  def new_channel(self):
    channel = MockChannel()
    self.channels[channel.id] = channel
    return channel

  def find_message(self, message_id):
    for channel in self.channels.values():
      if message := channel.messages.get(message_id):
        return message
    return None

def MockStream(name):
  return {
    'name': name,
    'url': 'twitch.tv/' + name,
    'title': name + '_title',
    'preview': 'preview.com/' + name,
    'game': 'game1',
  }

class BotTests:
  def on_parsed_streams(self, *streams):
    self.mock_gsfg.return_value = list(streams)
    bot.announce_live_channels()
    return list(database.get_announced_streams())

  def mock_head(self, url):
    expires = datetime.now() + timedelta(seconds=1) # IRL this would be 5 minutes but tests are supposed to be fast.
    headers = {'expires': datetime.strftime(expires, '%a, %d %b %Y %H:%M:%S UTC')}
    return (302, headers)

  def mock_send_message(self, channel_id, content, embed=None):
    channel = bot.client.channels[channel_id]
    message = channel.send(content, embed)

    print(f'Sent {message} with content "{content}" and embed {embed} to channel {channel.id}')
    return message

  def mock_edit_message(self, channel_id, message_id, content=None, embed=None):
    channel = bot.client.channels[channel_id]
    message = channel.messages[message_id]
    if content:
      message.content = content
    if embed:
      message.embed = embed
    channel.messages[message_id] = message

    # Solely for logging purposes
    if content:
      content = content.replace('\n', '\\n')
    else:
      content = '(unchanged)'
    print(f'Edited {message} with content "{content}" and embed {embed} to channel {channel.id}')
    return True


  def testNoChannels(self):
    streams = self.on_parsed_streams()
    assert len(streams) == 0

  def testOneChannelGoesLive(self):
    streams = self.on_parsed_streams(MockStream('foo'))
    assert len(streams) == 1

  def testOneChannelGoesLiveThenOffline(self):
    streams = self.on_parsed_streams(MockStream('foo'))
    assert len(streams) == 1
    sleep(1.1)
    streams = self.on_parsed_streams()
    assert len(streams) == 0

  def testChannelStillLiveOnStartup(self):
    channel = bot.client.new_channel()
    database.add_game('game2', 'game2', 'game2', channel.id)
    message = channel.send('initial message')
    database.add_announced_stream(
      name='bar',
      game='game2',
      title='bar_title',
      url='twitch.tv/bar',
      preview='preview.com/bar',
      channel_id=channel.id,
      message_id=message.id,
      preview_expires=datetime.now().timestamp(),
    )
    assert len(list(database.get_announced_streams())) == 1

    stream = MockStream('bar')
    stream['game'] = 'game2'
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1
    assert streams[0]['message_id'] == message.id
    assert message.content == 'initial message' # Messages are not edited while the stream is still live

  def testChannelChangesGame(self):
    database.add_game('game2', 'game2', 'game2', bot.client.new_channel().id)
    stream = MockStream('foo')

    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1
    assert streams[0]['game'] == 'game1'
    game1_message_id = streams[0]['message_id']

    stream['game'] = 'game2'
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1
    assert streams[0]['game'] == 'game2'

    game1_message = bot.client.find_message(game1_message_id)
    assert 'offline' in game1_message['content']

  def testChannelChangesTitle(self):
    stream = MockStream('foo')
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1
    message = bot.client.find_message(streams[0]['message_id'])
    assert message['embed']['title'] == 'foo\\_title'

    stream['title'] = 'new_title'
    streams = self.on_parsed_streams(stream)

    assert message['embed']['title'] == 'new\\_title'

  def testEscapement(self):
    streams = self.on_parsed_streams(MockStream('underscore_'))
    message = bot.client.find_message(streams[0]['message_id'])
    sleep(1.1)
    streams = self.on_parsed_streams()

    # underscore\_ went offline after 0:00:01.\nWatch their latest videos here: <twitch.tv/underscore_/videos?filter=archives>
    assert r'underscore\_ went offline' in message.content
    assert r'twitch.tv/underscore_/videos' in message.content

"""

  def testNoSrl(self):
    stream = MockStream('foo')
    stream['title'] = 'Any% runs of game1'
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1

    stream['title'] = 'Randomizer runs of game1 [nosrl]'
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 0

  def testMultipleChannelsMultipleGames(self):
    stream = MockStream('foo')
    stream2 = MockStream('bar')
    stream2['game'] = 'game2'

    self.on_parsed_streams([stream], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['foo']['game'] == 'game1')

    self.on_parsed_streams([stream2], 'game2', bot.client.tracked_games['game2'])
    self.assertTrue(len(bot.client.live_channels) == 2)
    self.assertTrue(bot.client.live_channels['foo']['game'] == 'game1')
    self.assertTrue(bot.client.live_channels['bar']['game'] == 'game2')

    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)
    self.assertTrue(bot.client.live_channels['bar']['game'] == 'game2')

    self.on_parsed_streams([], 'game2', bot.client.tracked_games['game2'])
    self.assertTrue(len(bot.client.live_channels) == 0)

  def testGoesOffline(self):
    bot.client.MAX_OFFLINE = 5
    # Stream goes live
    self.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream still live after 4 consecutive 'offline' checks
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream finally offline after 5th consecutive
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 0)

    # Stream stays offline (duh)
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 0)

  def testStreamDowntime(self):
    bot.client.MAX_OFFLINE = 5
    # Stream goes live
    self.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream still live after 4 consecutive 'offline' checks
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream comes back online -- still live
    self.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    # Stream almost goes down again
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

class BotTestsWithStdout():
  def testLiveDuration(self, get_stdout):
    self.on_parsed_streams([MockStream('foo')], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 1)

    sleep(2.5) # Sleeping for the assert below about "went offline after [duration]

    self.on_parsed_streams([], 'game1', bot.client.tracked_games['game1'])
    self.assertTrue(len(bot.client.live_channels) == 0)

    stdout = get_stdout()
    self.assertTrue('went offline after 0:00:02' in stdout)


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
"""

if __name__ == '__main__':
  info_stream = logging.StreamHandler(sys.stdout)
  info_stream.setLevel(logging.DEBUG)
  info_stream.setFormatter(logging.Formatter('%(message)s'))

  error_stream = logging.StreamHandler(sys.stderr)
  error_stream.setLevel(logging.ERROR)
  error_stream.setFormatter(logging.Formatter('Error: %(message)s'))
  logging.basicConfig(level=logging.DEBUG, handlers=[info_stream, error_stream])


  tests = BotTests()
  with (patch('source.generics.get_speedrunners_for_game') as mock_gsfg,
        patch('source.src_apis.make_request') as mock_http1,
        patch('source.discord_apis.make_request') as mock_http2,
        patch('source.twitch_apis.make_request') as mock_http3,
        patch('source.twitch_apis.make_head_request', new=tests.mock_head),
        patch('source.discord_apis.edit_message_ids', new=tests.mock_edit_message),
        patch('source.discord_apis.send_message_ids', new=tests.mock_send_message)):
    tests.mock_gsfg = mock_gsfg
    # tests.mock_http = [mock_http1, mock_http2, mock_http3]

    def is_test(method):
      return inspect.ismethod(method) and method.__name__.startswith('test')
    tests = list(inspect.getmembers(tests, is_test))
    tests.sort(key=lambda func: func[1].__code__.co_firstlineno)

    for test in tests:
      if len(sys.argv) > 1: # Requested specific test(s)
        if test[0] not in sys.argv[1:]:
          continue

      # Test setup
      bot.client = MockClient()

      ## Reload the database to keep tests clean
      database.conn.close()
      Path('source/database.db').unlink(missing_ok=True)
      importlib.reload(database)
      database.add_game('game1', 'game1', 'game1', bot.client.new_channel().id)

      # Run test
      print('---', test[0], 'started')
      try:
        test[1]()
      except:
        print('!!!', test[0], 'failed:')
        import traceback
        traceback.print_exc()
        break
      else:
        print('===', test[0], 'passed')
