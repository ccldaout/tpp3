# -*- coding: utf-8 -*-

from .ctypessyms import *

# Enum class

from .enumtype import EnumBase as _EnumBase

class _MetaEnum(type(ctypes.c_int32)):
    def __new__(mcls, name, bases, dic):
        cls = super().__new__(mcls, name, bases, dic)
        cls2 = type(_EnumBase)(name+'_', (_EnumBase,), dic)
        cls._enumtype_ = cls2
        for k, v in list(dic.items()):
            if isinstance(v, int):
                setattr(cls, k, getattr(cls2, k))
        return cls

    def __mul__(cls, val):
        return _MetaArray('%s_Array_%d' % (cls.__name__, val),
                          (ctypes.Array,),
                          {'_length_':val,
                           '_type_':cls})

class Enum(ctypes.c_int32, metaclass=_MetaEnum):
    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        if isinstance(other, ctypes.c_int32):
            return self.value == other.value
        return self.value == other

    def __coerce__(self, other):
        return (self.value, other)

    def __int__(self):
        return self.value

    def __long__(self):
        return int(self.value)

    def __float__(self):
        return float(self.value)

    def __repr__(self):
        i_self = int(self)
        for k, v in list(type(self).__dict__.items()):
            if v == i_self:
                return '%s(%d)' % (k, i_self)
        return '?<%s>(%d)' % (type(self).__name__, i_self)

    __str__ = __repr__

class EnumDesc(object):

    def __new__(cls, orgdesc):
        self = super().__new__(cls)
        self._orgdesc = orgdesc
        return self

    def __get__(self, ins, own):
        v = self._orgdesc.__get__(ins, own)
        if ins is None:
            return v
        return v._enumtype_(v.value)

    def __set__(self, ins, val):
        self._orgdesc.__set__(ins, val)

def _wrap_getitem_enum(getitem_):
    def _getitem(self, idx):
        v = getitem_(self, idx)
        return v._enumtype_(v.value)
    return _getitem

# additional functions

def is_array(ctype):
    return issubclass(ctype, ctypes.Array)

def analyze_ctypes(ctype):
    cdata = ctypes.Structure.__base__
    ds = []
    if not issubclass(ctype, cdata):
        return None
    while hasattr(ctype, '_length_'):
        ds.append(getattr(ctype, '_length_'))
        ctype = getattr(ctype, '_type_')
    return (ctype, ds)

# addtional methods

def _make_dump():
    from .toolbox import BufferedPrint

    bufferedprint = BufferedPrint()

    def _isallzero(cdata, csize=0):
        if isinstance(cdata, int):
            return (cdata == 0)
        elif isinstance(cdata, float):
            return (cdata == 0.0)
        elif isinstance(cdata, bytes):
            return (len(cdata) == 0)
        if csize == 0:
            csize = c_sizeof(cdata)
        return (c_string_at(c_addressof(cdata), csize).count(b'\x00') == csize)

    def _dump(ind, name, obj, printer):
        if name[:2] == '__':
            return
        if hasattr(obj, '_fields_'):
            printer('%*s%s {', ind, ' ', name)
            for m in obj._fields_:
                _dump(ind+2, m[0], getattr(obj, m[0]), printer)
            printer('%*s}', ind, ' ')
        elif isinstance(obj, bytes):
            #printer('%*s%s: <%s>', ind, ' ', name, obj.decode('utf-8'))
            printer('%*s%s: <%s>', ind, ' ', name, obj)
        elif hasattr(obj, '__len__'):
            last = len(obj)-1
            for i in range(len(obj)):
                if i == 0 or i == last or not _isallzero(obj[i]):
                    idxm = '%s[%3d]' % (name, i)
                    _dump(ind, idxm, obj[i], printer)
        else:
            printer('%*s%s: %s', ind, ' ', name, str(obj))

    def _print(fmt, *args):
        print(fmt % args)

    def dump(self, printer=None, all=False):
        if not printer:
            printer = _print
        bufferedprint.printer = printer
        bufferedprint.limit_calls = 10000
        with bufferedprint:
            _dump(2, '_', self, bufferedprint)

    return dump
        
