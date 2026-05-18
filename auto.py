#!/usr/bin/env python3
from navigator import Application
from appauto import Main

# define a new Application
app = Application(Main, enable_jinja2=True)
# Enable WebSockets Support
app.add_websockets()

if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print('EXIT FROM APP =========')
