import asyncio
import json
import logging
import websockets
from datetime import datetime, timedelta
from pathlib import Path
from random import random
from threading import Thread

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


# Valid callbacks:
# on_message, on_direct_message, on_reaction, on_message_edit, on_message_delete

class WebSocket():
  def __init__(self):
    self.callbacks = {} # Hooks which can be registered to handle various discord events. Must be registered before calling run().
    self.connected = False # Indicates whether or not the websocket is connected. If false, we should not send messages and should exit the loop.
    self.session_id = None # Indicates whether or not we have an active session, used to resume if the connection drops.
    self.sequence = None # Indicates the last recieved message in the current session. Meaningless if no session is active.
    self.got_heartbeat_ack = False # Indicates whether or not we've recieved a HEARTBEAT_ACK since the last heartbeat.


  def run(self):
    asyncio.get_event_loop().run_until_complete(self.run_async())


  async def run_async(self):
    while 1: # This loop does not exit naturally
      websocket = await self.connect()

      # Main loop: Wait for messages, interrupting for heartbeats.
      while self.connected:
        until_next_heartbeat = self.next_heartbeat - datetime.now()
        if until_next_heartbeat.total_seconds() <= 0:
          await self.heartbeat(websocket)
          continue

        msg = await self.get_message(websocket, timeout=until_next_heartbeat.total_seconds())
        if msg:
          await self.handle_message(msg, websocket)

      await websocket.close(1001)


  def get_token(self):
    with Path(__file__).with_name('discord_token.txt').open() as f:
      # Although we could save this as a class member, this allows the user to update their token without restarting the bot.
      return f.read().strip()


  async def connect(self):
    while not self.connected:
      try:
        websocket = await websockets.connect('wss://gateway.discord.gg/?v=9&encoding=json')
      except websockets.exceptions.WebSocketException as e:
        logging.exception('Unable to open a websocket connection')
        await asyncio.sleep(10)
        continue

      hello = await self.get_message(websocket)
      if hello:
        self.heartbeat_interval = timedelta(milliseconds=json.loads(hello)['d']['heartbeat_interval'])
        self.connected = True # Set connected early, since the connection may drop in between now and the heartbeat

        # https://discord.com/developers/docs/topics/gateway#heartbeating
        random_startup = self.heartbeat_interval.total_seconds() * random()
        logging.info(f'Connecting in {random_startup} seconds')
        await asyncio.sleep(random_startup)

        # Since this is our first heartbeat, we pretend we've already gotten an ack to avoid immediately disconnecting.
        self.got_hearbeat_ack = True
        await self.heartbeat(websocket)

      if not self.connected: # Internet may have gone down while waiting for hello / initial sleep
        await websocket.close(1001)
        continue

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
        '$os': 'windows',
        '$browser': 'speedrunbot-jbzdarkid',
        '$device': 'speedrunbot-jbzdarkid',
      }
    }
    await self.send_message(websocket, IDENTIFY, identify)
    # The READY response will be handled in handle_message, as it may get interrupted by a heartbeat.

    return websocket


  async def heartbeat(self, websocket):
    if not self.got_heartbeat_ack:
      # https://discord.com/developers/docs/topics/gateway#heartbeating-example-gateway-heartbeat-ack
      logging.error(f'Disconnecting because heartbeat did not get an ack since last heartbeat')
      self.connected = False

    await self.send_message(websocket, HEARTBEAT, self.sequence)
    self.next_heartbeat = datetime.now() + self.heartbeat_interval
    self.got_heartbeat_ack = False


  async def get_message(self, websocket, timeout=None):
    try:
      return await asyncio.wait_for(websocket.recv(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
      return None
    except websockets.exceptions.ConnectionClosedError as e:
      logging.exception('Disconnecting due to connection error on get')
      self.connected = False
      return None
    except websockets.exceptions.WebSocketException as e:
      logging.exception('Disconnecting due to generic websocket error on get')
      self.connected = False
      return None


  async def send_message(self, websocket, op, data):
    try:
      await websocket.send(json.dumps({'op': op, 'd': data}))
    except websockets.exceptions.WebSocketException as e:
      logging.exception('Disconnecting due to generic websocket error on send')
      self.connected = False


  async def handle_message(self, msg, websocket):
    msg = json.loads(msg)
    if msg['op'] == DISPATCH:
      if msg['t'] == 'READY':
        self.user = msg['d']['user']
        logging.info('Signed in as ' + self.user['username'])
        # TODO: This is a bit of an encapsulation break. We should really have a separate system which handles IDENTIFY/READY/RESUME,
        # which would also reduce the restart time in the INVALID_SESSION case below.
        # But, I don't want to duplicate the handle_message function, and it's not really designed to return anything.
        if self.session_id: # Attempt to resume the previous session, if we had one
          logging.info(f'Resuming {self.session_id} at {self.sequence}')
          resume = {
            'token': self.get_token(),
            'session_id': self.session_id,
            'seq': self.sequence,
          }
          await self.send_message(websocket, RESUME, resume)
        else: # Else, reset the session ID and sequence to the new one provided in READY
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
      else:
        logging.error('Cannot handle message type ' + msg['t'])

      if target:
        Thread(target=target, args=(msg['d'],)).start()

    elif msg['op'] == HEARTBEAT:
      await self.heartbeat()
    elif msg['op'] == RECONNECT:
      self.connected = False
    elif msg['op'] == INVALID_SESSION:
      # In theory, we don't have to disconnect here -- we just need to re-send our IDENTIFY.
      # However, it's much simpler to just drop the session, and besides this is pretty rare.
      self.connected = False
      if not msg['d']: # Session is not resumable
        self.session_id = None
      # Short sleep, per https://discord.com/developers/docs/topics/gateway#resuming-example-gateway-resume
      await asyncio.sleep(random() * 4 + 1)
    elif msg['op'] == HEARTBEAT_ACK:
      self.got_heartbeat_ack = True
    else:
      logging.error('Cannot handle message opcode ' + str(msg['op']))
