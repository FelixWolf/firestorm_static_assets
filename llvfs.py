#!/usr/bin/env python3
# @file llvfs.py
# @brief LLVFS manipulator
# 
# $LicenseInfo:firstyear=2020&license=viewerlgpl$
# Viewer utilities
# Copyright (C) 2010, Linden Research, Inc.
# Copyright (c) 2020, Chaser Zaks
# (This is technically also (C) to LL as it references the llvfs sources.)
# 
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation;
# version 2.1 of the License only.
# 
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
# 
# $/LicenseInfo$


import argparse
import struct
import os
import uuid
import datetime
import random
import hashlib
import math

def Singleton(cls):
    return cls()

@Singleton
class AT:
    asset_type_names = ("description", "typename", "humanname", "link", "fetch", "know")
    description = 0
    type = 1
    name = 2
    linkable = 3
    fetchable = 4
    knowable = 5
    asset_types = {
        #ID		 DESCRIPTION		TYPE NAME	HUMAN NAME			CAN LINK?	CAN FETCH?	CAN KNOW?
        #       |------------------|-----------|-------------------|----------|------------|---------|
        0:  	("TEXTURE",			"texture",	"texture",			True,		False,		True),
        1:  	("SOUND",			"sound",	"sound",			True,		True,		True),
        2:  	("CALLINGCARD",		"callcard",	"calling card",		True,		False,		False),
        3:  	("LANDMARK",		"landmark",	"landmark",			True,		True,		True),
        4:  	("SCRIPT",			"script",	"legacy script",	True,		False,		False),
        5:  	("CLOTHING",		"clothing",	"clothing",			True,		True,		True),
        6:  	("OBJECT",			"object",	"object",			True,		False,		False),
        7:  	("NOTECARD",		"notecard",	"note card",		True,		False,		True),
        8:  	("CATEGORY",		"category",	"folder",			True,		False,		False),
        10: 	("LSL_TEXT",		"lsltext",	"lsl2 script",		True,		False,		False),
        11: 	("LSL_BYTECODE",	"lslbyte",	"lsl bytecode",		True,		False,		False),
        12: 	("TEXTURE_TGA",		"txtr_tga",	"tga texture",		True,		False,		False),
        13: 	("BODYPART",		"bodypart",	"body part",		True,		True,		True),
        17: 	("SOUND_WAV",		"snd_wav",	"sound",			True,		False,		False),
        18: 	("IMAGE_TGA",		"img_tga",	"targa image",		True,		False,		False),
        19: 	("IMAGE_JPEG",		"jpeg",		"jpeg image",		True,		False,		False),
        20: 	("ANIMATION",		"animatn",	"animation",		True,		True,		True),
        21: 	("GESTURE",			"gesture",	"gesture",			True,		True,		True),
        22: 	("SIMSTATE",		"simstate",	"simstate",			False,		False,		False),
        
        24: 	("LINK",			"link",		"sym link",			False,		False,		True),
        25: 	("FOLDER_LINK",		"link_f", 	"sym folder link",	False,		False,		True),
        49: 	("MESH",			"mesh",     "mesh",				False,		False,		False),
        40: 	("WIDGET",			"widget",   "widget",			False,		False,		False),
        45: 	("PERSON",			"person",   "person",			False,		False,		False),
        255:	("UNKNOWN",			"invalid",  None,				False,		False,		False),
        -2: 	("NONE",			"-1",		None,		  		False,		False,		False),
    }
    
    def __init__(self):
        cvars = []
        for entry in self.asset_types:
            cvars.append(self.asset_types[entry][0])
        super().__setattr__("cvars", tuple(cvars))
    
    def __getitem__(self, k):
        if k not in self.asset_types:
            k = 255
        return dict(zip(self.asset_type_names, self.asset_types[k]))
    
    def __getattr__(self, k):
        if k in self.cvars:
            return self.cvars.index(k)
        raise AttributeError("'{}' object has no attribute '{}'".format(type(self), k))
    
    def fromFileExtension(self, v):
        for at in self.asset_types:
            if self.asset_types[at][1] == v:
                return at
    
