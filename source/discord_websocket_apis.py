import asyncio
import json
import logging
import random
import websockets
from datetime import datetime, timedelta
from pathlib import Path
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

class WebSocket():
  def __init__(self, on_message=None, on_reaction=None, on_direct_message=None, on_message_edit=None, on_message_delete=None):
    self.intents = 0
    # TODO: There is probably a smoother way to do this, but I need to be careful not to throw an AttributError
    self.on_message = on_message
    self.on_reaction = on_reaction
    self.on_direct_message = on_direct_message
    self.on_message_edit = on_message_edit
    self.on_message_delete = on_message_delete

    if on_message or on_message_edit or on_message_delete:
      self.intents |= (1 << 9) # GUID_MESSAGES
    if on_reaction:
      self.intents |= (1 << 10) # GUILD_MESSAGE_REACTIONS
    if on_direct_message:
      self.intents |= (1 << 12) # DIRECT_MESSAGES

    self.connected = False # Indicates whether or not the websocket is connected. If false, we should not send messages and should exit the loop.
    self.session_id = None # Indicates whether or not we have an active session, used to resume if the connection drops.
    self.sequence = None # Indicates the last recieved message in the current session. Meaningless if no session is active.


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
          await self.handle_message(msg)

      await websocket.close(1001)


  def get_token(self):
    with Path(__file__).with_name('discord_token.txt').open() as f:
      # Although we could save this as a class member, this allows the user to update their token without restarting the bot.
      return f.read().strip()


  async def connect(self):
    while not self.connected:
      websocket = await websockets.connect('wss://gateway.discord.gg/?v=9&encoding=json')
      hello = await self.get_message(websocket)
      if hello:
        self.heartbeat_interval = timedelta(milliseconds=json.loads(hello)['d']['heartbeat_interval'])
        self.connected = True # Set connected early, since both heartbeat and identify can trigger a disconnection.

        # https://discord.com/developers/docs/topics/gateway#heartbeating
        random_startup = self.heartbeat_interval.total_seconds() * random.random()
        logging.info(f'Connecting in {random_startup} seconds')
        await asyncio.sleep(random_startup)
        await self.heartbeat(websocket)

      if not self.connected: # Heartbeat may cause a disconnection, per above doc.
        await websocket.close(1001)
        continue

    # https://discord.com/developers/docs/topics/gateway#identifying
    identify = {
      'token': self.get_token(),
      'intents': self.intents,
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
    await self.send_message(websocket, HEARTBEAT, self.sequence)
    ack = await self.get_message(websocket, timeout=self.heartbeat_interval.total_seconds())
    if ack and json.loads(ack)['op'] == HEARTBEAT_ACK:
      self.next_heartbeat = datetime.now() + self.heartbeat_interval
      return
    else:
      logging.error(f'Disconnecting because heartbeat did not get an ack, instead got {ack}')
      # If we recieve any other message, we should disconnect, reconnect, and resume.
      # https://discord.com/developers/docs/topics/gateway#heartbeating-example-gateway-heartbeat-ack
      self.connected = False


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


  async def handle_message(self, msg):
    msg = json.loads(msg)
    if msg['op'] == DISPATCH:
      if msg['t'] == 'READY':
        self.user = msg['d']['user']
        logging.info('Signed in as ' + user['username'])
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
          target = self.on_message
        else:
          target = self.on_direct_message
      elif msg['t'] == 'MESSAGE_REACTION_ADD':
        target = self.on_reaction
      elif msg['t'] == 'MESSAGE_UPDATE':
        target = self.on_message_edit
      elif msg['t'] == 'MESSAGE_DELETE':
        target = self.on_message_delete
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
    else:
      logging.error('Cannot handle message opcode ' + str(msg['op']))
