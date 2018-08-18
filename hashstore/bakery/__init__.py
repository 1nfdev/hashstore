#!/usr/bin/env python
# -*- coding: utf-8 -*-

import abc

import threading
from datetime import datetime

from hashstore.utils import Jsonable
from io import BytesIO
from hashlib import sha256, sha1
import os
import hashstore.utils as utils
import base64
from hashstore.utils.base_x import base_x
import json
import enum
from typing import (
    Union, Optional, Any, Callable, Tuple,
    List, Iterable, Dict, IO)
import logging
from hashstore.utils import path_split_all
from hashstore.utils.file_types import guess_name, file_types, HSB
from hashstore.utils.smattr import JsonWrap, SmAttr, MoldedTable

log = logging.getLogger(__name__)

B62 = base_x(62)

B36 = base_x(36)

MAX_NUM_OF_SHARDS = 8192

class Hasher:
    def __init__(self, data: Optional[bytes] = None)->None:
        self.sha = sha256()
        if data is not None:
            self.update(data)

    def update(self, b: bytes):
        self.sha.update(b)

    def digest(self):
        return self.sha.digest()

class ContentAddress(utils.Stringable, utils.EnsureIt):
    """
    case-insensitive address that used to store blobs
    of data in file system and in db

    >>> a46 = Cake.from_bytes(b'a' * 46)
    >>> str(a46)
    '2lEWHXV2XeYyZnKNyQyGPt4poJhV7VeYCfeszHnLyFtx'
    >>> from_c = ContentAddress(a46)
    >>> str(from_c)
    '2jr7e7m1dz6uky4soq7eaflekjlgzwsvech6skma3ojl4tc0zv'
    >>> from_id = ContentAddress(str(from_c))
    >>> str(from_id)
    '2jr7e7m1dz6uky4soq7eaflekjlgzwsvech6skma3ojl4tc0zv'
    >>> from_id
    ContentAddress('2jr7e7m1dz6uky4soq7eaflekjlgzwsvech6skma3ojl4tc0zv')
    >>> from_id.hash_bytes == from_c.hash_bytes
    True
    >>> from_id.match(a46)
    True
    >>> a47 = Cake.from_bytes(b'a' * 47)
    >>> str(a47)
    '21EUi09ZvZAelgu02ANS9dSpK9oPsERF0uSpfEEZcdMx'
    >>> from_id.match(a47)
    False
    """

    def __init__(self, h: Union['Cake', Hasher, str])->None:
        if isinstance(h, Hasher):
            self.hash_bytes = h.digest()
            self._id = B36.encode(self.hash_bytes)
        elif isinstance(h, Cake):
            self.hash_bytes = h.hash_bytes()
            self._id = B36.encode(self.hash_bytes)
        else:
            self._id = h.lower()
            self.hash_bytes = B36.decode(self._id)
        self.shard_name = shard_name_int(shard_num(self.hash_bytes))

    def __str__(self):
        return self._id

    def __repr__(self):
        return f"{type(self).__name__}({repr(self._id)})"

    def match(self, cake):
        return cake.hash_bytes() == self.hash_bytes

    def __eq__(self, other):
        return isinstance(other, ContentAddress) and \
               self._id == other._id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._id)



def shard_name_int(num: int):
    """
    >>> shard_name_int(0)
    '0'
    >>> shard_name_int(1)
    '1'
    >>> shard_name_int(8000)
    '668'
    """
    return B36.encode_int(num)


def decode_shard(name: str):
    """
    >>> decode_shard('0')
    0
    >>> decode_shard('668')
    8000
    """
    return B36.decode_int(name)


def is_it_shard(shard_name: str, max_num:int = MAX_NUM_OF_SHARDS)->bool:
    """
    Test if name can represent shard

    >>> is_it_shard('668')
    True
    >>> is_it_shard('6bk')
    False
    >>> is_it_shard('0')
    True

    logic should not be sensitive for upper case:
    >>> is_it_shard('5BK')
    True
    >>> is_it_shard('6BK')
    False
    >>> is_it_shard('')
    False
    >>> is_it_shard('.5k')
    False
    >>> is_it_shard('abcd')
    False
    """
    shard_num = -1
    if shard_name == '' or len(shard_name) > 3:
        return False
    try:
        shard_num = decode_shard(shard_name.lower())
    except:
        pass
    return shard_num >= 0 and shard_num < max_num


def shard_num(hash_bytes: bytes, base: int = MAX_NUM_OF_SHARDS):
    b1, b2 = hash_bytes[:2]
    return (b1 * 256 + b2) % base


