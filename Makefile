venv:
	python3.11 -m venv .venv
	echo 'run `source .venv/bin/activate` to start develop with Parrot'

install:
	pip install wheel==0.42.0
	# Install Parrot
	pip install -e .[google,milvus,analytics]
	pip install --upgrade python-datamodel
	pip install --upgrade asyncdb[all]
	pip install --upgrade navconfig[default]
	pip install --upgrade navigator-api[locale]
	# Nav requirements:
	pip install --upgrade navigator-session
	pip install --upgrade navigator-auth
	# QS requirements
	pip install --upgrade querysource[analytics]

develop:
	pip install wheel==0.42.0
	# Install Parrot
	pip install -e .[all]
	pip install --upgrade python-datamodel
	pip install --upgrade asyncdb[all]
	pip install --upgrade navconfig[default]
	pip install --upgrade navigator-api[locale]
	# Nav requirements:
	pip install --upgrade navigator-session
	pip install --upgrade navigator-auth
	# QS requirements
	pip install --upgrade querysource
	python -m pip install -Ur requirements/requirements-dev.txt

dev:
	flit install --symlink

release: lint test clean
	flit publish

format:
	python -m black parrot

lint:
	python -m pylint --rcfile .pylint parrot/*.py
	python -m pylint --rcfile .pylint parrot/*.py
	python -m black --check parrot

test:
	python -m coverage run -m parrot.tests
	python -m coverage report
	python -m mypy parrot/*.py

distclean:
	rm -rf .venv
