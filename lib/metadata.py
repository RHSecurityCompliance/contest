import os
import re
import yaml

_cached_metadata = None


def _get_metadata():
    global _cached_metadata
    if _cached_metadata is None:
        metadata_yaml = os.environ['TMT_TEST_METADATA']  # exception if undefined
        with open(metadata_yaml) as f:
            _cached_metadata = yaml.safe_load(f)
    return _cached_metadata


def duration_seconds():
    metadata = _get_metadata()
    if duration_str := metadata.get('duration'):
        match = re.fullmatch(r'([0-9]+)([a-z]+)', duration_str)
        if not match:
            raise RuntimeError(f"'duration' has invalid format: {duration_str}")
        length, unit = match.groups()
        if unit == 'm':
            duration = int(length)*60
        elif unit == 'h':
            duration = int(length)*60*60
        elif unit == 'd':
            duration = int(length)*60*60*24
        else:
            duration = int(length)
    else:
        # use TMT's default of 5m
        duration = 300
    return duration


def tags():
    return _get_metadata().get('tag', [])