class Content(Jsonable):
    """
    >>> c=Content(size=3, created_dt="some time ago", file_type="TXT", mime='text/plain', data='abc')
    >>> json.dumps(c.to_json(),sort_keys=True)
    '{"created_dt": "some time ago", "mime": "text/plain", "size": 3, "type": "TXT"}'
    """
    JSONABLE_FIELDS = [(k+':'+k).split(':')[0:2] for k in
                      'size created_dt file_type:type mime'.split()]

    def __init__(self, data=None, file=None, stream_fn=None,
                 mime=None, file_type=None, created_dt=None,
                 size=None, role=None, lookup=None):
        self.mime = mime
        self.file_type = file_type
        if data is None and file is None and stream_fn is None:
            raise AssertionError('define data or file or stream_fn')
        self.data = data
        self.file = file
        self.stream_fn = stream_fn
        self.role = role
        if lookup is None:
            self.size = size
            self.created_dt = created_dt
        else:
            self.size = lookup.size
            self.created_dt = lookup.created_dt

    def guess_file_type(self, file=None):
        if file is None:
            file = self.file
        if self.file_type is None:
            if file is not None:
                self.file_type = guess_name(file)
        if self.file_type is not None and self.mime is None:
            self.mime = file_types[self.file_type].mime
        return self

    def set_role(self, copy_from):
        role = None
        if isinstance(copy_from, CakeRole):
            role = copy_from
        else:
            if hasattr(copy_from, 'role'):
                role = copy_from.role
        if role is not None:
            self.role = role
            if self.file_type is None:
                if self.role == CakeRole.NEURON:
                    self.file_type = HSB
        return self.guess_file_type()

    def has_data(self) -> bool:
        return self.data is not None

    def get_data(self) -> bytes:
        return self.data if self.has_data() else self.stream().read()

    def stream(self)-> IO[bytes]:
        if self.has_data():
            return BytesIO(self.data)
        elif self.file is not None:
            return open(self.file, 'rb')
        else:
            return self.stream_fn()

    def has_file(self):
        return self.file is not None

    def open_fd(self):
        return os.open(self.file,os.O_RDONLY)

    def to_json(self):
        return { n:getattr(self,k) for k,n in self.JSONABLE_FIELDS}


class CakeRole(utils.CodeEnum):
    SYNAPSE = (0,)
    NEURON = (1,)


class EventState(utils.CodeEnum):
    NEW = enum.auto()
    IN_PROCESS = enum.auto()
    SUCCESS = enum.auto()
    FAIL = enum.auto()


class Event(SmAttr):
    '''
    >>> EventState.NEW
    <EventState.NEW: 1>
    >>> EventState("IN_PROCESS")
    <EventState.IN_PROCESS: 2>
    >>> EventState(2)
    <EventState.IN_PROCESS: 2>
    >>> EventState("Q")
    Traceback (most recent call last):
    ...
    KeyError: 'Q'
    >>> e = Event()
    >>> e.to_json()
    {'state': 'NEW', 'input': {}, 'output': {}, 'codebase': None, 'additional_data': None}
    >>> q = Event(e.to_json())
    >>> q.state
    <EventState.NEW: 1>
    >>> str(q)
    '{"additional_data": null, "codebase": null, "input": {}, "output": {}, "state": "NEW"}'
    '''
    state: EventState = EventState.NEW
    input: Dict[str,Any]
    output: Dict[str,Any]
    codebase: Optional[str]
    additional_data: Optional[str]


_IS_PORTAL, _IS_VTREE, _IS_RESOLVED = (
    "is_portal", "is_vtree", "is_resolved" )


class CakeType(utils.CodeEnum):
    INLINE = (0, None, None)
    SHA256 = (1, None, None, _IS_RESOLVED)
    PORTAL = (2, None, None, _IS_PORTAL)
    VTREE = (3, None, None, _IS_VTREE)
    DMOUNT = (4, None, None, _IS_PORTAL)
    EVENT = (5, CakeRole.SYNAPSE, Event, _IS_RESOLVED)
    DAG_STATE = (6, CakeRole.NEURON, None, _IS_VTREE)
    JSON_WRAP = (7, CakeRole.SYNAPSE, JsonWrap, _IS_RESOLVED )

    def __init__(self,
                 code:int,
                 implied_role:Optional[CakeRole],
                 json_type:Optional[type],
                 *modifiers:str) -> None:
        utils.CodeEnum.__init__(self, code)
        self.implied_role = implied_role
        self.json_type = json_type
        self.is_vtree = _IS_VTREE in modifiers
        self.is_portal = self.is_vtree or _IS_PORTAL in modifiers
        self.is_resolved = _IS_RESOLVED in modifiers