class LLVFSEntry:
    def __init__(self, offset, size, length=None, key=None, accesstime=None, filetype=0, vfs=None):
        if length == None or length < size:
            length = 1024 * math.ceil(size/1024)
        
        if key == None:
            key = uuid.UUID(bytes=bytes([random.randint(0,255) for i in range(0,16)]))
        
        if accesstime == None:
            accesstime = datetime.datetime.now()
        
        self.offset = offset
        self._size = size
        self._length = length
        self.key = key
        self.accesstime = accesstime
        self.filetype = filetype
        self.VFS = vfs
    
    #Ensure size is never bigger than length
    @property
    def size(self):
        return self._size
    
    @size.setter
    def size(self, v):
        if self._length < v:
            self._length = 1024 * math.ceil(v/1024)
        self._size = v
    
    #Ensure length stays a multiple of 1024
    @property
    def length(self):
        return self._size
    
    @length.setter
    def length(self, v):
        #Must be multiple of 1024
        if v%1024 != 0:
            v = 1024 * round(v/1024)
        
        if v < self._size:
            self._length = 1024 * math.ceil(self._size/1024)
        else:
            self._length = v
    
    def read(self):
        if not self.VFS:
            return None
        return self.VFS.read(self.offset, self.size)
    
    def __repr__(self):
        return '<LLVFSEntry "{}.{}">'.format(str(self.key), AT[self.filetype]["typename"])
    
class LLVFS:
    def __init__(self, index, data, mode="w"):
        if mode.lower() not in ["r", "w", "a"]:
            raise ValueError("Expected mode r, w, or a")
        
        self.mode = mode
        
        self.entries = []
        self.keymap = []
        
        self.indexStruct = struct.Struct("<III16sHI")
        
        self.indexFile = open(index, mode+"b")
        self.dataFile = open(data, mode+"b")
        
        #Populate index if we are reading or appending
        if mode == "r" or mode == "a":
            self.loadIndexFile()
    
    def loadIndexFile(self):
        self.indexFile.seek(0)
        for entry in self.indexStruct.iter_unpack(self.indexFile.read()):
            key = uuid.UUID(bytes=entry[3])
            self.entries.append(LLVFSEntry(
                offset = entry[0],
                length = entry[1],
                accesstime = datetime.datetime.utcfromtimestamp(entry[2]),
                key = key,
                filetype = entry[4],
                size = entry[5],
                vfs = self
            ))
            self.keymap.append(key)
    
    def __len__(self):
        return len(self.entries)
    
    def fromKey(self, key):
        if type(key) == str:
            key = uuid.UUID(key)
        
        if key in self.keymap:
            return self.entries[self.keymap.index(key)]
    
    def read(self, offset, size):
        self.dataFile.seek(offset)
        return self.dataFile.read(size)
    
    def __dir__(self):
        return [str(i) for i in self.keymap]
    
    def __getitem__(self, prop):
        return self.fromKey(prop)
    
    def __iter__(self):
        return iter(self.entries)
    
    def add(self, key, filetype, data, accesstime = None):
        if not accesstime:
            accesstime = round(datetime.datetime.now().timestamp())
        length = 1024 * math.ceil(len(data)/1024)
        offset = self.dataFile.tell()
        self.dataFile.write(data)
        if length - len(data) > 0:
            self.dataFile.write(b"\0"*(length-len(data)))
        self.indexFile.write(self.indexStruct.pack(offset, length, accesstime, (uuid.UUID(key) if type(key) == str else key).bytes, filetype, len(data)))
    
    def __del__(self):
        self.indexFile.close()
        self.dataFile.close()

