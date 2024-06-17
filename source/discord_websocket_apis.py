import asyncio
import json
import logging
import websockets
from pathlib import Path
from random import random
from threading import Thread

from .utils import seconds_since_epoch
from . import commands, discord_apis, exceptions

DISPATCH = 0
HEARTBEAT = 1
IDENTIFY = 2
PRESENCE_UPDATE = 3
VOICE_STATE_UPDATE = 4
RESUME = 6
RECONNECT = 7
REQUEST_GUILD_MEMBERS = 8
INVALID_SESSION = 9
HELLO = 10
HEARTBEAT_ACK = 11

# Valid callbacks: (although callbacks are somewhat deprecated)
# on_message, on_direct_message, on_reaction, on_message_edit, on_message_delete

class WebSocket():
  def __init__(self):
    self.callbacks = {} # Hooks which can be registered to handle various discord events. Must be registered before calling run().
    self.connected = False # Indicates whether or not the websocket is connected. If false, we should not send messages and should exit the loop.
    self.user = None # The user object of this bot. Currently unused.
    self.session_id = None # Indicates whether or not we have an active session, used to resume if the connection drops.
    self.sequence = -1 # Indicates the last recieved message in the current session. Meaningless if no session is active.
    self.got_heartbeat_ack = False # Indicates whether or not we've recieved a HEARTBEAT_ACK since the last heartbeat.
    self.resume_gateway_url = None # Custom URL from discord to use when restarting the connection


  def run(self):
    asyncio.get_event_loop().run_until_complete(self.run_async())


  async def run_async(self):
    while 1: # This loop does not exit naturally
      # Clients are limited to 1000 IDENTIFY calls to the websocket in a 24-hour period.
      # https://discord.com/developers/docs/topics/gateway#identifying
      # For simplicity, I just use this limit as our generic reconnection rate,
      # so that no class of failure can throttle the client and invalidate the discord_token.
      logging.info('Sleeping to avoid throttling limits')
      await asyncio.sleep(24 * 60 * 60 / 1000)

      websocket = None
      try:
        websocket = await self.connect()
      except websockets.exceptions.WebSocketException:
        logging.exception('Unable to open a websocket connection due to a websocket error')
      except OSError:
        logging.exception('Unable to open a websocket connection due to a socket error')
      except Exception:
        logging.exception('Unable to open a websocket for an unknown reason')

      logging.info('Successfully connected the websocket')

      # Message loop: Wait for messages, interrupting for heartbeats.
      while self.connected:
        until_next_heartbeat = self.next_heartbeat - seconds_since_epoch()
        if until_next_heartbeat <= 0:
          await self.heartbeat(websocket)
          continue

        if msg := await self.get_message(websocket, timeout=until_next_heartbeat):
          await self.handle_message(msg, websocket)

      # Message loop exited, so self.connected = False
      if websocket:
        await websocket.close(1012) # 1012: Service restart. Discord asks us not to use 1000 and 1001.


  def get_token(self):
    with Path(__file__).with_name('discord_token.txt').open() as f:
      # Although we could save this as a class member, this allows the user to update their token without restarting the bot.
      return f.read().strip()


  async def connect(self):
    connection_url = self.resume_gateway_url if self.session_id else 'wss://gateway.discord.gg' # Only use the resume URL for resuming an existing session
    websocket = await websockets.connect(connection_url + '?v=10&encoding=json', ping_timeout=None)
    hello = await self.get_message(websocket)
    if not hello:
      return

    # Upon receiving the Hello event, your app should wait heartbeat_interval * jitter where jitter is any random value between 0 and 1
    # https://discord.com/developers/docs/topics/gateway#heartbeat-interval
    self.heartbeat_interval = json.loads(hello)['d']['heartbeat_interval'] / 1000 # Value is in millis
    random_startup = self.heartbeat_interval * random()
    logging.info(f'Connecting in {random_startup} seconds')
    await asyncio.sleep(random_startup)

    self.connected = True
    # Since this is our first heartbeat, we pretend we've already gotten an ack to avoid immediately disconnecting.
    self.got_heartbeat_ack = True
    await self.heartbeat(websocket)

    logging.info('Successfully connected and sent initial heartbeat')

    # Unlike the initial connection, your app does not need to re-Identify when Resuming.
    # https://discord.com/developers/docs/topics/gateway#preparing-to-resume
    if self.session_id:
      logging.info(f'Resuming {self.session_id} at {self.sequence}')
      resume = {
        'token': self.get_token(),
        'session_id': self.session_id,
        'seq': self.sequence,
      }
      self.session_id = None # If something goes wrong during the resume, we should not try again.

      try:
        await self.send_message(websocket, RESUME, resume)
        return websocket
      except Exception:
        logging.exception('Failed to resume the connection')

    # https://discord.com/developers/docs/topics/gateway#gateway-intents
    intents = 0
    if ('on_message' in self.callbacks
        or 'on_message_edit' in self.callbacks
        or 'on_message_delete' in self.callbacks):
      intents |= (1 << 9) # GUID_MESSAGES
    if 'on_reaction' in self.callbacks:
      intents |= (1 << 10) # GUILD_MESSAGE_REACTIONS
    if 'on_direct_message' in self.callbacks:
      intents |= (1 << 12) # DIRECT_MESSAGES

    # https://discord.com/developers/docs/topics/gateway#identifying
    identify = {
      'token': self.get_token(),
      'intents': intents,
      'properties': {
        'os': 'windows',
        'browser': 'speedrunbot-jbzdarkid',
        'device': 'speedrunbot-jbzdarkid',
      },
      'presence': {
        'activities': [{
          'type': 4,
          'emoji': 'exclamation',
          'state': 'Type !help for information',
        }],
      }
    }
    await self.send_message(websocket, IDENTIFY, identify)

    return websocket


  async def heartbeat(self, websocket):
    if not self.got_heartbeat_ack:
      # https://discord.com/developers/docs/topics/gateway#heartbeat-interval-example-heartbeat-ack
      logging.error('Disconnecting because heartbeat did not get an ack since last heartbeat')
      self.connected = False
      return

    await self.send_message(websocket, HEARTBEAT, self.sequence)
    self.next_heartbeat = seconds_since_epoch() + self.heartbeat_interval
    self.got_heartbeat_ack = False


  async def get_message(self, websocket, timeout=None):
    try:
      msg = await asyncio.wait_for(websocket.recv(), timeout=timeout)
      return msg
    except (asyncio.TimeoutError, asyncio.CancelledError):
      # These are perfectly normal responses from asyncio when the timeout expires.
      # We expect to recieve these often because messages are rarer than heartbeats.
      return None
    except websockets.exceptions.ConnectionClosedError:
      logging.exception('Disconnecting due to connection error on get')
      self.connected = False
      return None
    except websockets.exceptions.WebSocketException:
      logging.exception('Disconnecting due to generic websocket error on get')
      self.connected = False
      return None


  async def send_message(self, websocket, op, data):
    try:
      await websocket.send(json.dumps({'op': op, 'd': data}))
    except websockets.exceptions.WebSocketException:
      logging.exception('Disconnecting due to generic websocket error on send')
      self.connected = False


  async def handle_message(self, msg, websocket):
    msg = json.loads(msg)
    if msg['op'] == DISPATCH:
      if msg['t'] == 'READY':
        # https://discord.com/developers/docs/topics/gateway-events#ready-ready-event-fields
        self.user = msg['d']['user']
        logging.info('Signed in as ' + self.user['username'])
        self.resume_gateway_url = msg['d']['resume_gateway_url']
        if not self.session_id:
          self.session_id = msg['d']['session_id']
          self.sequence = msg['s']
          logging.info(f'Starting new session {self.session_id} at {self.sequence}')
        return

      # Aside from READY, all messages will be part of our current sequence.
      self.sequence = msg['s']
      target = None
      if msg['t'] == 'MESSAGE_CREATE':
        if 'guild_id' in msg['d']: # Direct messages do not have a guild_id
          target = self.callbacks.get('on_message')
        else:
          target = self.callbacks.get('on_direct_message')
      elif msg['t'] == 'MESSAGE_REACTION_ADD':
        target = self.callbacks.get('on_reaction')
      elif msg['t'] == 'MESSAGE_UPDATE':
        target = self.callbacks.get('on_message_edit')
      elif msg['t'] == 'MESSAGE_DELETE':
        target = self.callbacks.get('on_message_delete')
      elif msg['t'] == 'GUILD_MEMBER_UPDATE':
        logging.info(f'Member update: {msg}')
      elif msg['t'] == 'INTERACTION_CREATE':
        # There is only a single line in the docs that mentions this message type.
        # https://discord.com/developers/docs/interactions/receiving-and-responding#receiving-an-interaction
        target = self.on_interaction
      elif msg['t'] == 'RESUMED':
        logging.info(f'Successfully resumed session {self.session_id}')
      else:
        logging.error('Cannot handle message type ' + msg['t'])

      if target:
        Thread(target=target, args=(msg['d'],)).start()

    elif msg['op'] == HEARTBEAT:
      await self.heartbeat(websocket)
    elif msg['op'] == RECONNECT:
      # Similar to INVALID_SESSION with 'd' = true, disconnect but keep the session_id so that we can resume.
      self.connected = False
    elif msg['op'] == INVALID_SESSION:
      # Disconnect so that we can resume or re-identify.
      self.connected = False
      if not msg['d']: # Session is not resumable
        self.session_id = None
    elif msg['op'] == HEARTBEAT_ACK:
      self.got_heartbeat_ack = True
    else:
      logging.error('Cannot handle message opcode ' + str(msg['op']))

  def on_interaction(self, data):
    if data['type'] != 2: # APPLICATION_COMMAND
      logging.error(f'Cannot handle interaction type {data["type"]}\n{data}')
      return

    response = None
    command_name = None

    try:
      # We must ack within 3 seconds or Discord considers the command to have failed.
      # We then have 15 minutes to reply before the token expires.
      # https://discord.com/developers/docs/interactions/receiving-and-responding#responding-to-an-interaction
      # TODO: Somehow getting double-ack from this. IDK, man.
      # discord_apis.acknowledge_interaction(data['id'], data['token'])
      print('<264>', data)

      # Channel ID is a relatively common piece of information but I don't always want to expose it to the caller.
      # As such I'm just adding it into every command, and the value can be overridden if it's an actual argument.
      kwargs = {'channel': data['channel_id']}
      for option in data['data'].get('options', []):
        kwargs[option['name']] = option['value']

      command_name = data['data']['name']
      command = commands.CALLBACKS[command_name]
      response = command(**kwargs)
    except exceptions.NetworkError as e:
      response = f'Failed due to network error, please try again: {e}'
      logging.exception('interaction-network')
    except Exception as e:
      response = f'Failed due to an unknown error, please contact darkid: {e}'
      logging.exception(f'General error during {command_name}')

    if not response:
      response = 'Nothing to say...'
    try:
      discord_apis.reply_to_interaction(data['id'], data['token'], response)
    except Exception as e:
      logging.exception(f'Failed to send reply to {command_name}')