def portal_from_name(n):
    """
    >>> portal_from_name('')
    <CakeType.PORTAL: 2>
    >>> portal_from_name('PORTAL')
    <CakeType.PORTAL: 2>
    >>> portal_from_name('DMOUNT')
    <CakeType.DMOUNT: 4>
    >>> portal_from_name('VTREE')
    <CakeType.VTREE: 3>
    >>> portal_from_name('INLINE')
    Traceback (most recent call last):
    ...
    ValueError: not a portal type:INLINE
    """
    if n is None or n == '':
        return CakeType.PORTAL
    ct = CakeType[n]
    if ct.is_portal :
        return ct
    raise ValueError('not a portal type:'+n)


def assert_key_structure(expected, type):
    if type != expected:
        raise AssertionError("has to be %r and not %r"
                             % (expected, type))


inline_max_bytes=32


def nop_on_chunk(chunk:bytes)->None:
    """
    Does noting

    >>> nop_on_chunk(b'')

    :param read_buffer: takes bytes
    :return: does nothing
    """
    pass


def _header(type, role):
    """
    >>> _header(CakeType.INLINE,CakeRole.SYNAPSE)
    0
    >>> _header(CakeType.SHA256,CakeRole.NEURON)
    3
    """
    return (type.code << 1)|role.code


def pack_in_bytes(type, role, data_bytes):
    r"""
    >>> pack_in_bytes(CakeType.INLINE,CakeRole.SYNAPSE, b'ABC')
    b'\x00ABC'
    >>> pack_in_bytes(CakeType.SHA256,CakeRole.NEURON, b'XYZ')
    b'\x03XYZ'
    """
    return bytes([_header(type, role)]) + data_bytes


def process_stream(fd:IO[bytes],
                   on_chunk:Callable[[bytes], None]=nop_on_chunk,
                   chunk_size:int=65355
                   )->Tuple[bytes,Optional[bytes]]:
    """
    process stream to calculate hash, length of data,
    and if it is smaller then hash size, holds on to stream
    content to use it instead of hash.


    :param fd: stream
    :param on_chunk: function  called on every chunk
    :return: (<hash>, Optional[<inline_data>])
    """
    inline_data = bytes()
    hasher = Hasher()
    length = 0
    while True:
        chunk = fd.read(chunk_size)
        if len(chunk) <= 0:
            break
        length += len(chunk)
        hasher.update(chunk)
        on_chunk(chunk)
        if length <= inline_max_bytes:
            inline_data += chunk
    fd.close()
    return (hasher.digest(),
            None if length > inline_max_bytes else inline_data)


