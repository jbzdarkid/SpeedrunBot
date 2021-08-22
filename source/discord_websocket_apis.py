import asyncio
import json
import logging
import random
import websockets
from datetime import datetime, timedelta
from pathlib import Path

class WebSocket():
  def __init__(self, on_message_recieved=None):
    self.on_message_recieved = on_message_recieved
    self.intents = (1 << 9) | (1 << 10) | (1 << 12) # GUILD_MESSAGES, GUILD_MESSAGE_REACTIONS, DIRECT_MESSAGES
    self.sequence = None
    self.connected = False
    self.session_id = None

    with Path(__file__).parent.with_name('discord_token.txt').open() as f:
      self.token = f.read().strip()


  def run(self):
    asyncio.get_event_loop().run_until_complete(self.run())


  async def run(self):
    while 1:
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
      hello = json.loads(await websocket.recv())
      self.heartbeat_interval = timedelta(milliseconds=hello['d']['heartbeat_interval'])
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
    identify = {'op': 2, 'd': {
        'token': self.token,
        'intents': self.intents,
        'properties': {
          '$os': 'windows',
          '$browser': 'speedrunbot-jbzdarkid',
          '$device': 'speedrunbot-jbzdarkid',
        },
      }
    }
    await websocket.send(json.dumps(identify))

    # https://discord.com/developers/docs/topics/gateway#resuming
    if self.session_id:
      logging.info(f'Resuming {self.session_id} at {self.sequence}')
      resume = {'op': 6, 'd': {
          'token': self.token,
          'session_id': self.session_id,
          'seq': self.sequence,
        }
      }
      await websocket.send(json.dumps(resume)) # Note that resuming might return Invalid Session.
    return websocket


  async def heartbeat(self, websocket):
    await websocket.send(json.dumps({'op': 1, 'd': self.sequence}))
    ack = await self.get_message(websocket, timeout=self.heartbeat_interval.total_seconds())
    if ack and json.loads(ack)['op'] == 11:
      self.next_heartbeat = datetime.now() + self.heartbeat_interval
      return
    else:
      # If we recieve any other message, we should disconnect, reconnect, and resume.
      # https://discord.com/developers/docs/topics/gateway#heartbeating-example-gateway-heartbeat-ack
      self.connected = False


  async def get_message(self, websocket, timeout):
    try:
      return await asyncio.wait_for(websocket.recv(), timeout=timeout)
    except asyncio.TimeoutError:
      return None
    except websockets.exceptions.ConnectionClosed as e:
      logging.exception(f'Websocket connection closed: {e.code} {e.reason}')
      self.disconnected = True


  async def handle_message(self, msg):
    msg = json.loads(msg)
    if msg['op'] == 0: # Dispatch
      if msg['t'] == 'READY':
        logging.info('Signed in as ' + msg['d']['user']['username'])
        self.session_id = msg['d']['session_id']
      elif msg['t'] == 'RESUMED':
        pass
      elif msg['t'] == 'MESSAGE_CREATE':
        # TODO: Since I neither need to nor want to see this connection, can I post messages into a thread?
        # That way, the main program can just be sync and slow.
        self.on_message_recieved(msg['d'])
      else:
        logging.error('Not handling message type ' + msg['t'])

    elif msg['op'] == 1: # Heartbeat
      await self.heartbeat()
    elif msg['op'] == 7: # Reconnect
      self.disconnected = True
    elif msg['op'] == 9: # Invalid Session
      self.disconnected = True
      if not msg['d']: # Session is not resumable
        self.session_id = None
    else:
      logging.error('Not handling message opcode ' + msg['op'])