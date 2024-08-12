#!/usr/bin/env python3
import asyncio
import time
from functools import partial
from aiohttp import web
from navigator import Application
from app import Main
app = Application(Main, enable_jinja2=True)


async def send_email(email, message):
    print(' :: Waiting for 10 seconds to finish task :: ')
    await asyncio.sleep(10)  # Simulate email sending
    print(f"Email sent to {email} with message: {message}")

def blocking_code(request):
    time.sleep(10)
    print(":: Blocking code executed ::")

async def handle_post(request):
    data = await request.json()
    tasker = request.app['tasker']
    await tasker.put(send_email, data['email'], data['message'])
    fn = partial(blocking_code, request)
    await tasker.put(fn)
    return web.json_response({'status': 'Task enqueued'})


app.router.add_post('/send_email', handle_post)


if __name__ == '__main__':
    try:
        app.run()
    except KeyboardInterrupt:
        print(
            "Closing Parrot Chatbot Service ..."
        )