dump = _make_dump()

def copy(self, trg=None):
    if trg:
        c_memmove(c_addressof(trg), c_addressof(self), c_sizeof(self))
    else:
        trg = type(self).from_buffer_copy(self)
    return trg

def clear(self):
    c_memset(c_addressof(self), 0, c_sizeof(self))

def encode(self):
    if isinstance(self, (str, int, float)):
        return self
    if hasattr(self, '__len__'):
        return [encode(o) for o in self]
    if hasattr(self, '_fields_'):
        return dict(((fld[0], encode(getattr(self, fld[0]))) for fld in self._fields_))
    raise Exception("%s cannot be encoded" % self)

def decode(self, eobj):
    if isinstance(eobj, list):
        if isinstance(eobj[0], (list, dict)):
            for idx, e in enumerate(eobj):
                decode(self[idx], e)
        else:
            for idx, e in enumerate(eobj):
                self[idx] = e
    elif isinstance(eobj, dict):
        for k, e in list(eobj.items()):
            if isinstance(e, (list, dict)):
                decode(getattr(self, k), e)
            else:
                setattr(self, k, e)
    return self

# Suppress TypeError when assigninig a float value to int type.

def _wrap_setattr(setattr_):
    def _setattr(self, mbr, val):
        if mbr not in self._permit_attrs_ and not self._permit_new_attr_:
            raise AttributeError('%s has no member %s.' % (type(self).__name__, mbr))
        try:
            setattr_(self, mbr, val)
        except TypeError:
            if isinstance(val, float):
                setattr_(self, mbr, int(val))
            elif isinstance(val, str):
                setattr_(self, mbr, bytes(val, 'ascii'))
            else:
                raise
    return _setattr

_c_ints = (c_int8, c_uint8, c_int16, c_uint16, c_int32, c_uint32, c_int64, c_uint64)

def _wrap_setitem(setitem_):
    def _setitem(self, idx, val):
        if isinstance(idx, _c_ints):
            idx = idx.value
        try:
            setitem_(self, idx, val)
        except TypeError:
            if isinstance(val, float):
                setitem_(self, idx, int(val))
            else:
                raise
    return _setitem

# Enable a ctypes array to be _pickled.

def _array_unpickle(ctana, bs):
    ctype, ds = ctana
    for n in reversed(ds):
        ctype *= n
    return array(ctype).from_buffer(bs)

def _array_reduce(self):
    return (_array_unpickle,
            (analyze_ctypes(type(self)),
             bytearray(c_string_at(c_addressof(self), c_sizeof(self)))),
            )

# Extender for ctypes array.

def array(ctype):
    def __repr__(self):
        def parts(self):
            n, ds = analyze_ctypes(type(self))
            yield n.__name__
            for d in ds:
                yield '[%d]' % d
        return ''.join(parts(self))
    orgctype = ctype
    while hasattr(ctype, '_length_'):
        if hasattr(ctype, '_customized_'):
            return orgctype
        ctype._customized_ = True
        ctype.__reduce__ = _array_reduce
        ctype.copy = copy
        ctype.dup = copy
        ctype.clear = clear
        ctype.dump = dump
        ctype.encode = encode
        ctype.decode = decode
        ctype.__repr__ = __repr__
        ctype2 = ctype
        ctype = ctype._type_
    ctype2.__setitem__ = _wrap_setitem(ctype2.__setitem__)
    if issubclass(ctype, Enum):
        ctype2.__getitem__ = _wrap_getitem_enum(ctype2.__getitem__)
    return orgctype

# Additional properties for ctypes structure object.

def _top_base(self):
    o = self
    while o._b_base_:
        o = o._b_base_
    return o

