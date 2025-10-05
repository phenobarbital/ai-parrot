"""
Example: REST API endpoint for web app generation
====================================================
"""
from aiohttp import web
from parrot.generators import StreamlitGenerator, ReactGenerator, HTMLGenerator
from parrot.clients.google import GoogleClient

async def generate_webapp(request):
    """API endpoint for generating web applications."""
    data = await request.json()

    description = data.get('description')
    app_type = data.get('type', 'streamlit')

    if not description:
        return web.json_response(
            {'error': 'Description is required'},
            status=400
        )

    # Get LLM from app context
    llm = request.app['llm_client']

    # Select generator
    generators = {
        'streamlit': StreamlitGenerator(llm),
        'react': ReactGenerator(llm),
        'html': HTMLGenerator(llm)
    }

    generator = generators.get(app_type)
    if not generator:
        return web.json_response(
            {'error': f'Unknown app type: {app_type}'},
            status=400
        )

    try:
        # Generate app
        response = await generator.generate(
            description=description,
            additional_requirements=data.get('requirements'),
            save_to_file=data.get('save_file', False)
        )

        if not response.output:
            return web.json_response(
                {'error': 'Failed to generate app'},
                status=500
            )

        return web.json_response({
            'success': True,
            'app': {
                'title': response.output.title,
                'description': response.output.description,
                'code': response.output.code,
                'features': response.output.features,
                'type': app_type
            }
        })

    except Exception as e:
        return web.json_response(
            {'error': str(e)},
            status=500
        )


# Setup routes
def setup_routes(app):
    app.router.add_post(
        '/api/generate-webapp',
        generate_webapp
    )
