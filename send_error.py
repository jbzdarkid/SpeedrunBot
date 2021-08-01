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

with Path(__file__).with_name('out.log').open('r', encoding='utf-8') as f:
  content = f.read()
  last_lines = '\n'.join(f.read().split('\n')[-num_lines:])
  if len(last_lines) >= 1900: # Discord character limit, with enough space for the wrapper text.
    last_lines = last_lines[-1900:]
    num_lines = last_lines.count('\n')
    last_lines = '...\n' + last_lines
  content = f'Bot crashed, last {num_lines} lines:\n```{last_lines}```'

# These functions should not be moved into source/discord_apis, since there may be a typo in that file, which would cause this one to crash too.
r = requests.post(f'{api}/users/@me/channels', json={'recipient_id': user}, headers=headers)
if r.status_code != 200:
  print(r.text)
  exit(1)
channel = r.json()['id']

r = requests.post(f'{api}/channels/{channel}/messages', json={'content': content}, headers=headers)
if r.status_code != 200:
  print(r.text)
  exit(1)
