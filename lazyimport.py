# -*- coding: utf-8 -*-

import os
import sys
import traceback
import types as types
import importlib.abc
import importlib.machinery
from threading import Lock, RLock
from .dynamicopt import option as _opt

with _opt as _def:
    _def('TPP_LAZYIMPORT', 'i', '[tpp.lazyimport] print lazyimport action', 0)

_NO_LAZYIMPORT = bool(os.getenv('TPP_NO_LAZYIMPORT'))

def p_(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

class module(types.ModuleType):
    pass

class LazyModule(module):

    def __new__(cls, name, lazyfinder=None, paths=None):
        if _opt.TPP_LAZYIMPORT:
            p_('[ lazyimport ] -lazy-', name)
        self = super().__new__(cls, name, '')
        self.__lock = RLock()
        self.__loaded = False
        self.__lazyfinder = lazyfinder
        self.__path__ = paths
        return self

    def __init__(self, name, *args, **kwargs):
        super().__init__(name, '')

    def __import(self, attr):
        self.__loaded = True
        name = self.__name__
        if self.__lazyfinder:
            self.__lazyfinder.imported(name)
        if name in sys.modules:
            del sys.modules[name]
        if _opt.TPP_LAZYIMPORT:
            p_('[ lazyimport ] import %s (access to %s)' % (name, attr))
        # In order to get module object referrenced by 'name' parameter,
        # we must pass non-emply list as 4-th argument. If not, __import__ return
        # top module object in name.
        try:
            m = __import__(name, globals(), locals(), ['__name__'])
        except:
            traceback.print_exc()
            raise ImportError(name)
        self.__dict__.update(m.__dict__)
        v = getattr(self, attr)
        self.__class__ = module
        return v

    def __getattribute__(self, attr):
        if attr == '__dict__':
            with self.__lock:
                if not self.__loaded:
                    return self.__import(attr)
        return super().__getattribute__(attr)

    def __getattr__(self, attr):
        with self.__lock:
            if not self.__loaded:
                return self.__import(attr)
        return super().__getattribute__(attr)

class LazyLoader(importlib.abc.Loader):
    _slots_ = ('_lazyfinder', '_paths')

    def __init__(self, lazyfinder, paths):
        self._lazyfinder = lazyfinder
        self._paths = paths

    def create_module(self, spec):
        name = spec.name
        if name not in sys.modules:
            m = LazyModule(name, self._lazyfinder, self._paths)
            sys.modules[name] = m
        return sys.modules[name]
        
    def exec_module(self, module):
        pass


class LazyFinder(importlib.abc.MetaPathFinder):
    _slots_ = ('_lock', '_mods', '_roots', '_excepts')

    def __init__(self):
        self._lock = Lock()
        self._mods = set()
        self._roots = set()
        self._excepts = set()
        self._imported = set()

    def register(self, modname):
        with self._lock:
            self._mods.add(modname)

    def register_root(self, rootmod):
        with self._lock:
            self._roots.add(rootmod)
            self._mods.add(rootmod)

    def imported(self, modname):
        with self._lock:
            self._imported.add(modname)
            if modname in self._mods:
                self._mods.remove(modname)

    def remove(self, modname):
        with self._lock:
            self._excepts.add(modname)
            if modname in self._mods:
                self._mods.remove(modname)

    def find_spec(self, modname, paths, target=None):
        def check():
            if paths is None:
                return False
            lastname = modname.split('.')[-1]
            for p in paths:
                for sfx in ['.py', '.pyc', '.so']:
                    mp = os.path.join(p, lastname + sfx)
                    if os.path.exists(mp):
                        return True
                mp = os.path.join(p, lastname)
                if os.path.isdir(mp):
                    return True
            return False
        def do_lazy():
            if _NO_LAZYIMPORT:
                return False
            for e in self._excepts:
                if (modname == e or
                    (modname.startswith(e) and modname[len(e)] == '.')):
                    if _opt.TPP_LAZYIMPORT:
                        p_('[ lazyimport ] import %s (except)' % modname)
                    return False
            if modname in self._imported:
                return False
            if modname in self._mods:
                return check()
            for r in self._roots:
                rz = len(r)
                if modname[:rz] == r and modname[rz] == '.':
                    return check()
            return False
        with self._lock:
            if do_lazy():
                return importlib.machinery.ModuleSpec(modname, LazyLoader(self, paths))
        return None

_lazyfinder = LazyFinder()
register = _lazyfinder.register
register_root = _lazyfinder.register_root
register_except = _lazyfinder.remove

#sys.meta_path.append(_lazyfinder)
sys.meta_path.insert(0, _lazyfinder)

__all__ = ['register']
