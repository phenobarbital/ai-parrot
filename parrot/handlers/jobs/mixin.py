"""
JobManagerMixin: A mixin class to add asynchronous job execution capabilities to views.

This mixin provides:
- A decorator to enqueue functions to be executed by a job manager
- GET method override to check and retrieve job results by job_id
"""
from typing import Any, Callable, Optional, Dict, Awaitable
import functools
import inspect
import asyncio
from aiohttp import web
from .job import JobManager


class JobManagerMixin:
    """
    Mixin class to add job manager functionality to any BaseView.

    This mixin allows view methods to be executed asynchronously via a job manager,
    and provides automatic handling of job status/result retrieval via GET requests.

    Attributes:
        job_manager: An instance of JobManager that handles async job execution
        job_id_param: The query parameter name for job IDs (default: 'job_id')
    """

    job_manager: Optional[Any] = None
    job_id_param: str = "job_id"

    def __init__(self, *args, **kwargs):
        """Initialize the mixin with job manager instance."""
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'job_manager') or self.job_manager is None:
            raise ValueError(
                "JobManagerMixin requires a 'job_manager' attribute. "
                "Please set it in your view class."
            )

    @staticmethod
    def as_job(
        queue: str = "default",
        timeout: Optional[int] = None,
        result_ttl: Optional[int] = 500,
        return_job_id: bool = True
    ) -> Callable:
        """
        Decorator to enqueue a method to be executed by the job manager.

        Args:
            queue: The queue name for job execution (default: 'default')
            timeout: Maximum execution time in seconds
            result_ttl: Time to live for job results in seconds
            return_job_id: If True, returns job_id; if False, returns job result

        Returns:
            Decorated function that enqueues the job and returns job_id

        Example:
            @JobManagerMixin.as_job(queue="ml_tasks", timeout=3600)
            def process_large_dataset(self, request):
                # This will be executed asynchronously
                result = heavy_computation()
                return result
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(self_arg, *args, **kwargs):
                # self_arg is the instance (self)
                instance = self_arg

                # Extract request object if present in args
                request = None
                if args and hasattr(args[0], 'GET'):
                    request = args[0]

                # Enqueue the job with all arguments including self
                job = instance.job_manager.enqueue(
                    func,
                    args=(self_arg,) + args,  # Include self in args
                    kwargs=kwargs,
                    queue=queue,
                    timeout=timeout,
                    result_ttl=result_ttl
                )

                # Store job metadata
                job_metadata = {
                    'job_id': job.id,
                    'queue': queue,
                    'function': func.__name__,
                    'status': 'enqueued'
                }

                if return_job_id:
                    return instance._create_job_response(job_metadata, request)
                else:
                    # Wait for job to complete and return result
                    return job.result

            # Mark function as async job
            wrapper._is_async_job = True
            wrapper._job_config = {
                'queue': queue,
                'timeout': timeout,
                'result_ttl': result_ttl
            }

            return wrapper
        return decorator

    def get(self, request, *args, **kwargs):
        """
        Override GET method to handle job_id parameter.

        If request contains job_id parameter, retrieves and returns job status/result.
        Otherwise, delegates to the original GET method of the view.

        Args:
            request: The HTTP request object
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            Job status/result if job_id is present, otherwise original GET response
        """
        if (job_id := self._get_job_id_from_request(request)):
            return self._handle_job_status_request(job_id, request)

        # Call the original GET method if it exists
        if hasattr(super(), 'get'):
            return super().get(request, *args, **kwargs)
        else:
            return self._default_get_response(request)

    def _get_job_id_from_request(self, request) -> Optional[str]:
        """
        Extract job_id from request parameters.

        Checks both query parameters (GET) and request data (POST).

        Args:
            request: The HTTP request object

        Returns:
            job_id string if found, None otherwise
        """
        # Check GET parameters
        if hasattr(request, 'GET') and self.job_id_param in request.GET:
            return request.GET.get(self.job_id_param)

        # Check POST/request data
        if hasattr(request, 'data') and self.job_id_param in request.data:
            return request.data.get(self.job_id_param)

        return None

    def _handle_job_status_request(self, job_id: str, request) -> Dict[str, Any]:
        """
        Handle request for job status and results.

        Args:
            job_id: The unique job identifier
            request: The HTTP request object

        Returns:
            Dictionary containing job status, result, or error information
        """
        try:
            job = self.job_manager.fetch_job(job_id)

            if job is None:
                return self._create_error_response(
                    f"Job with id '{job_id}' not found",
                    status_code=404
                )

            job_status = {
                'job_id': job.id,
                'status': job.get_status(),
                'created_at': str(job.created_at) if hasattr(job, 'created_at') else None,
                'started_at': str(job.started_at) if hasattr(job, 'started_at') else None,
                'ended_at': str(job.ended_at) if hasattr(job, 'ended_at') else None,
            }

            # Add result if job is finished
            if job.is_finished:
                job_status['result'] = job.result
                job_status['success'] = True

            # Add error if job failed
            elif job.is_failed:
                job_status['error'] = str(job.exc_info) if hasattr(job, 'exc_info') else "Unknown error"
                job_status['success'] = False

            # Job is still in progress
            else:
                job_status['message'] = "Job is still in progress"
                job_status['progress'] = job.meta.get('progress') if hasattr(job, 'meta') else None

            return self._create_success_response(job_status)

        except Exception as e:
            return self._create_error_response(
                f"Error fetching job: {str(e)}",
                status_code=500
            )

    def _create_job_response(
        self,
        job_metadata: Dict[str, Any],
        request
    ) -> Dict[str, Any]:
        """
        Create standardized response for job creation.

        Args:
            job_metadata: Dictionary containing job information
            request: The HTTP request object

        Returns:
            Formatted response with job details and status URL
        """
        response = {
            'success': True,
            'job_id': job_metadata['job_id'],
            'status': job_metadata['status'],
            'message': f"Job enqueued successfully on queue '{job_metadata['queue']}'",
        }

        # Add status URL if request is available
        if request and hasattr(request, 'build_absolute_uri'):
            status_url = self._build_status_url(request, job_metadata['job_id'])
            response['status_url'] = status_url

        return response

    def _build_status_url(self, request, job_id: str) -> str:
        """
        Build URL for checking job status.

        Args:
            request: The HTTP request object
            job_id: The unique job identifier

        Returns:
            Full URL for job status endpoint
        """
        base_url = request.build_absolute_uri(request.path)
        separator = '&' if '?' in base_url else '?'
        return f"{base_url}{separator}{self.job_id_param}={job_id}"

    def _create_success_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create standardized success response."""
        return {
            'success': True,
            **data
        }

    def _create_error_response(
        self,
        message: str,
        status_code: int = 400
    ) -> Dict[str, Any]:
        """Create standardized error response."""
        return {
            'success': False,
            'error': message,
            'status_code': status_code
        }

    def _default_get_response(self, request) -> Dict[str, Any]:
        """Default GET response when no job_id is provided and no parent GET exists."""
        return {
            'message': 'No job_id provided. Use POST to create jobs or GET with job_id to check status.',
            'usage': {
                'create_job': 'POST to endpoint with required parameters',
                'check_status': f'GET to endpoint with ?{self.job_id_param}=<job_id>'
            }
        }

    @classmethod
    def get_async_methods(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get all methods decorated with @as_job in the class.

        Returns:
            Dictionary mapping method names to their job configurations
        """
        return {
            name: method._job_config
            for name, method in inspect.getmembers(
                cls, predicate=inspect.isfunction
            )
            if hasattr(method, '_is_async_job') and method._is_async_job
        }


class AsyncJobManagerMixin:
    """
    Async-native mixin for aiohttp views with job manager functionality.

    Unlike the sync JobManagerMixin (designed for RQ), this version:
    - Works natively with aiohttp's async request handlers
    - Supports both your asyncio JobManager and RQ Queue
    - Provides async get() method
    - Handles aiohttp request objects

    Usage with aiohttp:
        class MyView(AsyncJobManagerMixin, web.View):
            def __init__(self, request):
                super().__init__(request)
                # Use either RQ Queue or adapted JobManager
                self.job_manager = request.app['job_queue']

            @AsyncJobManagerMixin.as_job(queue="tasks", timeout=3600)
            async def post(self):
                # Your async handler
                return {"result": "success"}

            async def get(self):
                # Automatically handles job_id parameter
                return await super().get()
    """

    job_manager: Optional[Any] = None
    job_id_param: str = "job_id"

    def __init__(self, *args, **kwargs):
        """Initialize the mixin."""
        super().__init__(*args, **kwargs)

    def _get_jobmanager(self, request: web.Request) -> Any:
        """
        Retrieve the job manager from the aiohttp request.

        Args:
            request: aiohttp Request object
        Returns:
            Job manager instance (RQ Queue or your JobManager)
        """
        return request.app['job_manager'] if 'job_manager' in request.app else JobManager()

    @staticmethod
    def as_job(
        queue: str = "default",
        timeout: Optional[int] = None,
        result_ttl: Optional[int] = 500,
        return_job_id: bool = True,
        async_execution: bool = True
    ) -> Callable:
        """
        Decorator to enqueue an async method for job execution.

        Args:
            queue: Queue name for job execution
            timeout: Maximum execution time in seconds
            result_ttl: Time to live for job results
            return_job_id: If True, returns job_id immediately
            async_execution: If True, expects async function

        Returns:
            Decorated async function

        Example:
            @AsyncJobManagerMixin.as_job(queue="ml_tasks", timeout=3600)
            async def process_data(self):
                # This executes asynchronously
                result = await heavy_computation()
                return result
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def async_wrapper(self_arg, *args, **kwargs):
                instance = self_arg

                if not hasattr(instance, 'job_manager') or instance.job_manager is None:
                    raise ValueError(
                        "job_manager not set. Set it in your view's __init__ method."
                    )

                # Extract request if available
                request = None
                if hasattr(instance, 'request'):
                    request = instance.request
                elif args and isinstance(args[0], web.Request):
                    request = args[0]

                # Enqueue the job
                job = instance.job_manager.enqueue(
                    func,
                    args=(self_arg,) + args,
                    kwargs=kwargs,
                    queue=queue,
                    timeout=timeout,
                    result_ttl=result_ttl
                )

                # Create job metadata
                job_metadata = {
                    'job_id': job.id,
                    'queue': queue,
                    'function': func.__name__,
                    'status': 'enqueued'
                }

                if return_job_id:
                    response_data = instance._create_job_response(job_metadata, request)
                    return web.json_response(response_data)
                else:
                    # Wait for job to complete
                    # This is async-friendly
                    while not (job.is_finished or job.is_failed):
                        await asyncio.sleep(0.1)
                        job.refresh() if hasattr(job, 'refresh') else None

                    if job.is_failed:
                        return web.json_response(
                            {'error': str(job.exc_info)},
                            status=500
                        )
                    return web.json_response({'result': job.result})

            # Mark as async job
            async_wrapper._is_async_job = True
            async_wrapper._job_config = {
                'queue': queue,
                'timeout': timeout,
                'result_ttl': result_ttl,
                'async': async_execution
            }

            return async_wrapper
        return decorator

    async def get(self) -> web.Response:
        """
        Async GET method to handle job status requests.

        If request contains job_id parameter, returns job status/result.
        Otherwise, delegates to parent GET method or returns default response.

        Returns:
            web.Response with job status or default response
        """
        # Get request object
        request = self.request if hasattr(self, 'request') else None

        if not request:
            return web.json_response({
                'error': 'Request object not available'
            }, status=500)

        # Check for job_id parameter
        if (job_id := self._get_job_id_from_request(request)):
            response_data = await self._handle_job_status_request(job_id, request)
            status_code = response_data.pop('status_code', 200)
            return web.json_response(response_data, status=status_code)

        # Call parent get if it exists
        if hasattr(super(), 'get'):
            return await super().get()

        # Return default response
        return web.json_response(self._default_get_response(request))

    def _get_job_id_from_request(self, request: web.Request) -> Optional[str]:
        """
        Extract job_id from aiohttp request.

        Args:
            request: aiohttp Request object

        Returns:
            job_id if found, None otherwise
        """
        # Check query parameters
        if self.job_id_param in request.query:
            return request.query.get(self.job_id_param)

        # Check match_info (URL path parameters)
        if self.job_id_param in request.match_info:
            return request.match_info.get(self.job_id_param)

        return None

    async def _handle_job_status_request(
        self,
        job_id: str,
        request: web.Request
    ) -> Dict[str, Any]:
        """
        Handle async job status request.

        Args:
            job_id: Job identifier
            request: aiohttp Request object

        Returns:
            Dictionary with job status/result
        """
        try:
            # Fetch job (works with both RQ and your JobManager)
            job = self.job_manager.fetch_job(job_id)

            if job is None:
                return {
                    'success': False,
                    'error': f"Job with id '{job_id}' not found",
                    'status_code': 404
                }

            # Build status response
            job_status = {
                'job_id': job.id,
                'status': job.get_status(),
                'created_at': str(job.created_at) if hasattr(job, 'created_at') else None,
                'started_at': str(job.started_at) if hasattr(job, 'started_at') else None,
                'ended_at': str(job.ended_at) if hasattr(job, 'ended_at') else None,
            }

            # Add elapsed time if available
            if hasattr(job, 'elapsed_time') and job.elapsed_time:
                job_status['elapsed_time'] = job.elapsed_time

            # Handle completed jobs
            if job.is_finished:
                job_status['result'] = job.result
                job_status['success'] = True

            # Handle failed jobs
            elif job.is_failed:
                job_status['error'] = str(job.exc_info) if hasattr(job, 'exc_info') else "Unknown error"
                job_status['success'] = False

            # Job still in progress
            else:
                job_status['message'] = "Job is still in progress"
                if hasattr(job, 'meta'):
                    job_status['progress'] = job.meta.get('progress')

            return self._create_success_response(job_status)

        except Exception as e:
            return {
                'success': False,
                'error': f"Error fetching job: {str(e)}",
                'status_code': 500
            }

    def _create_job_response(
        self,
        job_metadata: Dict[str, Any],
        request: Optional[web.Request]
    ) -> Dict[str, Any]:
        """
        Create standardized job creation response for aiohttp.

        Args:
            job_metadata: Job information
            request: aiohttp Request object

        Returns:
            Response dictionary
        """
        response = {
            'success': True,
            'job_id': job_metadata['job_id'],
            'status': job_metadata['status'],
            'message': f"Job enqueued successfully on queue '{job_metadata['queue']}'",
        }

        # Add status URL
        if request:
            status_url = self._build_status_url(request, job_metadata['job_id'])
            response['status_url'] = status_url

        return response

    def _build_status_url(self, request: web.Request, job_id: str) -> str:
        """
        Build status URL for aiohttp request.

        Args:
            request: aiohttp Request object
            job_id: Job identifier

        Returns:
            Full URL for checking job status
        """
        # Build URL with job_id parameter
        scheme = request.scheme
        host = request.host
        path = request.path

        return f"{scheme}://{host}{path}?{self.job_id_param}={job_id}"

    def _create_success_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create standardized success response."""
        return {
            'success': True,
            **data
        }

    def _default_get_response(self, request: web.Request) -> Dict[str, Any]:
        """Default GET response for aiohttp."""
        return {
            'message': 'No job_id provided. Use POST to create jobs or GET with job_id to check status.',
            'usage': {
                'create_job': f'POST to {request.path}',
                'check_status': f'GET to {request.path}?{self.job_id_param}=<job_id>'
            }
        }

    @classmethod
    def get_async_methods(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get all methods decorated with @as_job.

        Returns:
            Dictionary mapping method names to configurations
        """
        return {
            name: method._job_config
            for name, method in inspect.getmembers(cls)
            if (hasattr(method, '_is_async_job') and method._is_async_job)
        }
