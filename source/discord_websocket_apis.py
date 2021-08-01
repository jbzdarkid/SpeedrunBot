import asyncio
import json
import random
import websockets
from datetime import datetime, timedelta

class WebSocket():
  def __init__(self, intents, on_message_recieved=None):
    self.on_message_recieved = on_message_recieved
    self.intents = intents
    self.sequence = None


  def run(self):
    asyncio.get_event_loop().run_until_complete(self.connect())
    

  async def run_async(self): # TODO: I don't think I need this.
    self.connect()


  async def connect(self):
    uri = 'wss://gateway.discord.gg/?v=9&encoding=json'
    async with websockets.connect(uri) as websocket:
      hello = json.loads(await websocket.recv())
      self.heartbeat_interval = timedelta(seconds=hello['d']['heartbeat_interval'])


      # https://discord.com/developers/docs/topics/gateway#heartbeating
      await asyncio.sleep(self.heartbeat_interval.total_seconds() * random.random())
      await self.heartbeat(websocket)
      
      await self.identify(websocket)

      # Main loop; sleep for the heartbeat duration, while waking up for any messages.
      while 1:
        until_next_heartbeat = self.next_heartbeat - datetime.now()
        if until_next_heartbeat.total_seconds() <= 0:
          await self.heartbeat(websocket)
          continue

        msg = await asyncio.wait_for(websocket.recv(), timeout=until_next_heartbeat.total_seconds())
        await self.handle_message(msg) # TODO: Since I neither need nor see this connection, can I change threads here? That way I don't have as much ASYNC NONSENSE to deal with.


  async def heartbeat(self, websocket):
    await websocket.send(json.dumps({'op': 1, 'd': self.sequence}))
    ack = await asyncio.wait_for(websocket.recv(), timeout=self.heartbeat_interval.total_seconds())
    if ack and json.loads(ack)['op'] == 11:
      self.next_heartbeat = datetime.now() + self.heartbeat_interval
      return
    else:
      # "The client should then immediately terminate the connection with a non-1000 close code, reconnect, and attempt to Resume."
      pass


  async def identify(self, websocket):
    ident = {
      'op': 2,
      'intents': self.intents,
      'd': {
        'token': 'my_token',
        'properties': {
          '$os': 'windows', 
          '$browser': 'speedrunbot-jbzdarkid',
          '$device': 'speedrunbot-jbzdarkid',
        },
      }
    }


  async def handle_message(msg):
    msg = json.loads(msg)
    if msg['op'] == 1:
      await self.heartbeat()


