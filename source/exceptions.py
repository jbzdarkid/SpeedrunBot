import requests

# As an interim step, these exceptions inherit from the existing exceptions, at least until I erradicate them.

class NetworkError(requests.exceptions.ConnectionError):
  pass

class CommandError(ValueError):
  pass
