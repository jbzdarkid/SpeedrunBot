# As tempting as it may be, DO NOT import any non-system modules -- this file needs to be stable!
import requests
from pathlib import Path
from sys import argv

with (Path(__file__).parent / 'source' / 'discord_token.txt').open() as f:
  token = f.read().strip()

api = 'https://discord.com/api/v9'
headers = {
  'Authorization': f'Bot {token}',
  'Content-Type': 'application/json',
}

r = requests.get(f'{api}/oauth2/applications/@me', headers=headers)
if r.status_code != 200:
  print(r.text)
  exit(1)
user = r.json()['owner']['id']

r = requests.post(f'{api}/users/@me/channels', json={'recipient_id': user}, headers=headers)
if r.status_code != 200:
  print(r.text)
  exit(1)
channel = r.json()['id']

with Path(__file__).with_name('out.log').open('r', encoding='utf-8') as f:
  lines = f.read().split('\n')

i = len(lines) - 1
message2 = ''
while len(message2) + len(lines[i]) < 1990: # Discord character limit, with some extra space for wrapper text
  message2 = lines[i] + '\n' + message2
  i -= 1

message1 = ''
while len(message1) + len(lines[i]) < 1900: # Discord character limit, with some extra space for wrapper text
  message1 = lines[i] + '\n' + message1
  i -= 1

cause = argv[1] if len(argv) > 1 else 'unknown'
message1 = f'Bot crashed due to {cause}, last {len(lines) - i} lines:\n```{message1}```'
message2 = f'```{message2}```'

r = requests.post(f'{api}/channels/{channel}/messages', json={'content': message1}, headers=headers)
if r.status_code != 200:
  print(r.text)
  exit(1)

r = requests.post(f'{api}/channels/{channel}/messages', json={'content': message2}, headers=headers)
if r.status_code != 200:
  print(r.text)
  exit(1)
