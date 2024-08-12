# AI Parrot: Python package for creating Chatbots
This is an open-source Python package for creating Chatbots based on Langchain and Navigator.
This README provides instructions for installation, development, testing, and releasing Parrot.

## Installation

**Creating a virtual environment:**

This is recommended for development and isolation from system-wide libraries.
Run the following command in your terminal:

Debian-based systems installation:
   ```
   sudo apt install gcc python3.11-venv python3.11-full python3.11-dev libmemcached-dev zlib1g-dev build-essential libffi-dev unixodbc unixodbc-dev libsqliteodbc libev4 libev-dev
   ```

   For Qdrant installation:
   ```
   docker pull qdrant/qdrant
   docker run -d -p 6333:6333 -p 6334:6334 --name qdrant -v $(pwd)/qdrant_storage:/qdrant/storage:z qdrant/qdrant
   ```

For VertexAI, creates a folder on "env" called "google" and copy the JSON credentials file into it.

   ```bash
   make venv
   ```

   This will create a virtual environment named `.venv`. To activate it, run:

   ```bash
   source .venv/bin/activate  # Linux/macOS
   ```

   Once activated, install Parrot within the virtual environment:

   ```bash
   make install
   ```
   The output will remind you to activate the virtual environment before development.

   **Optional** (for developers):
   ```bash
   pip install -e .
   ```

## Start http server
```bash
python run.py
```

## Development Setup

This section explains how to set up your development environment:

1. **Install development requirements:**

   ```bash
   make setup
   ```

   This installs development dependencies like linters and test runners mentioned in the `docs/requirements-dev.txt` file.

2. **Install Parrot in editable mode:**

   This allows you to make changes to the code and test them without reinstalling:

   ```bash
   make dev
   ```

   This uses `flit` to install Parrot in editable mode.


### Usage (Replace with actual usage instructions)

*Once you have set up your development environment, you can start using Parrot.*

#### Test with Code ChatBOT
* Set environment variables for:
 [google]
   GOOGLE_API_KEY=apikey
   GOOGLE_CREDENTIALS_FILE=.../credentials.json
   VERTEX_PROJECT_ID=vertex-project
   VERTEX_REGION=region

* Run the chatbot:
    ```bash
    python examples/test_agent.py
    ```

### Testing

To run the test suite:

```bash
make test
```

This will run tests using `coverage` to report on code coverage.


### Code Formatting

To format the code with black:

```bash
make format
```


### Linting

To lint the code for style and potential errors:

```bash
make lint
```

This uses `pylint` and `black` to check for issues.


### Releasing a New Version

This section outlines the steps for releasing a new version of Parrot:

1. **Ensure everything is clean and tested:**

   ```bash
   make release
   ```

   This runs `lint`, `test`, and `clean` tasks before proceeding.

2. **Publish the package:**

   ```bash
   make release
   ```

   This uses `flit` to publish the package to a repository like PyPI. You'll need to have publishing credentials configured for `flit`.


### Cleaning Up

To remove the virtual environment:

```bash
make distclean
```


### Contributing

We welcome contributions to Parrot! Please refer to the CONTRIBUTING.md file for guidelines on how to contribute.
