from __future__ import annotations

import os
import tempfile

import pytest

from ocr_nom_align import NomAlignConfig, ReadingTable
from tests.helpers import READINGS

# no test may reach the network or write to the user's cache: the online lookup is off unless a test turns it on
os.environ["NOM_ALIGN_OFFLINE"] = "1"
os.environ["NOM_ALIGN_CACHE"] = os.path.join(
    tempfile.mkdtemp(prefix="nom-align-cache-"), "online.json"
)


@pytest.fixture
def table():
    return ReadingTable({c: {k} for c, k in READINGS.items()})


@pytest.fixture
def cfg():
    return NomAlignConfig()