class PathMap:
    def __init__(self, data = None):
        #It is faster to have double mappings as it benefits from hash tables
        #Lists would be slower as lists do not use hashing
        self.pathMapping = {}
        self.keyMapping = {}
        
        if data:
            for entry in data:
                self.map(entry, data[entry])
    
    def findPath(self, path):
        return self.pathMapping[path] if path in self.pathMapping else None
    
    def findKey(self, key):
        return self.keyMapping[key] if key in self.keyMapping else None
    
    def map(self, key, path):
        self.pathMapping[path] = key
        self.keyMapping[key] = path
    
    @classmethod
    def loadmap(cls, data):
        self = cls()
        for line in data.splitlines():
            if line == "" or line.startswith("#"):
                continue
            tmp = line.split(" ", 1)
            if len(tmp) != 2:
                print("Invalid line: "+line)
                continue
            self.map(*[x.strip() for x in tmp])
        return self
        

if __name__ == "__main__":
    class shortChoices:
        def __init__(self, choices):
            self.choices = choices
            self.mapping = {}
            self.gnippam = {}
            for k in self.choices:
                for ix in range(len(k)):
                    if len([key for key in self.choices if key.startswith(k[:ix+1])]) == 1:
                        self.mapping[k[:ix+1]] = k
                        self.gnippam[k] = k[:ix+1]
                        break
        
        def __call__(self, prop):
            if prop in self.mapping:
                return self.mapping[prop]
            
            if prop in self.choices:
                return prop
            
            return None
        
        def __contains__(self, prop):
            if prop in self.mapping:
                prop = self.mapping[prop]
            return prop in self.choices
        
        def __iter__(self):
            self.n = 0
            return self
        
        def __next__(self):
            if self.n < len(self.choices):
                choice = self.choices[self.n]
                shortText = self.gnippam[choice]
                
                self.n = self.n + 1
                return "{}[{}]".format(shortText, choice[len(shortText):])
            else:
                raise StopIteration
    
    parser = argparse.ArgumentParser(description='LLVFS un/packer')
    mpicker = shortChoices(["pack", "unpack", "list"])
    parser.add_argument('mode', choices=mpicker, type=mpicker,
                        help="Mode to edit")
    parser.add_argument('--dir', default="./",
                        help="Directory to export or import from")
    parser.add_argument('--map', default=None,
                        help="Use a space seperated name mapping for paths instead of glob search.")
    parser.add_argument('index', default="static_index.db2", nargs='?',
                        help='Index file name (default: static_index.db2)')
    parser.add_argument('data', default="static_data.db2", nargs='?',
                        help='Data file name (default: static_data.db2)')

    args = parser.parse_args()
    
    #Verify files exist if in read mode
    if args.mode == "unpack" or args.mode == "list":
        if not os.path.isfile(args.index):
            print("Index file does not exist!")
            exit(1)
        if not os.path.isfile(args.data):
            print("Data file does not exist!")
            exit(1)
    
    vfs = LLVFS(args.index, args.data, mode = "w" if args.mode == "pack" else "r")
    if args.mode == "list":
        for entry in vfs:
            print(entry)
    
    elif args.mode == "unpack":
        for entry in vfs:
            fn = os.path.join(args.dir, "{}.{}".format(str(entry.key), AT.asset_types[entry.filetype][AT.type]))
            with open(fn, "wb") as f:
                f.write(entry.read())
            t = round(entry.accesstime.timestamp())
            os.utime(fn, (t, t))
    
    elif args.mode == "pack":
        if args.map:
            with open(args.map, "r") as f:
                pathmap = PathMap.loadmap(f.read())
                for key in pathmap.keyMapping:
                    file = os.path.join(args.dir, pathmap.keyMapping[key])
                    name, ext = os.path.splitext(os.path.basename(file))
                    with open(file, "rb") as f:
                        vfs.add(key, AT.fromFileExtension(ext[1:]), f.read(), round(os.path.getmtime(file)))
        else:
            files = glob.glob(os.path.join(args.dir, "**"), recursive=True)
            for file in files:
                name, ext = os.path.splitext(os.path.basename(file))
                with open(file, "rb") as f:
                    data = f.read()
                    vfs.add(uuid.UUID(bytes=hashlib.md5(data).digest()), AT.fromFileExtension(ext[1:]), data, round(os.path.getmtime(file)))
    