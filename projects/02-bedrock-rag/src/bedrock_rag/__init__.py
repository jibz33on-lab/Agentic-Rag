"""Project 02's modules, under a package name of their own.

Flat modules in src/ would be imported as `config` and `parameters`, and
project 01 already puts a `config` on sys.path. Both projects run in one pytest
session against one .venv, so the first `config` imported wins for the whole
run and the second project silently gets the first one's module. The skeleton
names main, answerer and rag_query for this project too, and project 01 has all
three -- so this was not a near miss.
"""
