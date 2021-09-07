import asyncio
import json
import logging
import random
import websockets
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread

class WebSocket():
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

  def __init__(self, on_message=None, on_reaction=None, on_direct_message=None, on_message_edit=None):
    self.intents = 0
    self.on_message = on_message
    self.on_reaction = on_reaction
    self.on_direct_message = on_direct_message
    self.on_message_edit = on_message_edit

    if on_message:
      self.intents |= (1 << 9) # GUID_MESSAGES
    if on_reaction:
      self.intents |= (1 << 10) # GUILD_MESSAGE_REACTIONS
    if on_direct_message:
      self.intents |= (1 << 12) # DIRECT_MESSAGES

    self.connected = False
    self.session_id = None
    self.sequence = -1

    with Path(__file__).with_name('discord_token.txt').open() as f:
      self.token = f.read().strip()


  def run(self):
    asyncio.get_event_loop().run_until_complete(self.run_async())


  async def run_async(self):
    while 1: # This loop does not exit
      websocket = await self.connect_and_resume()

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


  async def connect_and_resume(self):
    while not self.connected:
      websocket = await websockets.connect('wss://gateway.discord.gg/?v=9&encoding=json')
      hello = await self.get_message(websocket)
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
      'token': self.token,
      'intents': self.intents,
      'properties': {
        '$os': 'windows',
        '$browser': 'speedrunbot-jbzdarkid',
        '$device': 'speedrunbot-jbzdarkid',
      }
    }
    await self.send_message(websocket, IDENTIFY, identify)

    # Resume if we have a session_id: https://discord.com/developers/docs/topics/gateway#resuming
    if self.session_id:
      logging.info(f'Resuming {self.session_id} at {self.sequence}')
      resume = {
        'token': self.token,
        'session_id': self.session_id,
        'seq': self.sequence,
      }
      await self.send_message(websocket, RESUME, resume)
    return websocket


  async def heartbeat(self, websocket):
    await self.send_message(websocket, HEARTBEAT, self.sequence)
    ack = await self.get_message(websocket, timeout=self.heartbeat_interval.total_seconds())
    if ack and json.loads(ack)['op'] == HEARTBEAT_ACK:
      self.next_heartbeat = datetime.now() + self.heartbeat_interval
      return
    else:
      logging.error(f'Heartbeat did not get an ack, instead got {ack}')
      # If we recieve any other message, we should disconnect, reconnect, and resume.
      # https://discord.com/developers/docs/topics/gateway#heartbeating-example-gateway-heartbeat-ack
      # self.connected = False # Disabled for now. We'll see how this goes.


  async def get_message(self, websocket, timeout=None):
    try:
      msg = await asyncio.wait_for(websocket.recv(), timeout=timeout)
      logging.info(f'Received: {msg}')
      return msg
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
      logging.info(e)
      return None
    except websockets.exceptions.ConnectionClosedError as e:
      logging.info(e)
      if e.code == 1011:
        import os
        # uh oh
        os.kill(os.getppid(), 9)
        os.kill(os.getpid(), 9)
        return None # Discord sometimes returns this code to ask for a reconnection.
      logging.exception(f'Websocket connection closed: {e}')
      self.connected = False
      return None
    except websockets.exceptions.WebSocketException as e:
      logging.exception(f'Generic websocket connection error: {e}')
      self.connected = False
      return None


  async def send_message(self, websocket, op, data):
    logging.info(f'Sending: {op}, {data}')
    try:
      await websocket.send(json.dumps({'op': op, 'd': data}))
    except websockets.exceptions.WebSocketException as e:
      logging.exception(f'Websocket connection closed: {str(e)}')
      self.connected = False


  async def handle_message(self, msg):
    msg = json.loads(msg)
    if msg['op'] == DISPATCH:
      self.sequence = max(self.sequence, msg['s']) # For safety, I think discord sometimes tells us HELLO, 1 even when we're resuming
      target = None
      if msg['t'] == 'READY':
        logging.error('Signed in as ' + msg['d']['user']['username'])
        self.user = msg['d']['user']
        self.session_id = msg['d']['session_id']
      elif msg['t'] == 'RESUMED':
        logging.info(msg) # I have never seen this happen but they swear it does.
      elif msg['t'] == 'MESSAGE_CREATE':
        if 'guild_id' in msg['d']:
          target = self.on_message
        else:
          target = self.on_direct_message
      elif msg['t'] == 'MESSAGE_REACTION_ADD':
        target = self.on_reaction
      elif msg['t'] == 'MESSAGE_UPDATE':
        target = self.on_message_edit
      else:
        logging.error('Not handling message type ' + msg['t'])

      if target:
        Thread(target=target, args=(msg['d'],)).start()

    elif msg['op'] == HEARTBEAT:
      await self.heartbeat()
    elif msg['op'] == RECONNECT:
      self.connected = False
    elif msg['op'] == INVALID_SESSION:
      self.connected = False
      if not msg['d']: # Session is not resumable
        self.session_id = None
        self.sequence = -1
      # Discord docs said to sleep 1-5 sec here, not that any of the libraries are doing it.
      await asyncio.sleep(random() * 4 + 1)
    else:
      logging.error('Not handling message opcode ' + msg['op'])
