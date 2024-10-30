from aiohttp import web
import aiohttp_cors

app = web.Application()

# Configure CORS settings
cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
    )
})

async def my_handler(request):
    return web.Response(text="Hello, world")

# Register route with CORS applied
route = app.router.add_get('/api/v1/versions', my_handler)
cors.add(route, {
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
    )
})

# Run the app
web.run_app(app, port=5000)