class Cake(utils.Stringable, utils.EnsureIt):
    """
    Stands for Content Address Key.

    Content addressing scheme using SHA256. For small
    content ( <=32 bytes) data is embeded  in key.  Header byte is
    followed by hash digest or inlined data. header byte split in two
    halves: `CakeType` and `CakeRole`. Base62 encoding is
    used to encode bytes.

    >>> CakeRole('SYNAPSE') == CakeRole.SYNAPSE
    True
    >>> CakeRole('SYNAPSE')
    <CakeRole.SYNAPSE: 0>
    >>> list(CakeType) #doctest: +NORMALIZE_WHITESPACE
    [<CakeType.INLINE: 0>, <CakeType.SHA256: 1>, <CakeType.PORTAL: 2>,
     <CakeType.VTREE: 3>, <CakeType.DMOUNT: 4>, <CakeType.EVENT: 5>,
     <CakeType.DAG_STATE: 6>, <CakeType.JSON_WRAP: 7>]

    >>> short_content = b'The quick brown fox jumps over'
    >>> short_k = Cake.from_bytes(short_content)
    >>> short_k.type
    <CakeType.INLINE: 0>
    >>> short_k.has_data()
    True
    >>> short_k.data() is not None
    True
    >>> short_k.data() == short_content
    True
    >>> str(short_k)
    '01aMUQDApalaaYbXFjBVMMvyCAMfSPcTojI0745igi'

    Longer content is hashed with SHA256:

    >>> longer_content = b'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    >>> longer_k = Cake.from_bytes(longer_content)
    >>> longer_k.type
    <CakeType.SHA256: 1>
    >>> longer_k.has_data()
    False
    >>> longer_k.data() is None
    True
    >>> str(longer_k)
    '2xgkyws1ZbSlXUvZRCSIrjne73Pv1kmYArYvhOrTtqkX'
    >>> len(longer_k.hash_bytes())
    32
    >>> len(longer_k.digest())
    32
    >>> len(set([hash(longer_k) , hash(longer_k)]))
    1

    Global Unique ID can be generated, it is 32 byte
    random sequence packed in same way.

    >>> guid = Cake.new_portal()
    >>> guid.type
    <CakeType.PORTAL: 2>
    >>> len(str(guid))
    44
    """
    def __init__(self,
                 s:Optional[str],
                 data:Optional[bytes]=None,
                 type:Optional[CakeType]=None,
                 role:Optional[CakeRole]=None
                 )->None:
        if type is not None:
            if data is None or role is None:
                raise AssertionError(f'data={data} and role={role} '
                                     f'has to be defined')
            self._data = data
            self.type = type
            self.role = role
        else:
            decoded = B62.decode(utils.ensure_string(s))
            header = decoded[0]
            self._data = decoded[1:]
            self.type = CakeType.find_by_code(header >> 1)
            self.role = CakeRole.find_by_code(header & 1)
        if not(self.has_data()):
            if len(self._data) != 32:
                raise AssertionError('invalid CAKey: %r ' % s)

    def shard_num(self, base=MAX_NUM_OF_SHARDS)->int:
        """
        >>> Cake('0').shard_num()
        0
        >>> Cake.from_bytes(b' ').shard_num()
        32
        >>> Cake('2xgkyws1ZbSlXUvZRCSIrjne73Pv1kmYArYvhOrTtqkX').shard_num()
        5937

        """
        l = len(self._data)
        if l >= 2:
            return shard_num(self._data, base)
        elif l == 1:
            return self._data[0]
        else:
            return 0

    def shard_name(self, base: int=MAX_NUM_OF_SHARDS)->str:
        return shard_name_int(self.shard_num(base))

    @staticmethod
    def from_digest_and_inline_data(digest: bytes,
                                    buffer: Optional[bytes],
                                    role: CakeRole=CakeRole.SYNAPSE
                                    )->'Cake':
        if buffer is not None and len(buffer) <= inline_max_bytes:
            return Cake(None, data=buffer, type=CakeType.INLINE,
                        role=role)
        else:
            return Cake(None, data=digest, type=CakeType.SHA256,
                        role=role)

    @staticmethod
    def from_stream(fd: IO[bytes],
                    role: CakeRole=CakeRole.SYNAPSE
                    )->'Cake':
        digest, inline_data = process_stream(fd)
        return Cake.from_digest_and_inline_data(digest, inline_data,
                                                role=role)

    @staticmethod
    def from_bytes(s, role: CakeRole=CakeRole.SYNAPSE)->'Cake':
        return Cake.from_stream(BytesIO(s), role=role)

    @staticmethod
    def from_file(file, role:CakeRole=CakeRole.SYNAPSE)->'Cake':
        return Cake.from_stream(open(file, 'rb'), role=role)

    @staticmethod
    def new_portal(role:CakeRole=None, type:CakeType=None)->'Cake':
        if role is None:
            role = CakeRole.SYNAPSE
        if type is None:
            type = CakeType.PORTAL
        cake = Cake(None, data=os.urandom(32), type=type, role=role)
        cake.assert_portal()
        return cake

    def transform_portal(self,
                         role:CakeRole=None,
                         type:CakeType=None
                         )->'Cake':
        self.assert_portal()
        if type is None:
            type = self.type
        if role is None:
            role = self.role
        if type == self.type and role == self.role:
            return self
        return Cake(None, data=self._data, type=type, role=role)

    def has_data(self)->bool:
        return self.type == CakeType.INLINE

    def data(self)->Optional[bytes]:
        return self._data if self.has_data() else None

    def digest(self)->bytes:
        if not(hasattr(self, '_digest')):
            if self.has_data():
                self._digest = Hasher(self._data).digest()
            else:
                self._digest = self._data
        return self._digest

    def is_immutable(self)->bool:
        return self.has_data() or self.type.is_resolved

    def assert_portal(self)->None:
        if not self.type.is_portal:
            raise AssertionError('has to be a portal: %r' % self)

    def hash_bytes(self)->bytes:
        """
        :raise AssertionError when Cake is not hash based
        :return: hash in bytes
        """
        if not self.type.is_resolved:
            raise AssertionError(f"Not-hash {self.type} {self}")
        return self._data

    def __str__(self)->str:
        in_bytes = pack_in_bytes(self.type, self.role,
                                 self._data)
        return B62.encode(in_bytes)

    def __repr__(self)->str:
        return f"Cake({str(self)!r})"

    def __hash__(self)->int:
        if not(hasattr(self, '_hash')):
            self._hash = hash(self.digest())
        return self._hash

    def __eq__(self, other)->bool:
        if not isinstance(other, Cake):
            return False
        return self._data == other._data and \
               self.type == other.type and \
               self.role == other.role

    def __ne__(self, other)->bool:
        return not self.__eq__(other)


