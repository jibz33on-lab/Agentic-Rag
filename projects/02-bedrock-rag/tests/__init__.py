"""Makes this a package so its test modules get qualified names.

Both projects have a tests/test_config.py, and without this pytest imports
them both as the top-level module `test_config` and refuses the second.
Project 01's tests stay a plain directory; only this one needed changing.
"""
