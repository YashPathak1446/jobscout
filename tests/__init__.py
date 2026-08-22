"""Test suite. Run: python -m unittest discover -s tests -t .

Stdlib unittest deliberately, not pytest: requirements.txt is the end
user install list for a local app, and shipping a test framework to every
user is wrong. A dev-only requirements file is more structure than this
earns right now.
"""
