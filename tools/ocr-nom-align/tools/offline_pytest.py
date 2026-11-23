"""Offline pytest stand-in (dev only): for a sandbox with NO network and no pytest. Copy as pytest.py and run `PYTHONPATH=<dir>:src python pytest.py [test_file_stem]`. Supports tmp_path, monkeypatch, capsys, raises, skip, importorskip, stacked parametrize, conftest fixtures."""

from __future__ import annotations

import contextlib
import importlib
import inspect
import io
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path


class SkippedError(Exception):
    pass


def skip(msg=""):
    raise SkippedError(msg)


def importorskip(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        raise SkippedError(name) from None


def fixture(fn=None, **kw):
    def deco(f):
        f._is_fixture = True
        return f

    return deco(fn) if fn else deco


class _Raises:
    def __init__(self, exc, match=None):
        self.exc, self.match, self.value = exc, match, None

    def __enter__(self):
        return self

    def __exit__(self, t, v, tb):
        if t is None:
            raise AssertionError(f"DID NOT RAISE {self.exc}")
        if not issubclass(t, self.exc):
            return False
        if self.match and not re.search(self.match, str(v)):
            raise AssertionError(f"{v!r} does not match {self.match!r}")
        self.value = v
        return True


def raises(exc, match=None):
    return _Raises(exc, match)


class _Mark:
    def parametrize(self, names, values):
        def deco(f):
            f._plist = [*getattr(f, "_plist", []), (names, values)]
            return f

        return deco

    def __getattr__(self, name):
        return lambda *a, **k: lambda f: f


mark = _Mark()


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value=None, raising=True):
        if isinstance(target, str):
            value = name
            mod, _, attr = target.rpartition(".")
            parts = mod.split(".")
            obj = importlib.import_module(parts[0])
            for p in parts[1:]:
                try:
                    obj = getattr(obj, p)
                except AttributeError:
                    obj = importlib.import_module(".".join(parts[: parts.index(p) + 1]))
            target, name = obj, attr
        old = getattr(target, name)
        self._undo.append(lambda: setattr(target, name, old))
        setattr(target, name, value)

    def setenv(self, k, v):
        old = os.environ.get(k)
        self._undo.append(
            lambda: os.environ.__setitem__(k, old) if old is not None else os.environ.pop(k, None)
        )
        os.environ[k] = str(v)

    def delenv(self, k, raising=True):
        old = os.environ.get(k)
        if old is None:
            if raising:
                raise KeyError(k)
            return
        self._undo.append(lambda: os.environ.__setitem__(k, old))
        del os.environ[k]

    def setitem(self, d, k, v):
        had, old = k in d, d.get(k)
        self._undo.append(lambda: d.__setitem__(k, old) if had else d.pop(k, None))
        d[k] = v

    def chdir(self, p):
        old = os.getcwd()
        self._undo.append(lambda: os.chdir(old))
        os.chdir(p)

    def undo(self):
        while self._undo:
            self._undo.pop()()


class _Capsys:
    def __init__(self):
        self._o, self._e = io.StringIO(), io.StringIO()
        self._ro, self._re = (
            contextlib.redirect_stdout(self._o),
            contextlib.redirect_stderr(self._e),
        )
        self._ro.__enter__()
        self._re.__enter__()

    def readouterr(self):
        r = type("R", (), {"out": self._o.getvalue(), "err": self._e.getvalue()})
        self._o.seek(0)
        self._o.truncate()
        self._e.seek(0)
        self._e.truncate()
        return r

    def close(self):
        self._re.__exit__(None, None, None)
        self._ro.__exit__(None, None, None)


def _run(path_root: Path, only: str | None):
    sys.path.insert(0, str(path_root))
    sys.modules["pytest"] = sys.modules[__name__]
    fixtures = {}
    try:
        conf = importlib.import_module("tests.conftest")
        fixtures = {n: f for n, f in vars(conf).items() if getattr(f, "_is_fixture", False)}
    except ModuleNotFoundError:
        pass
    passed = failed = skipped = 0
    for f in sorted((path_root / "tests").rglob("test_*.py")):
        if only and only not in f.name:
            continue
        modname = ".".join(f.relative_to(path_root).with_suffix("").parts)
        try:
            mod = importlib.import_module(modname)
        except SkippedError:
            skipped += 1
            continue
        local = {n: v for n, v in vars(mod).items() if getattr(v, "_is_fixture", False)}
        for name, fn in list(vars(mod).items()):
            if not (name.startswith("test_") and callable(fn)):
                continue
            cases = [{}]
            for names, values in getattr(fn, "_plist", []):  # stacked decorators: cartesian product
                names = [n.strip() for n in names.split(",")]
                cases = [
                    {**c, **dict(zip(names, v if len(names) > 1 else [v], strict=False))}
                    for c in cases
                    for v in values
                ]
            for case in cases:
                tmp = Path(tempfile.mkdtemp())
                mp, cap = MonkeyPatch(), None
                try:
                    cache = {"tmp_path": tmp, "monkeypatch": mp, **case}
                    pool = {**fixtures, **local}

                    def get(n, cache=cache, pool=pool):
                        if n in cache:
                            return cache[n]
                        if n == "capsys":
                            nonlocal cap
                            cap = cache[n] = _Capsys()
                            return cap
                        ff = pool[n]
                        cache[n] = ff(**{p: get(p) for p in inspect.signature(ff).parameters})
                        return cache[n]

                    fn(**{p: get(p) for p in inspect.signature(fn).parameters})
                    passed += 1
                except SkippedError:
                    skipped += 1
                except BaseException:
                    failed += 1
                    if cap:
                        cap.close()
                        cap = None
                    print(f"FAIL {f.name}::{name} {case or ''}")
                    print("".join(traceback.format_exc().splitlines(True)[-14:]))
                finally:
                    if cap:
                        cap.close()
                    mp.undo()
                    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed} passed, {failed} failed, {skipped} skipped")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run(Path.cwd(), sys.argv[1] if len(sys.argv) > 1 else None) else 0)
