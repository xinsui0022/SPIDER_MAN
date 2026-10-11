"""Offline SWF/DoABC reader for bounded diagnostic disassembly; never executes ABC."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import zlib


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, count):
        start = self.pos
        self.pos += count
        if self.pos > len(self.data):
            raise ValueError("Truncated input")
        return self.data[start:self.pos]

    def u8(self):
        return self.take(1)[0]

    def u30(self):
        value = 0
        for shift in range(0, 35, 7):
            byte = self.u8()
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
        raise ValueError("Invalid variable integer")

    def s24(self):
        return int.from_bytes(self.take(3), "little", signed=True)


def abc_blocks(data):
    if data[:3] in (b"CWS", b"CFX"):
        data = data[:8] + zlib.decompress(data[8:])
    if data[:3] not in (b"FWS", b"GFX", b"CWS", b"CFX"):
        raise ValueError("Unsupported SWF signature")
    expected = struct.unpack_from("<I", data, 4)[0]
    if len(data) != expected:
        raise ValueError("SWF length mismatch")
    rect_bytes = ((data[8] >> 3) * 4 + 5 + 7) // 8
    r = Reader(data)
    r.pos = 8 + rect_bytes + 4
    while r.pos < len(data):
        header = int.from_bytes(r.take(2), "little")
        kind, size = header >> 6, header & 63
        if size == 63:
            size = int.from_bytes(r.take(4), "little")
        offset = r.pos
        payload = r.take(size)
        if kind == 82:
            start = payload.index(b"\0", 4) + 1
            yield offset + start, payload[start:]
        elif kind == 72:
            yield offset, payload
        if kind == 0:
            break


class ABC:
    def __init__(self, data):
        r = self.r = Reader(data)
        self.version = struct.unpack("<HH", r.take(4))
        self.ints = [0] + [r.u30() for _ in range(max(0, r.u30() - 1))]
        self.uints = [0] + [r.u30() for _ in range(max(0, r.u30() - 1))]
        self.doubles = [0.0] + [struct.unpack("<d", r.take(8))[0] for _ in range(max(0, r.u30() - 1))]
        self.strings = [""] + [r.take(r.u30()).decode("utf8", errors="replace") for _ in range(max(0, r.u30() - 1))]
        self.ns = [(0, 0)] + [(r.u8(), r.u30()) for _ in range(max(0, r.u30() - 1))]
        self.nssets = [[]] + [[r.u30() for _ in range(r.u30())] for _ in range(max(0, r.u30() - 1))]
        self.names = [None]
        for _ in range(max(0, r.u30() - 1)):
            kind = r.u8()
            if kind in (7, 13):
                item = (kind, r.u30(), r.u30())
            elif kind in (15, 16):
                item = (kind, r.u30())
            elif kind in (17, 18):
                item = (kind,)
            elif kind in (9, 14):
                item = (kind, r.u30(), r.u30())
            elif kind in (27, 28):
                item = (kind, r.u30())
            elif kind == 29:
                item = (kind, r.u30(), [r.u30() for _ in range(r.u30())])
            else:
                raise ValueError(f"Unknown multiname {kind}")
            self.names.append(item)
        self.methods = []
        self.labels = {}
        for _ in range(r.u30()):
            count, ret = r.u30(), r.u30()
            args = [r.u30() for _ in range(count)]
            name, flags = r.u30(), r.u8()
            defaults = [(r.u30(), r.u8()) for _ in range(r.u30())] if flags & 8 else []
            argnames = [r.u30() for _ in range(count)] if flags & 128 else []
            self.methods.append(dict(name=self.strings[name], flags=flags, params=args, defaults=defaults))
        for _ in range(r.u30()):
            r.u30()
            count = r.u30()
            for _ in range(count * 2):
                r.u30()
        class_count = r.u30()
        classes = []
        for _ in range(class_count):
            name, superclass, flags = r.u30(), r.u30(), r.u8()
            if flags & 8:
                r.u30()
            for _ in range(r.u30()):
                r.u30()
            label = self.name(name)
            classes.append(label)
            self.labels[r.u30()] = label + "/iinit"
            self.traits(label)
        for label in classes:
            self.labels[r.u30()] = label + "/cinit"
            self.traits(label + ".static")
        for index in range(r.u30()):
            r.u30()
            self.traits(f"script{index}")
        self.bodies = {}
        for _ in range(r.u30()):
            index = r.u30()
            limits = [r.u30() for _ in range(4)]
            length = r.u30()
            offset = r.pos
            code = r.take(length)
            for _ in range(r.u30()):
                for _ in range(5):
                    r.u30()
            self.traits("body")
            self.bodies[index] = dict(code=code, offset=offset, limits=limits)
        if r.pos != len(data):
            raise ValueError(f"ABC trailing bytes {len(data) - r.pos}")

    def name(self, index):
        if index == 0:
            return "*"
        item = self.names[index]
        if item[0] in (7, 13):
            namespace = self.strings[self.ns[item[1]][1]]
            return (namespace + "::" if namespace else "") + self.strings[item[2]]
        if item[0] in (9, 14, 15, 16):
            return self.strings[item[1]]
        return repr(item)

    def traits(self, owner):
        r = self.r
        for _ in range(r.u30()):
            name, tag = r.u30(), r.u8()
            kind = tag & 15
            if kind in (0, 6):
                r.u30(); r.u30()
                if r.u30():
                    r.u8()
            elif kind in (1, 2, 3):
                r.u30()
                method = r.u30()
                self.labels[method] = owner + "/" + self.name(name)
            elif kind in (4, 5):
                r.u30(); r.u30()
            else:
                raise ValueError(f"Unknown trait {kind}")
            if tag & 64:
                for _ in range(r.u30()):
                    r.u30()


OPS = {
    0x02: ("nop", ""), 0x03: ("throw", ""), 0x04: ("getsuper", "n"), 0x05: ("setsuper", "n"),
    0x06: ("dxns", "s"), 0x07: ("dxnslate", ""), 0x08: ("kill", "u"), 0x09: ("label", ""),
    0x1c: ("pushwith", ""), 0x1d: ("popscope", ""), 0x1e: ("nextname", ""), 0x1f: ("hasnext", ""),
    0x20: ("pushnull", ""), 0x21: ("pushundefined", ""), 0x23: ("nextvalue", ""),
    0x24: ("pushbyte", "b"), 0x25: ("pushshort", "u"), 0x26: ("pushtrue", ""), 0x27: ("pushfalse", ""),
    0x28: ("pushnan", ""), 0x29: ("pop", ""), 0x2a: ("dup", ""), 0x2b: ("swap", ""),
    0x2c: ("pushstring", "s"), 0x2d: ("pushint", "i"), 0x2e: ("pushuint", "v"), 0x2f: ("pushdouble", "d"),
    0x30: ("pushscope", ""), 0x31: ("pushnamespace", "u"), 0x32: ("hasnext2", "uu"),
    0x40: ("newfunction", "u"), 0x41: ("call", "u"), 0x42: ("construct", "u"),
    0x43: ("callmethod", "uu"), 0x44: ("callstatic", "uu"), 0x45: ("callsuper", "nu"),
    0x46: ("callproperty", "nu"), 0x47: ("returnvoid", ""), 0x48: ("returnvalue", ""),
    0x49: ("constructsuper", "u"), 0x4a: ("constructprop", "nu"), 0x4c: ("callproplex", "nu"),
    0x4e: ("callsupervoid", "nu"), 0x4f: ("callpropvoid", "nu"),
    0x53: ("applytype", "u"), 0x55: ("newobject", "u"), 0x56: ("newarray", "u"),
    0x57: ("newactivation", ""), 0x58: ("newclass", "u"), 0x59: ("getdescendants", "n"),
    0x5a: ("newcatch", "u"), 0x5d: ("findpropstrict", "n"), 0x5e: ("findproperty", "n"),
    0x5f: ("finddef", "n"), 0x60: ("getlex", "n"), 0x61: ("setproperty", "n"),
    0x62: ("getlocal", "u"), 0x63: ("setlocal", "u"), 0x64: ("getglobalscope", ""),
    0x65: ("getscopeobject", "B"), 0x66: ("getproperty", "n"), 0x67: ("getouterscope", "u"),
    0x68: ("initproperty", "n"), 0x6a: ("deleteproperty", "n"), 0x6c: ("getslot", "u"),
    0x6d: ("setslot", "u"), 0x6e: ("getglobalslot", "u"), 0x6f: ("setglobalslot", "u"),
    0x80: ("coerce", "n"), 0x82: ("coerce_a", ""), 0x85: ("coerce_s", ""),
    0x86: ("astype", "n"), 0x87: ("astypelate", ""), 0x92: ("inclocal", "u"), 0x94: ("declocal", "u"),
    0xb2: ("istype", "n"), 0xc2: ("inclocal_i", "u"), 0xc3: ("declocal_i", "u"),
    0xef: ("debug", "BuBu"), 0xf0: ("debugline", "u"), 0xf1: ("debugfile", "s"),
}
for op, name in enumerate(("ifnlt", "ifnle", "ifngt", "ifnge", "jump", "iftrue", "iffalse", "ifeq", "ifne", "iflt", "ifle", "ifgt", "ifge", "ifstricteq", "ifstrictne"), 0x0c):
    OPS[op] = (name, "j")
for op, name in {0x70: "convert_s", 0x73: "convert_i", 0x74: "convert_u", 0x75: "convert_d", 0x76: "convert_b", 0x77: "convert_o", 0x78: "checkfilter", 0x81: "coerce_b", 0x83: "coerce_i", 0x84: "coerce_d", 0x88: "coerce_u", 0x89: "coerce_o", 0x90: "negate", 0x91: "increment", 0x93: "decrement", 0x95: "typeof", 0x96: "not", 0x97: "bitnot", 0xa0: "add", 0xa1: "subtract", 0xa2: "multiply", 0xa3: "divide", 0xa4: "modulo", 0xa5: "lshift", 0xa6: "rshift", 0xa7: "urshift", 0xa8: "bitand", 0xa9: "bitor", 0xaa: "bitxor", 0xab: "equals", 0xac: "strictequals", 0xad: "lessthan", 0xae: "lessequals", 0xaf: "greaterthan", 0xb0: "greaterequals", 0xb1: "instanceof", 0xb3: "istypelate", 0xb4: "in", 0xc0: "increment_i", 0xc1: "decrement_i", 0xc4: "negate_i", 0xc5: "add_i", 0xc6: "subtract_i", 0xc7: "multiply_i"}.items():
    OPS[op] = (name, "")
for index in range(4):
    OPS[0xd0 + index] = (f"getlocal{index}", "")
    OPS[0xd4 + index] = (f"setlocal{index}", "")


def disassemble(abc, body):
    r = Reader(body["code"])
    while r.pos < len(r.data):
        offset = r.pos
        op = r.u8()
        if op == 0x1b:
            default, count = r.s24(), r.u30()
            operands = [default + offset] + [r.s24() + offset for _ in range(count + 1)]
            yield offset, "lookupswitch", operands
            continue
        if op not in OPS:
            raise ValueError(f"Unsupported opcode {op:02x} at {offset:x}")
        name, fmt = OPS[op]
        operands = []
        for field in fmt:
            if field == "j":
                relative = r.s24()
                value = f"->0x{r.pos + relative:x}"
            elif field in ("B", "b"):
                value = r.u8()
                if field == "b" and value > 127:
                    value -= 256
            else:
                value = r.u30()
                if field == "n": value = abc.name(value)
                elif field == "s": value = abc.strings[value]
                elif field == "i": value = abc.ints[value]
                elif field == "v": value = abc.uints[value]
                elif field == "d": value = abc.doubles[value]
            operands.append(value)
        yield offset, name, operands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--match", default="StartGame,NewGame,DifficultyMode,OpenDifficultyPanel,OnDifficultyListComplete")
    args = parser.parse_args()
    data = args.path.read_bytes()
    print("sha256", hashlib.sha256(data).hexdigest())
    needles = [part.lower() for part in args.match.split(",")]
    for offset, block in abc_blocks(data):
        abc = ABC(block)
        print("ABC", hex(offset), "version", abc.version, "methods", len(abc.methods), "bodies", len(abc.bodies))
        for index, method in enumerate(abc.methods):
            label = abc.labels.get(index, method["name"])
            if not any(needle in label.lower() for needle in needles):
                continue
            print("METHOD", index, label, "debugname", method["name"], "params", len(method["params"]))
            body = abc.bodies.get(index)
            if body is None:
                print("  no bytecode body")
                continue
            print("  body file offset", hex(offset + body["offset"]), "length", len(body["code"]))
            for pc, op, operands in disassemble(abc, body):
                print(f"  {pc:04x} {op} {json.dumps(operands, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
