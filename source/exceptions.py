# Do not use exceptions to pass information.
# If you do so, you are probably using exceptions for non-exceptional circumstances.

class NetworkError(Exception):
  pass

class CommandError(Exception):
  pass

class UsageError(Exception):
  pass

class InvalidApiResponseError(Exception):
  pass