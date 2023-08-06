import importlib
import inspect
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from unittest.mock import patch

import bot3 as bot
from source import database, src_apis, exceptions

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
    self.mock_get_live_streams.return_value = list(streams)
    bot.announce_live_channels()
    return list(database.get_announced_streams())

  def mock_head(self, url):
    expires = datetime.now() + timedelta(milliseconds=100) # IRL this would be 5 minutes but tests are supposed to be fast.
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

  def testTwoGamesOneChannel(self):
    channel = bot.client.new_channel()
    database.add_game('game2_name', 'game2_twitch_id', 'game2_src_id', channel.id)
    database.add_game('game3_name', 'game3_twitch_id', 'game3_src_id', channel.id)
    
    stream = MockStream('foo')
    stream['game'] = 'game2_name'
    
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1

    stream2 = MockStream('bar')
    stream2['game'] = 'game3_name'
    
    streams = self.on_parsed_streams(stream, stream2)
    assert len(streams) == 2
    # Shrug? It's not reproing.
    raise


  """
  def testGoesOffline(self):
    streams = self.on_parsed_streams(MockStream('foo'))
    assert len(streams) == 1
    message = bot.client.find_message(streams[0]['message_id'])
    assert 'is now doing runs of game1' in message.content

    # Before waiting, stream should still be within the 'possibly still live' period
    streams = self.on_parsed_streams()
    assert len(streams) == 1
    assert 'is now doing runs of game1' in message.content

    sleep(.2) # Offline time is 100 millis in tests, sleep until it's done
    streams = self.on_parsed_streams()
    assert len(streams) == 0
    assert 'has gone offline' in message.content

  def testStreamDowntime(self):
    stream = MockStream('foo')
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1

    # Stream goes down briefly (or the API lies), but we're within the grace period
    streams = self.on_parsed_streams()
    assert len(streams) == 1

    # Stream comes back online
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1

    # Stream goes down again
    streams = self.on_parsed_streams()
    assert len(streams) == 1

    # Stream comes back online again
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1

    sleep(.2) # Offline time is 100 millis in tests, sleep until it's done

    # Stream goes down again
    streams = self.on_parsed_streams()
    assert len(streams) == 1
  """

  def testEscapement(self):
    streams = self.on_parsed_streams(MockStream('underscore_'))
    message = bot.client.find_message(streams[0]['message_id'])
    assert r'underscore\_ is now doing runs of game1' in message.content # Usernames need escaping
    assert r'underscore\_\_title' in message.embed['title'] # Titles need escaping
    assert r'twitch.tv/underscore_' in message.embed['url'] # URLs do not

    sleep(.2) # Offline time is 100 millis in tests, sleep until it's done
    streams = self.on_parsed_streams()

    # underscore\_ went offline after 0:00:01.\nWatch their latest videos here: <twitch.tv/underscore_/videos?filter=archives>
    assert r'underscore\_ went offline' in message.content # Username needs escaping
    assert r'<twitch.tv/underscore_/videos?filter=archives>' in message.content # URL does not

  def testNoSrl(self):
    stream = MockStream('foo')
    stream['title'] = 'Any% runs of game1'
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1

    stream['title'] = 'Randomizer runs of game1 [nosrl]'
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 0

  def testMultipleChannelsMultipleGames(self):
    database.add_game('game2', 'game2', 'game2', bot.client.new_channel().id)

    stream = MockStream('foo')
    streams = self.on_parsed_streams(stream)
    assert len(streams) == 1
    assert streams[0]['game'] == 'game1'

    stream2 = MockStream('bar')
    stream2['game'] = 'game2'
    streams = self.on_parsed_streams(stream, stream2)
    assert len(streams) == 2
    assert streams[0]['game'] == 'game1'
    assert streams[1]['game'] == 'game2'

    streams = self.on_parsed_streams(stream2)
    assert len(streams) == 1
    assert streams[0]['game'] == 'game2'

    streams = self.on_parsed_streams()
    assert len(streams) == 0

  # Note that SRC should not ever return a name which completely mismatches. I hope.
  def testAmbiguousGameId(self):
    self.mock_http['src'].return_value = {'data': [
      {'names': {'international': 'foobar'}, 'id': 0},
    ]}

    assert src_apis.get_game_id('foo') == 0
    assert src_apis.get_game_id('bar') == 0
    assert src_apis.get_game_id('foobar') == 0

    self.mock_http['src'].return_value = {'data': [
      {'names': {'international': 'foobar'}, 'id': 0},
      {'names': {'international': 'barfoo'}, 'id': 1},
    ]}

    try:
      src_apis.get_game_id('foo')
      assert False
    except exceptions.CommandError as e:
      # It's ambiguous, so we error to the user.
      assert 'foobar' in str(e)
      assert 'barfoo' in str(e)

    # Prefers an exact match when possible
    self.mock_http['src'].return_value = {'data': [
      {'names': {'international': 'foobar'}, 'id': 0},
      {'names': {'international': 'foo'},    'id': 1},
      {'names': {'international': 'barfoo'}, 'id': 2},
    ]}

    assert src_apis.get_game_id('foo') == 1
    assert src_apis.get_game_id('foobar') == 0
    assert src_apis.get_game_id('barfoo') == 2

if __name__ == '__main__':
  info_stream = logging.StreamHandler(sys.stdout)
  info_stream.setLevel(logging.DEBUG)
  info_stream.setFormatter(logging.Formatter('%(message)s'))

  error_stream = logging.StreamHandler(sys.stderr)
  error_stream.setLevel(logging.ERROR)
  error_stream.setFormatter(logging.Formatter('Error: %(message)s'))
  logging.basicConfig(level=logging.DEBUG, handlers=[info_stream, error_stream])

  # Eh. I should probably be mocking the make_request call. Whatever.
  def mock_src_id(twitch_username):
    return f'{twitch_username}_src'
  def mock_runner_runs_game(twitch_username, src_id, src_game_id):
    return True

  tests = BotTests()
  with (patch('source.twitch_apis.get_live_streams') as mock_get_live_streams,
        patch('source.src_apis.make_request') as mock_src_http,
        patch('source.discord_apis.make_request') as mock_discord_http,
        patch('source.twitch_apis.make_request') as mock_twitch_http,
        patch('source.twitch_apis.make_head_request', new=tests.mock_head),
        patch('source.discord_apis.edit_message_ids', new=tests.mock_edit_message),
        patch('source.discord_apis.send_message_ids', new=tests.mock_send_message),
        patch('source.src_apis.get_src_id', new=mock_src_id),
        patch('source.src_apis.runner_runs_game', new=mock_runner_runs_game)):
    tests.mock_get_live_streams = mock_get_live_streams
    tests.mock_http = {
      'src': mock_src_http,
      'discord': mock_discord_http,
      'twitch': mock_twitch_http,
    }
    
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
      except Exception:
        print('!!!', test[0], 'failed:')
        import traceback
        traceback.print_exc()
        break
      else:
        print('===', test[0], 'passed')
    else:
      print('\nAll tests passed')
