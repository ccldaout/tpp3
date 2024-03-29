# -*- coding: utf-8 -*-

import _pickle
import json
import os
import select
import socket
import struct
import sys
import time
import traceback
from . import threadutil as tu
from . import toolbox as tb
from .dynamicopt import option as _opt

with _opt as _def:
    _def('TPP_IPC_DEBUG', 'i', '[tpp.ipc] print message handled by packer', 0)

___ = tb.no_except


PICKLE_PROTOCOL = 4


#----------------------------------------------------------------------------
#                          simple socket wrappter
#----------------------------------------------------------------------------

class CSocket(object):

    def __getattr__(self, attr):
        return getattr(self._sock, attr)
    
    def __new__(cls, addr, server=False, backlog=2, ctmo_s=None):
        self = super().__new__(cls)
        self.send_tmo_s = 120
        self.init_recv_tmo_s = None
        self.next_recv_tmo_s = 120
        self.is_server = server
        if isinstance(addr, socket.socket):
            self._sock = addr
            self.tcpnodelay()
            self.tcpkeepalive()
            return self
        af = socket.AF_UNIX
        if isinstance(addr, tuple):
            af = socket.AF_INET
        elif ':' in addr:
            host, port = addr.split(':')
            if port.isdigit():
                if host == '*':
                    host = ''
                addr = (host, int(port))
                af = socket.AF_INET
        self._sock = socket.socket(af)
        try:
            if server:
                if af == socket.AF_UNIX:
                    ___(os.unlink)(addr)
                self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.bind(addr)
                self.listen(backlog)
            else:
                self.tcpnodelay()
                self.tcpkeepalive()
                self.settimeout(ctmo_s)
                self.connect(addr)
                self.settimeout(None)
        except Exception as e:
            self.close()
            raise type(e)(str(e) + ': ' + str(addr)) from e
        return self

    def close(self, *args):
        ___(self._sock.close)(*args)

    def accept(self, *args):
        s, addr = self._sock.accept(*args)
        ns = type(self)(s)
        ns.send_tmo_s = self.send_tmo_s
        ns.init_recv_tmo_s = self.init_recv_tmo_s
        ns.next_recv_tmo_s = self.next_recv_tmo_s
        ns.is_server = True
        return (ns, addr)

    def setsockopt(self, *args):
        return ___(self._sock.setsockopt)(*args)

    def tcpnodelay(self, setting=1):
        self.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, setting)

    def tcpkeepalive(self, kpidle=180, kpintvl=5, kpcnt=12):
        try:
            avail = int(kpidle > 0)
            self.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, avail)
            if avail == 0:
                return
            for kpopt, kpval in [('ALIVE', kpidle), ('IDLE', kpidle),
                                 ('INTVL', kpintvl), ('CNT', kpcnt)]:
                kpopt = 'TCP_KEEP' + kpopt
                if hasattr(socket, kpopt):
                    self.setsockopt(socket.IPPROTO_TCP, getattr(socket, kpopt), kpval)
        except:
            pass

    def wait_readable(self, tmo_s=None):
        rok, _, _ = select.select([self._sock], [], [], tmo_s)
        return bool(rok)

    def wait_writable(self, tmo_s=None):
        _, wok, _ = select.select([], [self._sock], [], tmo_s)
        return bool(wok)

    def recv_x(self, size):
        # return: (data, rest_size)
        # exception: socket.timeout, socket.error
        data = bytes()
        tmo_s = self.init_recv_tmo_s
        while size > 0:
            if (tmo_s is not None) and (not self.wait_readable(tmo_s)):
                raise socket.timeout('recv timeout: %f' % tmo_s)
            s = self._sock.recv(size)
            if not s:
                return data, size
            size -= len(s)
            data += s
            tmo_s = self.next_recv_tmo_s
        return data, 0

    def send_x(self, buf, size=None):
        # exception: socket.timeout, socket.error
        if size is None:
            size = len(buf)
        buf = memoryview(buf)[:size]
        tmo_s = self.send_tmo_s
        while size > 0:
            if (tmo_s is not None) and (not self.wait_writable(tmo_s)):
                raise socket.timeout('send timeout: %f' % tmo_s)
            n = self._sock.send(buf)
            size -= n
            buf = buf[n:]
            tmo_s = self.send_tmo_s

    def shutdown(self, m):
        try:
            self._sock.shutdown(m)
        except socket.error as e:
            if e.errno != os.errno.ENOTCONN:
                traceback.print_exc()

    def shut_read(self):
        self.shutdown(socket.SHUT_RD)

    def shut_write(self):
        self.shutdown(socket.SHUT_WR)

