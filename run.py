#!/usr/bin/env python3
from navigator import Application
from navigator.ext.memcache import Memcache
from app import Main

# define a new Application
app = Application(Main, enable_jinja2=True)
mcache = Memcache()
mcache.setup(app)

# Enable WebSockets Support
app.add_websockets()

if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
