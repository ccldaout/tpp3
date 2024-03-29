import atexit
import gc
import os
import sys
import weakref
import builtins

for _m in ['warnings', 'abc'] + os.getenv('INSMON_ERR_MODULES', '').split(' '):
    if _m:
        _m = __import__(_m)
        _m.type = type
    
class _type(type):
    __original_type__ = type

    def __new__(mcls, name, bases=None, dic=None):
        if bases is None:
            return _type.__original_type__(name)
        if dic is None:
            return _type.__original_type__(name, bases)
        if ('__slots__' in dic and
            '__weakref__' not in dic['__slots__'] and
            name != '_object'):
            sl = list(dic['__slots__'])
            sl.append('__weakref__')
            dic['__slots__'] = sl
        return super().__new__(mcls, name, bases, dic)
    
class _object(object, metaclass=_type):
    __slots__ = ()
    __counts__ = {}
    __gc_collect__ = gc.collect
    __objset_class__ = weakref.WeakSet

    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls)
        try:
            s = _object.__counts__.setdefault(cls, _object.__objset_class__())
            s.add(self)
        except:
            pass
        return self

    @staticmethod
    def __show_alived__(all_=False):
        _object.__gc_collect__()
        for k, os in list(_object.__counts__.items()):
            n = len(os)
            if n or all_:
                print('%8d %s' % (len(os), k))

    @staticmethod
    def __clear_alived__():
        _object.__counts__ = {}

def enable():
    builtins.type = _type
    builtins.object = _object
    builtins.show_alived = _object.__show_alived__
    builtins.clear_alived = _object.__clear_alived__
    atexit.register(_object.__show_alived__)

__all__ = []

if __name__ == '__main__':
    enable()
    del atexit, gc, os, weakref, _m, enable
    sys.argv.pop(0)
    if sys.argv:
        _argv0 = sys.argv[0]
        del sys
        exec(compile(open(_argv0, "rb").read(), _argv0, 'exec'))
    else:
        del sys