#----------------------------------------------------------------------------
#                           Simple IPC framework
#----------------------------------------------------------------------------

class NoMoreData(Exception):
    pass

class PackerMeta(type):
    def __new__(mcls, name, bases, dic):
        if _opt.TPP_IPC_DEBUG:
            def wrapper_pack(f):
                def pack(self, msg):
                    tb.pr('  PACK: %.2048s', msg)
                    return f(self, msg)
                return pack
            def wrapper_unpack(f):
                def unpack(self, csock):
                    msg = f(self, csock)
                    tb.pr('UNPACK: %.2048s', msg)
                    return msg
                return unpack
            dic['pack'] = wrapper_pack(dic['pack'])
            dic['unpack'] = wrapper_unpack(dic['unpack'])
        cls = super().__new__(mcls, name, bases, dic)
        return cls

class PackerBase(object, metaclass=PackerMeta):
    def __call__(self):
        return self

    def pack(self, msg):
        raise NotImplementedError('pack')
        
    def unpack(self, csock):
        raise NotImplementedError('unpack')

class PyPacker(PackerBase):
    MAX_PACKED = (1024*1024*16)

    def pack(self, msg):
        s = _pickle.dumps(msg, PICKLE_PROTOCOL)
        n = len(s)
        return struct.pack('<i', n)+s, n+4
        
    def unpack(self, csock):
        s, n = csock.recv_x(4)
        if not s:
            raise NoMoreData('Peer maybe finish sending data')
        if n != 0:
            raise EOFError('Unexpeceted disconnection (error)')
        n, = struct.unpack('<i', s)
        if not (0 < n <= self.MAX_PACKED):
            raise RuntimeError('Packed object size is too large: %d' % n)
        s, n = csock.recv_x(n)
        if n != 0:
            raise EOFError('Unexpected disconnection (error)')
        return _pickle.loads(s)

class JSONPacker(PackerBase):
    MAX_PACKED = (1024*1024*16)

    def pack(self, msg):
        s = json.dumps(msg)
        n = len(s)
        return struct.pack('<i', n)+s, n+4
        
    def unpack(self, csock):
        s, n = csock.recv_x(4)
        if not s:
            raise NoMoreData('Peer maybe finish sending data')
        if n != 0:
            raise EOFError('Unexpeceted disconnection (error)')
        n, = struct.unpack('<i', s)
        if not (0 < n <= self.MAX_PACKED):
            raise RuntimeError('Packed object size is too large: %d' % n)
        s, n = csock.recv_x(n)
        if n != 0:
            raise EOFError('Unexpected disconnection (error)')
        return json.loads(s)

class ServiceBase(object):
    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls)
        self.__ports = []
        return self

    def __call__(self):
        return self

    def link_port(self, port):
        if port not in self.__ports:
            self.__ports.append(port)

    def unlink_port(self, port):
        if port in self.__ports:
            self.__ports.remove(port)

    def sendto_all(self, msg):
        for p in self.__ports[:]:
            p.send(msg)

    def call_handler(self, port, msg):
        fn = 'handle_' + str(msg[0])
        if hasattr(self, fn):
            getattr(self, fn)(port, msg)
        else:
            self.handle_default(port, msg)

    def handle_default(self, port, msg):
        raise NotImplementedError('handle_%s' % str(msg[0]))

    def handle_CONNECTED(self, port):
        pass

    def handle_ACCEPTED(self, port):
        pass

    def handle_DISCONNECTED(self, port):
        pass

    def handle_SOCKERROR(self, port):
        pass