class HasCake(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def cake(self)->Cake:
        raise NotImplementedError('subclasses must override')


class CakedBytes(HasCake):

    @abc.abstractmethod
    def in_bytes(self)->bytes:
        raise NotImplementedError('subclasses must override')


class Str2Bytes(metaclass=abc.ABCMeta):

    def in_bytes(self)->bytes:
        return str(self).encode('utf-8')


CakedBytes.register(MoldedTable)

class PatchAction(Jsonable, enum.Enum):
    update = +1
    delete = -1

    @classmethod
    def factory(cls):
        return lambda s: cls[s]

    def __str__(self):
        return self.name

    def to_json(self):
        return str(self)


class CakeRack(utils.Jsonable, CakedBytes):
    """
    sorted dictionary of names and corresponding Cakes

    >>> short_k = Cake.from_bytes(b'The quick brown fox jumps over')
    >>> longer_k = Cake.from_bytes(b'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.')

    >>> cakes = CakeRack()
    >>> cakes['short'] = short_k
    >>> cakes['longer'] = longer_k
    >>> len(cakes)
    2

    >>> cakes.keys()
    ['longer', 'short']
    >>> str(cakes.cake())
    '3fqJUOtUYjGCs3cWuPum5CwXtyyeJPRRp3gJ3A9wg3uS'
    >>> cakes.size()
    117
    >>> cakes.content()
    '[["longer", "short"], ["2xgkyws1ZbSlXUvZRCSIrjne73Pv1kmYArYvhOrTtqkX", "01aMUQDApalaaYbXFjBVMMvyCAMfSPcTojI0745igi"]]'
    >>> cakes.get_name_by_cake("2xgkyws1ZbSlXUvZRCSIrjne73Pv1kmYArYvhOrTtqkX")
    'longer'
    """
    def __init__(self,o:Any=None)->None:
        self.store: Dict[str,Optional[Cake]] = {}
        self._clear_cached()
        if o is not None:
            self.parse(o)

    def _clear_cached(self):
        self._inverse: Any = None
        self._cake: Any = None
        self._content: Any = None
        self._size: Any = None
        self._in_bytes: Any = None
        self._defined: Any = None

    def inverse(self)->Dict[Optional[Cake],str]:
        if self._inverse is None:
            self._inverse = {v: k for k, v in self.store.items()}
        return self._inverse

    def cake(self)->Cake:
        if self._cake is None:
            in_bytes = self.in_bytes()
            self._cake = Cake.from_digest_and_inline_data(
                Hasher(in_bytes).digest(),
                in_bytes,
                role=CakeRole.NEURON)
        return self._cake

    def content(self)->str:
        if self._content is None:
            self._content = str(self)
        return self._content

    def in_bytes(self)->bytes:
        if self._in_bytes is None:
            self._in_bytes = utils.ensure_bytes(self.content())
        return self._in_bytes

    def size(self)->int:
        if self._size is None:
            self._size = len(self.in_bytes())
        return self._size

    def is_defined(self)->bool:
        if self._defined is None:
            self._defined = all(
                v is not None for v in self.store.values())
        return self._defined

    def parse(self, o:Any)->'CakeRack':
        self._clear_cached()
        if isinstance(o, str):
            names, cakes = json.loads(o)
        elif type(o) in [list, tuple] and len(o) == 2:
            names, cakes = o
        else:
            names, cakes = json.load(o)
        self.store.update(zip(names, map(Cake.ensure_it_or_none, cakes)))
        return self

    def merge(self,
              previous:'CakeRack'
              )->Iterable[Tuple[PatchAction,str,Optional[Cake]]]:
        """
        >>> o1 = Cake.from_bytes(b'The quick brown fox jumps over')
        >>> o2v1 = Cake.from_bytes(b'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.')
        >>> o2v2 = Cake.from_bytes(b'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. v2')
        >>> o3 = CakeRack().cake()
        >>> r1 = CakeRack()
        >>> r1['o1']=o1
        >>> r1['o2']=o2v1
        >>> r1['o3']=None
        >>> r2 = CakeRack()
        >>> r2['o1']=o1
        >>> r2['o2']=o2v2
        >>> r2['o3']=o3
        >>> list(r2.merge(r1))
        [(<PatchAction.update: 1>, 'o2', Cake('2KLrqwGfNUC75Zk46B8SIbyYQFcm4FoW8UgOd9xnkKD9'))]
        >>> list(r1.merge(r2))
        [(<PatchAction.update: 1>, 'o2', Cake('2xgkyws1ZbSlXUvZRCSIrjne73Pv1kmYArYvhOrTtqkX'))]
        >>> r1['o1'] = None
        >>> list(r2.merge(r1)) #doctest: +NORMALIZE_WHITESPACE
        [(<PatchAction.delete: -1>, 'o1', None),
        (<PatchAction.update: 1>, 'o1', Cake('01aMUQDApalaaYbXFjBVMMvyCAMfSPcTojI0745igi')),
        (<PatchAction.update: 1>, 'o2', Cake('2KLrqwGfNUC75Zk46B8SIbyYQFcm4FoW8UgOd9xnkKD9'))]
        >>> list(r1.merge(r2)) #doctest: +NORMALIZE_WHITESPACE
        [(<PatchAction.delete: -1>, 'o1', None),
        (<PatchAction.update: 1>, 'o1', None),
        (<PatchAction.update: 1>, 'o2', Cake('2xgkyws1ZbSlXUvZRCSIrjne73Pv1kmYArYvhOrTtqkX'))]
        >>> del r1["o2"]
        >>> list(r2.merge(r1)) #doctest: +NORMALIZE_WHITESPACE
        [(<PatchAction.delete: -1>, 'o1', None),
        (<PatchAction.update: 1>, 'o1', Cake('01aMUQDApalaaYbXFjBVMMvyCAMfSPcTojI0745igi')),
        (<PatchAction.update: 1>, 'o2', Cake('2KLrqwGfNUC75Zk46B8SIbyYQFcm4FoW8UgOd9xnkKD9'))]
        >>> list(r1.merge(r2)) #doctest: +NORMALIZE_WHITESPACE
        [(<PatchAction.delete: -1>, 'o1', None),
        (<PatchAction.update: 1>, 'o1', None),
        (<PatchAction.delete: -1>, 'o2', None)]
        """
        for k in sorted(list(set(self.keys() + previous.keys()))):
            if k not in self and k in previous:
                yield PatchAction.delete, k, None
            else:
                v = self[k]
                neuron = self.is_neuron(k)
                if k in self and k not in previous:
                    yield PatchAction.update, k, v
                else:
                    prev_v = previous[k]
                    prev_neuron = previous.is_neuron(k)
                    if v != prev_v:
                        if neuron == True and prev_neuron == True:
                            continue
                        if prev_neuron == neuron:
                            yield PatchAction.update, k, v
                        else:
                            yield PatchAction.delete, k, None
                            yield PatchAction.update, k, v

    def is_neuron(self, k)->Optional[bool]:
        v = self.store[k]
        return v is None or v.role == CakeRole.NEURON

    def __iter__(self)->Iterable[str]:
        return iter(self.keys())

    def __setitem__(self, k:str, v:Union[Cake,str,None])->None:
        self._clear_cached()
        self.store[k] = Cake.ensure_it_or_none(v)

    def __delitem__(self, k:str):
        self._clear_cached()
        del self.store[k]

    def __getitem__(self, k:str)->Optional[Cake]:
        return self.store[k]

    def __len__(self)->int:
        return len(self.store)

    def __contains__(self, k:str)->bool:
        return k in self.store

    def get_name_by_cake(self, k:Union[Cake,str]):
        return self.inverse()[Cake.ensure_it(k)]

    def keys(self)->List[str]:
        names = list(self.store.keys())
        names.sort()
        return names

    def get_cakes(self, names=None)->List[Optional[Cake]]:
        if names is None:
            names = self.keys()
        return [self.store[k] for k in names]

    def to_json(self)->Tuple[List[str],List[Optional[Cake]]]:
        keys = self.keys()
        return (keys, self.get_cakes(keys))


class CakePath(utils.Stringable, utils.EnsureIt):
    """
    >>> root = CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF')
    >>> root
    CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF/')
    >>> root.root
    Cake('dCYNBHoPFLCwpVdQU5LhiF0i6U60KF')
    >>> root.root.role
    <CakeRole.NEURON: 1>
    >>> root.root.type
    <CakeType.INLINE: 0>
    >>> root.root.data()
    b'[["b.text"], ["06wO"]]'
    >>> absolute = CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF/b.txt')
    >>> absolute
    CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF/b.txt')
    >>> relative = CakePath('y/z')
    >>> relative
    CakePath('y/z')
    >>> relative.make_absolute(absolute)
    CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF/b.txt/y/z')

    `make_absolute()` have no effect to path that already
    absolute

    >>> p0 = CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF/r/f')
    >>> p0.make_absolute(absolute)
    CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF/r/f')
    >>> p1 = p0.parent()
    >>> p2 = p1.parent()
    >>> p1
    CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF/r')
    >>> p2
    CakePath('/dCYNBHoPFLCwpVdQU5LhiF0i6U60KF/')
    >>> p2.parent()
    >>> p0.path_join()
    'r/f'
    >>> p1.path_join()
    'r'
    >>> p2.path_join()
    ''
    >>> str(CakePath('q/x/палка_в/колесе.bin'))
    'q/x/палка_в/колесе.bin'
    """
    def __init__(self, s, _root = None, _path = []):
        if s is  None:
            self.root = _root
            self.path = _path
        else:
            split = path_split_all(s, ensure_trailing_slash=False)
            if len(split) > 0 and split[0] == '/' :
                self.root = Cake(split[1])
                self.path = split[2:]
            else:
                self.root = None
                self.path = split

    def child(self, name):
        path = list(self.path)
        path.append(name)
        return CakePath(None, _path=path, _root=self.root)

    def parent(self):
        if self.relative() or len(self.path) == 0 :
            return None
        return CakePath(None, _path=self.path[:-1], _root=self.root)

    def next_in_relative_path(self):
        if not self.relative():
            raise AssertionError("only can be applied to relative")
        l = len(self.path)
        reminder = None
        if l < 1:
            next= None
        else:
            next=self.path[0]
            if l > 1:
                reminder = CakePath(None, _path=self.path[1:])
        return next,reminder

    def relative(self):
        return self.root is None

    def is_root(self):
        return not self.relative() and len(self.path) == 0

    def make_absolute(self, current_cake_path):
        if self.relative():
            path = list(current_cake_path.path)
            path.extend(self.path)
            return CakePath( None ,
                             _root=current_cake_path.root,
                             _path=path)
        else:
            return self

    def __str__(self):
        if self.relative():
            return self.path_join()
        else:
            return f'/{str(self.root)}/{self.path_join()}'

    def path_join(self):
        return '/'.join(self.path)

    def filename(self):
        l = len(self.path)
        if l > 0 and self.path[l-1]:
            return self.path[l-1]


def cake_or_path(s, relative_to_root=False):
    if isinstance(s, Cake) or isinstance(s, CakePath):
        return s
    elif s[:1] == '/':
        return CakePath(s)
    elif relative_to_root and '/' in s:
        return CakePath('/'+s)
    else:
        return Cake(s)


def ensure_cakepath(s):
    if not(isinstance(s, (Cake,CakePath) )):
        s = cake_or_path(s)
    if isinstance(s, Cake):
        return CakePath(None, _root=s)
    else:
        return s


class HashSession(metaclass=abc.ABCMeta):

    @staticmethod
    def get() -> 'HashSession':
        return threading.local().hash_ctx

    @staticmethod
    def set(ctx: 'HashSession') -> None:
        threading.local().hash_ctx = ctx

    @staticmethod
    def close() -> None:
        l = threading.local()
        if hasattr(l, 'hash_ctx'):
            l.hash_ctx.close()
            l.hash_ctx = None

    @abc.abstractmethod
    def get_content(self, cake_or_path) -> 'Content':
        raise NotImplementedError('subclasses must override')


class PathResolved(SmAttr):
    path: CakePath
    resolved: Optional[Cake]


class PathInfo(SmAttr):
    name: str
    role: CakeRole
    size: int
    created_dt: datetime
    file_type: str
    mime: str
    resolved: Optional[Cake]


class LookupInfo(PathInfo):
    path: CakePath
    data: Optional[bytes]
    stream_fn: Optional[Callable[[],IO[bytes]]]
    file: Optional[str]

    def has_data(self) -> bool:
        return self.data is not None

    def get_data(self) -> bytes:
        return self.stream().read() if self.data is None else self.data

    def stream(self) -> IO[bytes]:
        if self.data is not None:
            return BytesIO(self.data)
        elif self.file is not None:
            return open(self.file, 'rb')
        elif self.stream_fn is not None:
            return self.stream_fn()
        else:
            raise AssertionError(f'cannot stream: {self.path}')

    def has_file(self):
        return self.file is not None

    def open_fd(self):
        return os.open(self.file, os.O_RDONLY)


"""
@HashSession
    def get_info(self, cake_path) -> PathInfo
    def get_content(self, cake_path) -> PathInfo

    def write_content(self, fp, chunk_size=65355):
    def store_directories(self, directories:Dict[Cake,CakeRack]):
    def edit_portal(self, cake_path, cake):
    def query(self, cake_path, include_path_info:bool=False) -> CakeRack:
    def edit_portal_tree(self, 
            files:List[PatchAction,Cake,Optional[Cake]], 
            asof_dt:datetime=None):
            
@guest
    def info(self):
    def login(self, email, passwd, client_id=None):
    def authorize(self, cake, pts):
    def get_content(self, cake_or_path):

@user
    def logout(self):
    def write_content(self, fp, chunk_size=65355):
    def store_directories(self, directories):
    def create_portal(self, portal_id, cake):
    def edit_portal(self, portal_id, cake):
    def list_acls(self):
    def edit_portal_tree(self, files, asof_dt=None):
    def delete_in_portal_tree(self, cake_path, asof_dt = None):
    def get_portal_tree(self, portal_id, asof_dt=None):
    def grant_portal(self, portal_id, grantee, permission_type):
    def delete_portal(self, portal_id):

@admin
    def add_user(self, email, ssha_pwd, full_name = None):
    def remove_user(self, user_or_email):
    def add_acl(self, user_or_email, acl):
    def remove_acl(self, user_or_email, acl):

"""


class MoldedCake(Cake):

    def get_instance(self):
        data = HashSession.get().get_content(self).get_data()
        return self.__smattr__(json.loads(data))


class EventCake(MoldedCake):
    __smattr__= Event

class JsonWrapCake(MoldedCake):
    __smattr__ = JsonWrap

_SSHA_MARK= '{SSHA}'


class SaltedSha(utils.Stringable, utils.EnsureIt):
    """
    >>> ssha = SaltedSha.from_secret('abc')
    >>> ssha.check_secret('abc')
    True
    >>> ssha.check_secret('zyx')
    False
    >>> ssha = SaltedSha('{SSHA}5wRHUQxypw7C4AVd4yZRW/8pXy2Gwvh/')
    >>> ssha.check_secret('abc')
    True
    >>> ssha.check_secret('Abc')
    False
    >>> ssha.check_secret('zyx')
    False
    >>> str(ssha)
    '{SSHA}5wRHUQxypw7C4AVd4yZRW/8pXy2Gwvh/'
    >>> ssha
    SaltedSha('{SSHA}5wRHUQxypw7C4AVd4yZRW/8pXy2Gwvh/')

    """
    def __init__( self,
                  s:Optional[str],
                  _digest: bytes=None,
                  _salt: bytes=None)->None:
        if s is None:
            self.digest = _digest
            self.salt = _salt
        else:
            len_of_mark = len(_SSHA_MARK)
            if _SSHA_MARK == s[:len_of_mark]:
                challenge_bytes = base64.b64decode(s[len_of_mark:])
                self.digest = challenge_bytes[:20]
                self.salt = challenge_bytes[20:]
            else:
                raise AssertionError('cannot init: %r' % s)

    @staticmethod
    def from_secret(secret):
        secret = utils.ensure_bytes(secret)
        h = sha1(secret)
        salt = os.urandom(4)
        h.update(salt)
        return SaltedSha(None, _digest=h.digest(), _salt=salt)

    def check_secret(self, secret):
        secret = utils.ensure_bytes(secret)
        h = sha1(secret)
        h.update(self.salt)
        return self.digest == h.digest()

    def __str__(self):
        encode = base64.b64encode(self.digest + self.salt)
        return _SSHA_MARK + utils.ensure_string(encode)


class InetAddress(utils.Stringable, utils.EnsureIt):

    def __init__(self, k):
        self.k = k

    def __str__(self):
        return self.k


class RemoteError(ValueError): pass


class CredentialsError(ValueError): pass


class NotAuthorizedError(ValueError): pass


class NotFoundError(ValueError): pass


RESERVED_NAMES = ('_', '~', '-')


def check_bookmark_name(name):
    """
    >>> check_bookmark_name('a')
    >>> check_bookmark_name('_')
    Traceback (most recent call last):
    ...
    ValueError: Reserved name: _
    >>> check_bookmark_name('a/h')
    Traceback (most recent call last):
    ...
    ValueError: Cannot contain slash: a/h
    """
    if '/' in name:
        raise ValueError('Cannot contain slash: ' +name)
    if name in RESERVED_NAMES:
        raise ValueError('Reserved name: '+name)