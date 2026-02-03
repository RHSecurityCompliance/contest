"""
These is a superset of OS partitions used by all RHEL-supporting content
profiles, to be used for virtual machines (or otherwise).

It's a list of tuples of
 - absolute path to a mount point
 - size in MBs
"""

partitions = [
    ('/boot', 3000),
    ('/', 1000),
    ('/home', 100),
    ('/var', 5000),
    ('/var/log', 1000),
    ('/var/log/audit', 1000),
    ('/var/tmp', 1000),
    ('/srv', 100),
    ('/opt', 100),
    ('/tmp', 1000),
    ('/usr', 8000),
]
