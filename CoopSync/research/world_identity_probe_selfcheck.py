"""Pure fake-memory checks of the exact world identity reader; no process use."""
from __future__ import annotations

import world_identity_runtime_probe as probe

BASE, TABLE, ARRAY, COMPONENT = 0x140000000, 0x200000000, 0x210000000, 0x220000000
INDEX, GENERATION, KEY = 1, 3, 0x8123456789ABCDEF
ENTRY = TABLE + INDEX * 0xC0
CHECKS = 0


def require(condition, message):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(message)


class Fake:
    def __init__(self):
        self.memory, self.seen, self.mutate, self.short = {}, {}, None, None

    def put(self, address, value, size):
        self.memory[address, size] = value.to_bytes(size, "little")

    def read(self, address, size):
        self.seen[address, size] = self.seen.get((address, size), 0) + 1
        if self.mutate:
            self.mutate(address, size, self.seen[address, size])
        raw = self.memory[address, size]
        return raw[:size//2] if address == self.short else raw


def fixture():
    fake = Fake()
    fake.put(BASE + probe.TABLE_RVA, TABLE, 8)
    fake.put(BASE + probe.COUNT_RVA, 10, 4)
    fake.put(BASE + probe.KEY_ARRAY_RVA, ARRAY, 8)
    fake.put(ENTRY + 0xC, INDEX, 4)
    fake.put(ENTRY + 0x10, GENERATION, 2)
    fake.put(COMPONENT, BASE + probe.VTABLES["Door"], 8)
    fake.put(COMPONENT + 8, ENTRY, 8)
    fake.put(COMPONENT + 0x14, 0x1234, 4)
    fake.put(ARRAY + INDEX * 8, KEY, 8)
    candidate = {"type": "Door", "entity_index": INDEX, "entity_generation_raw": GENERATION,
                 "component_raw": hex(COMPONENT), "component_handle_local": 0x1234,
                 "source_table_raw": hex(TABLE), "source_table_count_raw": 10,
                 "owner_raw": hex(ENTRY), "vtable_raw": hex(BASE + probe.VTABLES["Door"]),
                 "source_sequence": 5}
    return fake, candidate


def main():
    fake, candidate = fixture()
    reader = probe.Reader(fake)
    result = probe.capture(reader, BASE, [candidate])
    require(len(result["accepted"]) == 1, "stable candidate rejected")
    require(result["accepted"][0]["candidate_key_u64"] == hex(KEY), "key value wrong")
    require(result["accepted"][0]["peer_id"] is None, "key promoted to peer ID")
    require(result["accepted"][0]["stable_network_entity_id_verified"] is False, "stability overclaimed")
    require(reader.reads <= probe.MAX_READS and reader.bytes <= probe.MAX_BYTES, "read budget exceeded")

    for address, size, altered in ((ENTRY + 0x10, 2, 4), (COMPONENT + 0x14, 4, 0x4321),
                                    (ARRAY + INDEX * 8, 8, KEY + 1)):
        fake, candidate = fixture()
        def mutate(got_address, got_size, count):
            if got_address == address and got_size == size and count == 2:
                fake.put(address, altered, size)
        fake.mutate = mutate
        result = probe.capture(probe.Reader(fake), BASE, [candidate])
        require(not result["accepted"], "observed per-object race accepted")
        require("changed_during_reads" in result["gaps"][0]["reason"], "race reason missing")

    for address, size, altered in ((BASE + probe.COUNT_RVA, 4, 9),
                                    (BASE + probe.KEY_ARRAY_RVA, 8, ARRAY + 0x1000)):
        fake, candidate = fixture()
        def mutate(got_address, got_size, count):
            if got_address == address and got_size == size and count == 2:
                fake.put(address, altered, size)
        fake.mutate = mutate
        result = probe.capture(probe.Reader(fake), BASE, [candidate])
        require(not result["accepted"], "global race accepted")
        require(not result["global_headers_unchanged"], "global race missed")

    fake, candidate = fixture()
    fake.put(COMPONENT, BASE + probe.VTABLES["Health"], 8)
    result = probe.capture(probe.Reader(fake), BASE, [candidate])
    require(not result["accepted"], "different vtable accepted")
    require((ARRAY + INDEX * 8, 8) not in fake.seen, "key read before source identity validation")
    fake, candidate = fixture()
    fake.short = ARRAY + INDEX * 8
    result = probe.capture(probe.Reader(fake), BASE, [candidate])
    require(not result["accepted"], "short key read accepted")
    require(result["gaps"][0]["reason"] == "read_short", "short read not reported")

    fake, candidate = fixture()
    reader = probe.Reader(fake)
    result = probe.capture(reader, BASE, [candidate] * 17)
    require(len(result["accepted"]) == 16, "max 16 objects ignored")
    require(reader.reads <= probe.MAX_READS and reader.bytes <= probe.MAX_BYTES, "16-object cap budget exceeded")
    fake, _ = fixture()
    reader = probe.Reader(fake)
    for _ in range(probe.MAX_READS):
        reader.read(BASE + probe.TABLE_RVA, 8)
    try:
        reader.read(BASE + probe.TABLE_RVA, 8)
        raise AssertionError("read cap ignored")
    except ValueError as error:
        require(str(error) == "read_budget_refused", "wrong budget refusal")
    print(f"World raw identity probe: {CHECKS} pure checks passed; no game process used.")


if __name__ == "__main__":
    main()
