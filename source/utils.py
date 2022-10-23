from datetime import datetime, timezone

def seconds_since_epoch(): # -> float
  return datetime.now(timezone.utc).timestamp()

def parse_time(str, fmt):
  dt = datetime.strptime(str, fmt)
  dt = dt.replace(tzinfo=timezone.utc) # strptime assumes local time, which is incorrect here.
  return dt
