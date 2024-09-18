import os
import re
import yaml
import copy as copy_mod


class TestMetadata(dict):
    def __init__(self):
        metadata_yaml = os.environ['TMT_TEST_METADATA']  # exception if undefined
        with open(metadata_yaml) as f:
            test_metadata = yaml.safe_load(f)
        self.update(test_metadata)

    # return 'TestMetadata' for .copy(), not 'dict'
    def copy(self):
        return copy_mod.copy(self)

    def duration_seconds(self):
        if 'duration' in self:
            duration_str = self['duration']
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
