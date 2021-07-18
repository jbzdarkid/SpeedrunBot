import requests
import sys
from pathlib import Path

with Path(__file__).with_name('discord_token.txt').open() as f:
  token = f.read().strip()

api = 'https://discord.com/api/v9'
headers = {
  'Authorization': f'Bot {token}',
  'Content-Type': 'application/json',
}

user = sys.argv[1]
num_lines = int(sys.argv[2]) if len(sys.argv) > 2 else 20

with Path(__file__).with_name('out.log').open('r') as f:
  last_lines = '\n'.join(f.read().split('\n')[-num_lines:])
  if len(last_lines) >= 1900: # Discord character limit, with enough space for the wrapper text.
    last_lines = '...\n' + last_lines[-1900:]
  content = f'Bot crashed, last {num_lines} lines:\n```{last_lines}```'

r = requests.post(f'{api}/users/@me/channels', json={'recipient_id': user}, headers=headers)
if r.status_code != 200:
  print(r.text)
  exit(1)
channel = r.json()['id']

r = requests.post(f'{api}/channels/{channel}/messages', json={'content': content}, headers=headers)
if r.status_code != 200:
  print(r.text)
  exit(1)
