---
id: F011
query: "RequestBot virtual subclass registration"
type: read
file: packages/ai-parrot/src/parrot/bots/abstract.py
lines: 3755-3759
---

`AbstractBot.register(RequestBot)` makes isinstance(wrapper, AbstractBot) True.
This is needed because RequestBot is a proxy, not a real subclass.

If RequestBot is retired, this registration can be removed. If kept for
backward compatibility, it stays.
