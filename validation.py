# -*- coding: utf-8 -*-

import inspect
import os
from . import funcutil as _fu
from ctypes import Array as _C_ArrayType
from .dynamicopt import option as _opt

with _opt as _def:
    _def('TPP_VALIDATION_DISABLE', 'i', '[tpp.validation] disable validation', 0)


#----------------------------------------------------------------------------
#                    Unified parameter verification tool
#----------------------------------------------------------------------------

class Check(object):
    __slots__ = tuple('_accepts_only:_accepts:_types:_min:_max:_inf:_sup:'
                      '_pred:_normalizer:_dim:_doc:_do_check_val:_is_c_array'.split(':'))

    def __init__(self, *, accepts=(), types=None, min=None, max=None, inf=None, sup=None,
                 pred=None, normalizer=None, dim=0, doc=''):
        self._accepts = accepts if isinstance(accepts, (tuple, list, set, dict)) else (accepts,)
        self._accepts_only = (self._accepts and
                              all([_ is None for _ in [types, min, max, inf, sup, pred]]))
        self._types = types
        self._min = min
        self._max = max
        self._inf = inf
        self._sup = sup
        self._pred = pred
        self._normalizer = normalizer if normalizer else lambda x:x
        if isinstance(dim, int):
            self._dim = (None,) * dim
        elif isinstance(dim, tuple):
            self._dim = dim
        else:
            raise TypeError('dim parameter must be integer or tuple of integer')
        self._doc = doc
        self._do_check_val = any([_ is not None for _ in [min, max, inf, sup, pred]])
        self._is_c_array = isinstance(types, type) and issubclass(types, _C_ArrayType)

    def __call__(self, name, val):
        if not self._dim:
            self._check(name, val, True)
        else:
            def breakdown(dim, val, checktype):
                n = dim[0]
                if n is None:
                    n = len(val)
                if (len(dim) == 1):
                    for i in range(n):
                        self._check(name, val[i], checktype)
                else:
                    dim = dim[1:]
                    for i in range(n):
                        breakdown(dim, val[i], checktype)
            if self._is_c_array:
                self._check_type(name, val)
                checktype = False
            else:
                checktype = bool(self._types)
            if checktype or self._accepts or self._do_check_val:
                breakdown(self._dim, val, checktype)

    @property
    def _types_s(self):
        s = repr(self._types).replace("<type '", '').replace("<class '", '').replace("'>", '')
        if isinstance(self._types, tuple):
            s = s[1:-1]
        return s

    def _check_type(self, name, val):
        if self._types and not isinstance(val, self._types):
            raise TypeError('Parameter %s require %s, but assigned value %s is not.' %
                            (name, self._types_s, val))

    def _check(self, name, val, checktype):
        val = self._normalizer(val)

        if val in self._accepts:
            return
        if self._accepts_only:
            raise TypeError('Parameter %s must be one of %s' % (name, self._accepts))

        if checktype:
            self._check_type(name, val)

        if self._min is not None:
            if val < self._min:
                raise TypeError('Assigned value %s for parameter %s is too small.' % (val, name))

        if self._inf is not None:
            if val <= self._inf:
                raise TypeError('Assigned value %s for parameter %s is too small.' % (val, name))

        if self._max is not None:
            if val > self._max:
                raise TypeError('Assigned value %s for parameter %s is too big.' % (val, name))

        if self._sup is not None:
            if val >= self._sup:
                raise TypeError('Assigned value %s for parameter %s is too big.' % (val, name))

        if self._pred is not None:
            self._pred(name, val)

    def doc(self, name, indent):
        def _doc():
            if self._doc:
                yield '- %s -' % self._doc
            if self._accepts_only:
                yield 'one of %s' % repr(self._accepts)
            else:
                if self._accepts:
                    yield 'accept: %s' % repr(self._accepts)
                if self._types:
                    yield 'types: %s' % self._types_s
                rl = ru = ''
                if self._min is not None:
                    rl = '%s <=' % self._min
                elif self._inf is not None:
                    rl = '%s <' % self._inf
                if self._max is not None:
                    ru = '<= %s' % self._max
                elif self._sup is not None:
                    ru = '< %s' % self._sup
                if rl or ru:
                    yield 'range: %s' % ' ... '.join((rl, ru))
        n_pref = '.' + ' ' * (indent - 1)
        if self._dim:
            for d in self._dim:
                name += '[]' if d is None else ('[%d]' % d)
        name += ': '
        if len(name) > indent:
            yield name
            pref = n_pref
        else:
            pref = name + ' '*(indent - len(name))
        for s in _doc():
            yield pref + s
            pref = n_pref

class _ArgChecker(object):
    def __init__(self, **keywords):
        self._check_all = None
        self._db = {}
        for key, chk in list(keywords.items()):
            if key == '_':
                if not callable(chk):
                    raise TypeError('Parameter of %s must be callable.' % key)
                self._check_all = chk
            else:
                if not isinstance(chk, Check):
                    raise TypeError('Parameter of %s must be Check object.' % key)
                self._db[key] = chk

    def __call__(self, argdef, argdic):
        for key, val in list(argdic.items()):
            if key in self._db:
                self._db[key](key, val)
        if self._check_all:
            self._check_all(argdic)

    def modify_doc(self, f):
        indent = 8
        def _doc():
            args = inspect.getfullargspec(f).args
            for a in args:
                if a in self._db:
                    chk = self._db[a]
                    for s in chk.doc(a, indent):
                        yield s
            for key, chk in list(self._db.items()):
                if key not in args:
                    for s in chk.doc(key, indent):
                        yield s
            if f.__doc__:
                yield ' '
                yield f.__doc__
        f.__doc__ = '\n'.join(_doc())

def parameter(**kws):
    def wrapper(f):
        if _opt.TPP_VALIDATION_DISABLE:
            return f
        ac = _ArgChecker(**kws)
        ac.modify_doc(f)
        return _fu.prehook_wrapper(f, ac)
    return wrapper

#----------------------------------------------------------------------------
#----------------------------------------------------------------------------

__all__ = []
