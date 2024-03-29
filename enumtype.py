# -*- coding: utf-8 -*-

class _Enumerator(object):

    def __init__(self, v=0):
        self.v = v

    def __call__(self, v=None):
        if v is not None:
            self.v = v
        v = self.v
        self.v += 1
        return v

class _EnumMeta(type):

    def __new__(mcls, clsname, bases, dic):
        cls = super().__new__(mcls, clsname, bases, dic)
        for k, v in list(dic.items()):
            if isinstance(v, int):
                setattr(cls, k, cls(v))
        return cls

class EnumBase(int, metaclass=_EnumMeta):

    def __repr__(self):
        for k, v in list(type(self).__dict__.items()):
            if v == self:
                return '%s(%d)' % (k, v)
        return '?<%s>(%d)' % (type(self).__name__, self)

    __str__ = __repr__

C = _Enumerator(0)
