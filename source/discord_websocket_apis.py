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
    self.user = None
    self.session_is_live = False
    self.session_id = None # Indicates whether or not we have an active session, used to resume if the connection drops.
    self.sequence = None # Indicates the last recieved message in the current session. Meaningless if no session is active.
    self.got_heartbeat_ack = False # Indicates whether or not we've recieved a HEARTBEAT_ACK since the last heartbeat.


  def run(self):
    asyncio.get_event_loop().run_until_complete(self.run_async())


  async def run_async(self):
    while 1: # This loop does not exit naturally
      # Clients are limited to 1000 IDENTIFY calls to the websocket in a 24-hour period.
      # For simplicity, I just use this limit as our generic reconnection rate.
      await asyncio.sleep(24 * 60 * 60 / 1000)

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
    try: # TODO: Why are we only catching this area? Why not catch the entire connect function?
      websocket = await websockets.connect('wss://gateway.discord.gg/?v=9&encoding=json')
      hello = await self.get_message(websocket)
      if not hello:
        return

      # https://discord.com/developers/docs/topics/gateway#heartbeating
      self.heartbeat_interval = timedelta(milliseconds=json.loads(hello)['d']['heartbeat_interval'])
      random_startup = self.heartbeat_interval.total_seconds() * random()
      logging.info(f'Connecting in {random_startup} seconds')
      await asyncio.sleep(random_startup)

      self.connected = True
      # Since this is our first heartbeat, we pretend we've already gotten an ack to avoid immediately disconnecting.
      self.got_heartbeat_ack = True
      await self.heartbeat(websocket)

    except websockets.exceptions.WebSocketException:
      logging.exception('Unable to open a websocket connection due to a websocket error')
    except OSError:
      logging.exception('Unable to open a websocket connection due to a socket error')

    if not self.connected: # Any part of the initial handshake (connect, hello, heartbeat) may fail
      return
    logging.info('Successfully connected and sent initial heartbeat')

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

    self.user = None # TODO: Somewhere better to put this?

    await self.send_message(websocket, IDENTIFY, identify)

    msg = await self.get_message(websocket) # TODO: Heartbeat timeout? Move this into the main loop.
    if msg:
      await self.handle_message(msg, websocket)
    
    # We did not get a READY, so the connection is not live.
    if not self.user:
      self.connected = False
      return None

    # Resume is just... not working. I think the right approach is to only try and resume once.
    # Attempt to resume the previous session, if we had one
    # Maybe check self.sequence instead?
    # logging.info(f'Session is live: {self.session_is_live} Sequence: {self.sequence}')
    # if not self.session_is_live:
    #   logging.info(f'Resuming {self.session_id} at {self.sequence}')
    #   resume = {
    #     'token': self.get_token(),
    #     'session_id': self.session_id,
    #     'seq': self.sequence,
    #   }
    #   await self.send_message(websocket, RESUME, resume)

    return websocket


  async def heartbeat(self, websocket):
    if not self.got_heartbeat_ack:
      # https://discord.com/developers/docs/topics/gateway#heartbeating-example-gateway-heartbeat-ack
      logging.error('Disconnecting because heartbeat did not get an ack since last heartbeat')
      self.connected = False
      return

    await self.send_message(websocket, HEARTBEAT, self.sequence)
    self.next_heartbeat = datetime.now() + self.heartbeat_interval
    self.got_heartbeat_ack = False


  async def get_message(self, websocket, timeout=None):
    try:
      msg = await asyncio.wait_for(websocket.recv(), timeout=timeout)
      logging.info(f'> Got message {msg}')
      return msg
    except (asyncio.TimeoutError, asyncio.CancelledError):
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
      logging.info(f'> Sending message {op}: {data}')
      await websocket.send(json.dumps({'op': op, 'd': data}))
    except websockets.exceptions.WebSocketException:
      logging.exception('Disconnecting due to generic websocket error on send')
      self.connected = False


  async def handle_message(self, msg, websocket):
    msg = json.loads(msg)
    if msg['op'] == DISPATCH:
      if msg['t'] == 'READY':
        self.user = msg['d']['user']
        logging.info('Signed in as ' + self.user['username'])
        if not self.session_id:
          self.session_id = msg['d']['session_id']
          self.sequence = msg['s']
          logging.info(f'Starting new session {self.session_id} at {self.sequence}')
          self.session_is_live = True
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
      await self.heartbeat(websocket)
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
