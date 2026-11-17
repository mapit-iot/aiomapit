from importlib.metadata import version

# Read once at import: reading it per client would hit the disk inside the event loop.
__version__ = version("aiomapit")