class IPCPort(object):
    _counter = tb.Counter()

    def __new__(cls, service_object, packer, csock):
        self = super().__new__(cls)
        self._service = service_object
        self._packer = packer if packer else PyPacker()
        self._csock = csock
        self._send_queue = tu.Queue()
        self._send_error = None
        self.order = self._counter()
        return self

    def __repr__(self):
        return '<IPCPort#%d>' % self.order

    def _send_loop(self):
        msg = None
        try:
            while True:
                msg = self._send_queue.get()
                if msg is False:
                    return
                s, n = self._packer.pack(msg)
                self._csock.send_x(s, n)
        except Exception as e:
            traceback.print_exc()
            self._send_error = (e, msg)
            self._csock.shut_read()

    def _send_thread(self):
        self._send_loop()
        self._service.unlink_port(self)
        self._csock.shut_write()
        self._send_queue.stop(soon=True)

    def _main_loop(self):
        try:
            while True:
                msg = self._packer.unpack(self._csock)
                self._service.call_handler(self, msg)
        except Exception as e:
            if self._send_error:
                e, msg = self._send_error
                e.args = (e.args[0] + '\n' + str(msg)[:70],) + e.args[1:]
            if isinstance(e, NoMoreData):
                self._service.handle_DISCONNECTED(self)
            else:
                traceback.print_exception(type(e), e, sys.exc_info()[2])
                self._service.handle_SOCKERROR(self)
            return e

    def _main_thread(self, send_thread, fin_func):
        try:
            if self._csock.is_server:
                self._service.link_port(self)
                self._service.handle_ACCEPTED(self)
            else:
                self._service.handle_CONNECTED(self)
            self._main_loop()
        except:
            traceback.print_exc()
        ___(self._send_queue.stop)(soon=False)
        send_thread.join()
        self._service = None
        self._csock.close()
        if fin_func:
            fin_func()

    def start(self, fin_func=None):
        name = '%s#%d' % (type(self._service).__name__, self.order)

        t = tu.Thread(target=self._send_thread)
        t.daemon = True
        t.name = name + '(S)'
        t.start()

        t = tu.Thread(target=self._main_thread, args=(t, fin_func))
        t.daemon = True
        t.name = name + '(M)'
        t.start()

    def send(self, msg):
        self._send_queue.put(msg)

    def __getattr__(self, name):
        def _send(*args):
            msg = [name]
            msg.extend(args)
            return self._send_queue.put(msg)
        return _send

    def send_fin(self, soon=False):
        ___(self._send_queue.stop)(soon)

class Connector(object):
    def __new__(cls, service_object, addr,
                retry=True, recover=False, ctmo_s=None, packer=None):
        self = super().__new__(cls)
        self._service = service_object
        self._addr = addr
        self._retry = retry
        self._retry_itv_s = 5
        self._retry_exc_n = 60 / self._retry_itv_s
        self._recover = recover
        self._ctmo_s = ctmo_s
        self._packer = packer
        return self

    def _main_thread(self):
        retry_n = 0
        fin_func = self.start if self._recover else None
        while True:
            csock = None
            try:
                csock = CSocket(self._addr, ctmo_s=self._ctmo_s)
                self._port = IPCPort(self._service, self._packer, csock)
                self._port.start(fin_func)
                return
            except:
                if csock:
                    csock.close()
                if not self._retry:
                    raise
                if retry_n % self._retry_exc_n == 0:
                    traceback.print_exc()
                time.sleep(self._retry_itv_s)
                retry_n += 1

    def start(self, background=True):
        if background:
            self._thread = tu.Thread(target=self._main_thread)
            self._thread.daemon = True
            self._thread.name = str(self._addr) + '(C)'
            self._thread.start()
        else:
            self._main_thread()
        return self
    
    @property
    def port(self):
        self._thread.join()
        return self._port

class Acceptor(object):
    def __new__(cls, service_factory, addr, packer_factory=None):
        self = super().__new__(cls)
        self._service_factory = service_factory
        if packer_factory is None:
            packer_factory = PyPacker()
        self._packer_factory = packer_factory
        self._addr = addr
        return self

    def _main_thread(self, svr_csock):
        while True:
            csock, _ = svr_csock.accept()
            try:
                IPCPort(self._service_factory(),
                        self._packer_factory(), csock).start()
            except:
                traceback.print_exc()
                csock.close()
            csock = None	# to be gc-ed as soon as possible when csock is closed.

    def start(self, background=True):
        svr_csock = CSocket(self._addr, server=True)
        if background:
            t = tu.Thread(target=self._main_thread, args=(svr_csock,))
            t.daemon = True
            t.name = str(self._addr) + '(A)'
            t.start()
        else:
            self._main_thread(svr_csock)

#----------------------------------------------------------------------------
#                   Simple client object (no event loop)
#----------------------------------------------------------------------------

class SimpleClient(object):
    def __new__(cls, addr, packer=None):
        self = super().__new__(cls)
        self._addr = addr
        self._packer = packer if packer else PyPacker()
        return self

    def start(self):
        self._csock = CSocket(self._addr) 

    def recv(self):
        return self._packer.unpack(self._csock)
        
    def send(self, msg):
        s, n = self._packer.pack(msg)
        self._csock.send_x(s, n)
        
    def __getattr__(self, name):
        def _send(*args):
            msg = [name]
            msg.extend(args)
            return self.send(msg)
        return _send

    def send_fin(self):
        self._csock.shut_write()
        
    def close(self):
        self._csock.close()

#----------------------------------------------------------------------------
#----------------------------------------------------------------------------

__all__ = []