class _PropertyCacheDesc(object):
    __slots__ = ('_name',)

    class _Store(object):
        pass

    def __new__(cls, name):
        self = super().__new__(cls)
        self._name = name
        return self

    def __get__(self, obj, cls):
        top = _top_base(obj)
        if self._name in top.__dict__:
            s = top.__dict__[self._name]
        else:
            s = type(self)._Store()
            top.__dict__[self._name] = s
        if top is not obj:
            obj.__dict__[self._name] = s
        return s

# Custom Structure and Union classes.

def _setup(cls):
    if hasattr(cls, '_fields_'):
        flds = cls._fields_

        attrs = [f[0] for f in flds]

        name = '_permit_new_attr_'
        if hasattr(cls, name):
            if isinstance(getattr(cls, name), (tuple, list)):
                attrs.extend(getattr(cls, name))
                setattr(cls, name, False)
        else:
            setattr(cls, name, False)

        name = '_permit_attrs_'
        if hasattr(cls, name):
            attrs.extend(getattr(cls, name))
        setattr(cls, name, set(attrs))

        for fld in flds:
            if is_array(fld[1]):
                array(fld[1])
            if issubclass(fld[1], Enum):
                try:
                    setattr(cls, fld[0], EnumDesc(cls.__dict__[fld[0]]))
                except KeyError:
                    pass

    cls.__setattr__ = _wrap_setattr(cls.__setattr__)
    cls._property_ = _PropertyCacheDesc('_property_')
    cls._top_base_ = property(_top_base)
    cls.copy = copy
    cls.dup = copy
    cls.clear = clear
    cls.dump = dump
    cls.encode = encode
    cls.decode = decode

class _MetaArray(type(ctypes.Array)):
    def __new__(mcls, name, bases, dic):
        cls = super().__new__(mcls, name, bases, dic)
        return array(cls)

    def __mul__(cls, val):
        newcls = super().__mul__(val)
        return array(newcls)

class _MetaStruct(type(ctypes.Structure)):
    def __new__(mcls, name, bases, dic):
        cls = super().__new__(mcls, name, bases, dic)
        _setup(cls)
        return cls

    def __mul__(cls, val):
        return _MetaArray('%s_Array_%d' % (cls.__name__, val),
                          (ctypes.Array,),
                          {'_length_':val,
                           '_type_':cls})

class _MetaUnion(type(ctypes.Union)):
    def __new__(mcls, name, bases, dic):
        cls = super().__new__(mcls, name, bases, dic)
        _setup(cls)
        return cls

    def __mul__(cls, val):
        return _MetaArray('%s_Array_%d' % (cls.__name__, val),
                          (ctypes.Array,),
                          {'_length_':val,
                           '_type_':cls})

class Struct(ctypes.Structure, metaclass=_MetaStruct):
    def __iter__(self):
        return iter((getattr(self, mbr[0]) for mbr in self._fields_))

    def __repr__(self):
        def walk(co):
            hn = 4
            ct = type(co)
            yield ct.__name__ + '('
            sep = ''
            for fld in ct._fields_[:hn]:
                v = getattr(co, fld[0])
                if isinstance(v, (int, float, bytes)):
                    yield '%s%s:%s' % (sep, fld[0], repr(v))
                else:
                    yield '%s%s' % (sep, fld[0])
                sep = ', '
            if len(ct._fields_) > hn:
                yield ', ...'
            yield ')'
        return ''.join(walk(self))

class Union(ctypes.Union, metaclass=_MetaUnion):
    _permit_attrs_ = {'_assigned_mbr_'}

    def __setattr__(self, mbr, val):
        super().__setattr__('_assigned_mbr_', mbr)
        return super().__setattr__(mbr, val)

    def __repr__(self):
        mbr = self._fields_[0][0]
        if hasattr(self, '_assigned_mbr_'):
            mbr = self._assigned_mbr_
        return '%s(%s:%s)' % (type(self).__name__, mbr, repr(getattr(self, mbr)))

#

__all__ = []
