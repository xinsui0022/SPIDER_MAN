#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#include <atomic>
#include <cstdio>
#include <cwchar>
#include <cstring>
#include <initializer_list>
#include "door_logic.h"
#include "MinHook.h"

using doorstep::Matrix;
using doorstep::Context;
using doorstep::Anchor;
namespace {
constexpr wchar_t GAME_HASH[] = L"e297d4d94f1ffe4febf289745e79e7b6fa233a788e7a00f480fc77c55db81ad1";
constexpr wchar_t SMT_HASH[] = L"b7ab575100f2346af25180d74bf9641e24ce09bf549ce47446be09c3462606c7";
constexpr uintptr_t COMMIT = 0x1fbd440, WARP = 0x1fc1c50, MATRIX_READ = 0x5c6530;
constexpr uintptr_t PLAYER_GLOBAL = 0x5d9dd00, ENTITY_TABLE = 0x7a44380, ENTITY_COUNT = 0x7a4439c;
constexpr uintptr_t STANDARD_VTABLE = 0x4f70168, TASK_MANAGER = 0x6efc1a0;
constexpr uintptr_t DIRECTOR = 0x6f64af4;
const unsigned char commitBytes[] = {0x40,0x53,0x48,0x83,0xec,0x20,0x48,0x8b,0xd9,0xe8,0xc2,0x61,0,0,0x48,0x8b};
const unsigned char warpBytes[] = {0x48,0x89,0x5c,0x24,0x08,0x48,0x89,0x6c,0x24,0x10,0x48,0x89,0x74,0x24,0x18,0x57};
const unsigned char readBytes[] = {0x48,0x8b,0x01,0x48,0x85,0xc0,0x0f,0x84,0xde,0,0,0,0xf3,0x0f,0x10,0x48};
using CommitFn = void(__fastcall*)(void*);
using MatrixFn = float*(__fastcall*)(void*, Matrix*);
using WarpFn = void(__fastcall*)(void*, const Matrix*, float);
CommitFn originalCommit = nullptr;
uintptr_t gameBase = 0;
HMODULE ownModule = nullptr;
std::atomic<bool> ready{false}, armed{false}, faulted{false}, stopping{false};
std::atomic<bool> tracking{false};
std::atomic<bool> resetReturn{false};
std::atomic_flag actionLock = ATOMIC_FLAG_INIT;
std::atomic<int> pending{0}, result{0};
std::atomic<uint64_t> requestTime{0}, resultSequence{0};
float stepDistance = 2.5f;
float verticalDistance = 1.0f;
wchar_t logPath[32768]{};
Anchor anchor;
thread_local bool inside = false;
enum Code { Off=1, On, Queued, Stepped, Returned, NoPlayer, BadScene, BadMatrix, NoAnchor, Stale,
    NativeFault, Rebounded, Ready, BadHost, BadVersion, BadCode, HookFailure, BadDirection, MovedUp, MovedDown };

void Publish(Code code) { result.store(code); resultSequence.fetch_add(1, std::memory_order_release); }
const char* Description(int code) {
    switch (code) {
    case Off: return "DISARMED"; case On: return "ARMED: F8 forward, PageUp up, PageDown down, F9 return";
    case Queued: return "request queued"; case Stepped: return "native short step applied";
    case Returned: return "returned to last step origin"; case NoPlayer: return "refused: player identity changed or unavailable";
    case BadScene: return "refused: scene/task state unavailable"; case BadMatrix: return "refused: invalid transform";
    case NoAnchor: return "refused: return point absent, expired, too far, or scene/player changed";
    case Stale: return "refused: request expired or game no longer foreground";
    case NativeFault: return "DISABLED: protected plugin operation faulted";
    case Rebounded: return "DISARMED: position did not hold after native warp";
    case Ready: return "READY, initially DISARMED; F7 enable; F8 forward; PageUp up; PageDown down; F9 return";
    case BadHost: return "disabled: host is not Spider-Man.exe";
    case BadVersion: return "disabled: game/SMT SHA256 mismatch or SMT missing";
    case BadCode: return "disabled: live code/vtable differs from audited build";
    case HookFailure: return "disabled: hook initialization failed";
    case BadDirection: return "refused: character direction is unsuitable";
    case MovedUp: return "native upward step applied";
    case MovedDown: return "native downward step applied";
    } return "unknown";
}
void Log(const char* message) {
    FILE* file = nullptr;
    if (_wfopen_s(&file, logPath, L"ab") || !file) return;
    SYSTEMTIME t{}; GetLocalTime(&t);
    fprintf(file, "%04u-%02u-%02u %02u:%02u:%02u DoorStep 0.1 %s\r\n",t.wYear,t.wMonth,t.wDay,t.wHour,t.wMinute,t.wSecond,message);
    fclose(file);
}
bool Readable(uintptr_t address, size_t size) {
    if (address < 0x10000 || size > 0x100000 || address + size < address) return false;
    MEMORY_BASIC_INFORMATION m{};
    if (!VirtualQuery(reinterpret_cast<void*>(address), &m, sizeof(m)) || m.State != MEM_COMMIT) return false;
    if (m.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    return address + size <= reinterpret_cast<uintptr_t>(m.BaseAddress) + m.RegionSize;
}
bool Foreground() {
    DWORD pid = 0; GetWindowThreadProcessId(GetForegroundWindow(), &pid);
    return pid == GetCurrentProcessId();
}
template<class T> T Read(uintptr_t p) { return *reinterpret_cast<const T*>(p); }
uint64_t Mix(uint64_t h, uint64_t v) { return (h ^ v) * 1099511628211ull; }
bool SceneTag(uint64_t& tag) {
    if (Read<unsigned char>(gameBase + DIRECTOR) != 1) return false;
    const uintptr_t manager = gameBase + TASK_MANAGER;
    const uintptr_t storage = Read<uintptr_t>(manager + 0x688b0);
    const uintptr_t entries = Read<uintptr_t>(manager + 0x28);
    const int entryCount = Read<int>(manager + 0x30);
    if (!storage || !entries || entryCount <= 0 || entryCount > 200000) return false;
    const int count = Read<int>(storage + 0x30320);
    const uintptr_t states=Read<uintptr_t>(storage);
    if (count <= 0 || count > 64 || !states) return false;
    tag = Mix(1469598103934665603ull, storage);
    tag = Mix(tag, entries); tag = Mix(tag, states);
    tag = Mix(tag, static_cast<uint64_t>(count));
    for (int i = 0; i < count; ++i) {
        const int index = Read<int>(storage + 0x120 + i*4);
        if (index < 0 || index >= entryCount) return false;
        const uintptr_t mission = Read<uintptr_t>(entries + index*0x30);
        if (!mission) return false;
        const uint32_t goals = Read<uint32_t>(mission + 0x80);
        if (goals > 64) return false;
        tag=Mix(tag,static_cast<uint64_t>(index)); tag=Mix(tag,mission);
        tag=Mix(tag,Read<uint32_t>(states+index*4));
        tag = Mix(tag, Read<uint32_t>(mission + 0x14));
        for (uint32_t k = 0; k < goals; ++k) tag = Mix(tag, Read<uint32_t>(storage + 0x220 + i*0x100 + k*4));
    }
    return true;
}
bool Local(void* mover, Context& c) {
    const uintptr_t self = reinterpret_cast<uintptr_t>(mover);
    if (!Readable(self, 0x730) || Read<uintptr_t>(self) != gameBase + STANDARD_VTABLE) return false;
    const uintptr_t record = Read<uintptr_t>(gameBase + PLAYER_GLOBAL + 0x158);
    if (!record || !Readable(record, 8)) return false;
    const uint32_t handle = Read<uint32_t>(record + 4);
    const uint32_t index = handle & 0xfffff, generation = (handle >> 20) & 0x7ff;
    const uint32_t count = Read<uint32_t>(gameBase + ENTITY_COUNT);
    const uintptr_t table = Read<uintptr_t>(gameBase + ENTITY_TABLE);
    if (!generation || !table || count > 0x100000 || index >= count) return false;
    const uintptr_t entry = table + index*0xc0;
    if (!Readable(entry, 0xc0) || Read<uint16_t>(entry + 0x10) != generation || Read<uintptr_t>(self + 8) != entry) return false;
    const uintptr_t spatial = Read<uintptr_t>(entry);
    if (!Readable(spatial, 0x80)) return false;
    c = {handle, entry, self, 0};
    return true;
}
struct Verification { bool active=false; Context context{}; Matrix target{}; uint64_t time=0; } verification;
uint64_t lastLocalTick=0;

void Action(void* mover) {
    Context context{};
    if (!Local(mover, context)) return; // Leave a queued request for the actual local Mover.
    const uint64_t now = GetTickCount64();
    if (resetReturn.exchange(false) || (lastLocalTick && now-lastLocalTick>1000)) {
        anchor.valid=false; verification.active=false;
    }
    lastLocalTick=now;
    if (!SceneTag(context.scene)) {
        anchor.valid = false; verification.active = false;
        if (pending.exchange(0)) Publish(BadScene);
        return;
    }
    Matrix current{};
    reinterpret_cast<MatrixFn>(gameBase + MATRIX_READ)(reinterpret_cast<void*>(context.entry), &current);
    if (!doorstep::ValidMatrix(current)) {
        anchor.valid = false; verification.active = false;
        if (pending.exchange(0)) Publish(BadMatrix);
        return;
    }
    if (anchor.valid && (!doorstep::SameContext(context, anchor.context) || now-anchor.time > 120000)) anchor.valid = false;
    if (verification.active && now >= verification.time + 400) {
        if (doorstep::SameContext(context, verification.context) && doorstep::Separation(current, verification.target) > 1.5f) {
            armed = false; pending = 0; Publish(Rebounded);
        }
        verification.active = false;
    }
    const int command = pending.exchange(0, std::memory_order_acquire);
    if (!command) return;
    if (!armed || !Foreground() || now < requestTime || now-requestTime > 1000) { Publish(Stale); return; }
    Matrix target{};
    if (command == 1) {
        if (!doorstep::Step(current, stepDistance, target)) { Publish(BadDirection); return; }
    } else if(command==3 || command==4) {
        if (!doorstep::Vertical(current,command==3 ? verticalDistance : -verticalDistance,target)) { Publish(BadMatrix); return; }
    } else {
        if (!doorstep::CanReturn(anchor, context, current, now)) { anchor.valid=false; Publish(NoAnchor); return; }
        target = anchor.matrix;
    }
    Context again{};
    if (!Local(mover, again) || !SceneTag(again.scene) || !doorstep::SameContext(again,context)) { anchor.valid=false; Publish(NoPlayer); return; }
    if (command != 2) anchor = {true, current, context, now};
    reinterpret_cast<WarpFn>(gameBase + WARP)(mover, &target, 0.0f);
    Matrix actual{};
    reinterpret_cast<MatrixFn>(gameBase + MATRIX_READ)(reinterpret_cast<void*>(context.entry), &actual);
    if (!doorstep::ValidMatrix(actual) || doorstep::Separation(actual, target) > 0.15f) {
        armed = false; Publish(Rebounded); return;
    }
    if (command == 2) anchor.valid = false;
    verification = {true, context, target, now};
    Publish(command==1 ? Stepped : command==2 ? Returned : command==3 ? MovedUp : MovedDown);
}
void ProtectedAction(void* mover) {
    __try { Action(mover); }
    __except(EXCEPTION_EXECUTE_HANDLER) {
        faulted = true; armed = false; pending = 0; anchor.valid = false; verification.active = false; Publish(NativeFault);
    }
    tracking.store(anchor.valid || verification.active, std::memory_order_release);
}
void __fastcall CommitHook(void* mover) {
    originalCommit(mover);
    if (inside || !ready || faulted || (!pending && !tracking)) return;
    if (actionLock.test_and_set(std::memory_order_acquire)) return;
    inside = true; ProtectedAction(mover); inside = false;
    actionLock.clear(std::memory_order_release);
}
bool ShaMatches(const wchar_t* path, const wchar_t* expected) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    BCRYPT_ALG_HANDLE alg = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
    bool ok = BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0;
    if (ok) ok = BCryptCreateHash(alg, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    unsigned char buffer[65536], digest[32]{}; DWORD n = 0;
    while (ok) {
        if (!ReadFile(file, buffer, sizeof(buffer), &n, nullptr)) { ok=false; break; }
        if (!n) break;
        ok = BCryptHashData(hash, buffer, n, 0) >= 0;
    }
    if (ok) ok = BCryptFinishHash(hash, digest, sizeof(digest), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (alg) BCryptCloseAlgorithmProvider(alg, 0);
    CloseHandle(file);
    wchar_t text[65]{};
    for (int i=0; i<32; ++i) swprintf_s(text+i*2, 3, L"%02x", digest[i]);
    return ok && _wcsicmp(text, expected) == 0;
}
bool CodeMatches() {
    __try {
        return !memcmp(reinterpret_cast<void*>(gameBase+COMMIT),commitBytes,sizeof(commitBytes))
            && !memcmp(reinterpret_cast<void*>(gameBase+WARP),warpBytes,sizeof(warpBytes))
            && !memcmp(reinterpret_cast<void*>(gameBase+MATRIX_READ),readBytes,sizeof(readBytes))
            && Read<uintptr_t>(gameBase+STANDARD_VTABLE+0x60) == gameBase+COMMIT;
    } __except(EXCEPTION_EXECUTE_HANDLER) { return false; }
}
bool LoadedPlayer() {
    __try {
        const uintptr_t record=Read<uintptr_t>(gameBase+PLAYER_GLOBAL+0x158);
        if (!Readable(record,8)) return false;
        const uint32_t h=Read<uint32_t>(record+4), index=h&0xfffff, generation=(h>>20)&0x7ff;
        const uint32_t count=Read<uint32_t>(gameBase+ENTITY_COUNT);
        const uintptr_t table=Read<uintptr_t>(gameBase+ENTITY_TABLE);
        if (!generation || count>0x100000 || index>=count || !table) return false;
        const uintptr_t entry=table+index*0xc0;
        if (!Readable(entry,0xc0) || Read<uint16_t>(entry+0x10)!=generation) return false;
        const uintptr_t key=gameBase+0x7c40bf0;
        const uint16_t capacity=Read<uint16_t>(entry+0x88);
        uintptr_t mover=0;
        if (capacity) {
            if (capacity>32768 || (capacity&(capacity-1))) return false;
            const uintptr_t buckets=Read<uintptr_t>(entry+0x80);
            if (!Readable(buckets,static_cast<size_t>(capacity)*16)) return false;
            const size_t start=(key>>4)&(capacity-1);
            for (size_t n=0;n<capacity;++n) {
                const uintptr_t item=buckets+((start+n)&(capacity-1))*16;
                if (Read<uintptr_t>(item)==key) { mover=Read<uintptr_t>(item+8); break; }
            }
        } else {
            const uint16_t n=Read<uint16_t>(entry+0x70);
            const uintptr_t items=Read<uintptr_t>(entry+0x68);
            if (n>128 || !Readable(items,static_cast<size_t>(n)*16)) return false;
            for (uint16_t i=0;i<n;++i) if (Read<uintptr_t>(items+i*16)==key) { mover=Read<uintptr_t>(items+i*16+8); break; }
        }
        Context context{};
        uint64_t scene=0;
        return mover && Local(reinterpret_cast<void*>(mover),context) && SceneTag(scene);
    } __except(EXCEPTION_EXECUTE_HANDLER) { return false; }
}
bool Down(int key) { return (GetAsyncKeyState(key) & 0x8000) != 0; }
DWORD WINAPI Worker(void*) {
    wchar_t modulePath[32768]{}, hostPath[32768]{};
    GetModuleFileNameW(ownModule, modulePath, 32768);
    wchar_t* last = wcsrchr(modulePath, L'\\'); if (!last) return 0; *last = 0;
    swprintf_s(logPath,L"%s\\DoorStep.log",modulePath);
    GetModuleFileNameW(nullptr, hostPath, 32768);
    const wchar_t* name=wcsrchr(hostPath,L'\\'); name=name ? name+1 : hostPath;
    if (_wcsicmp(name,L"Spider-Man.exe")) { Publish(BadHost); Log(Description(BadHost)); return 0; }
    HMODULE smt=nullptr;
    for (int i=0;i<1800 && !stopping;++i) {
        smt=GetModuleHandleW(L"smt.dll"); if (smt) break; Sleep(50);
    }
    wchar_t smtPath[32768]{};
    if (smt) GetModuleFileNameW(smt,smtPath,32768);
    if (!smt || !ShaMatches(hostPath,GAME_HASH) || !ShaMatches(smtPath,SMT_HASH)) { Publish(BadVersion); Log(Description(BadVersion)); return 0; }
    gameBase=reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    if (!CodeMatches()) { Publish(BadCode); Log(Description(BadCode)); return 0; }
    wchar_t iniPath[32768]{}, distanceText[64]{};
    swprintf_s(iniPath,L"%s\\DoorStep.ini",modulePath);
    GetPrivateProfileStringW(L"DoorStep",L"StepMeters",L"2.5",distanceText,64,iniPath);
    wchar_t* end=nullptr; float d=wcstof(distanceText,&end);
    if (end && !*end && std::isfinite(d) && d>=0.5f && d<=5.0f) stepDistance=d;
    GetPrivateProfileStringW(L"DoorStep",L"VerticalMeters",L"1.0",distanceText,64,iniPath);
    end=nullptr; d=wcstof(distanceText,&end);
    if (end && !*end && std::isfinite(d) && d>=0.5f && d<=5.0f) verticalDistance=d;
    Log("waiting for loaded local MoverStandard; no hook or warp yet");
    while (!stopping && !LoadedPlayer()) Sleep(200);
    if (stopping) return 0;
    if (!CodeMatches()) { Publish(BadCode); Log(Description(BadCode)); return 0; }
    HMODULE pinned=nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
        reinterpret_cast<LPCWSTR>(&Worker),&pinned)) { Publish(HookFailure); Log(Description(HookFailure)); return 0; }
    if (MH_Initialize()!=MH_OK || MH_CreateHook(reinterpret_cast<void*>(gameBase+COMMIT),reinterpret_cast<void*>(&CommitHook),reinterpret_cast<void**>(&originalCommit))!=MH_OK
        || MH_EnableHook(reinterpret_cast<void*>(gameBase+COMMIT))!=MH_OK) { Publish(HookFailure); Log(Description(HookFailure)); return 0; }
    ready=true; Publish(Ready); Log(Description(Ready));
    bool f7=Down(VK_F7), f8=Down(VK_F8), f9=Down(VK_F9), up=Down(VK_PRIOR), down=Down(VK_NEXT);
    uint64_t lastRequest=0, logged=resultSequence.load();
    while (!stopping) {
        bool a=Down(VK_F7), b=Down(VK_F8), c=Down(VK_F9), u=Down(VK_PRIOR), dkey=Down(VK_NEXT);
        const uint64_t now=GetTickCount64();
        if (!Foreground()) {
            if (armed.exchange(false)) { resetReturn=true; Publish(Off); }
            pending=0;
        } else if (!faulted) {
            if (a && !f7) { armed=!armed.load(); pending=0; if(!armed)resetReturn=true; Publish(armed ? On : Off); }
            if (armed && now-lastRequest>=600 && ((b && !f8)||(c && !f9)||(u && !up)||(dkey && !down)) && !pending) {
                const int command=c && !f9 ? 2 : u && !up ? 3 : dkey && !down ? 4 : 1;
                requestTime.store(now); pending.store(command,std::memory_order_release); lastRequest=now; Publish(Queued);
            }
            if (pending && now-requestTime>1000) { pending=0; Publish(Stale); }
        }
        f7=a; f8=b; f9=c; up=u; down=dkey;
        const uint64_t sequence=resultSequence.load(std::memory_order_acquire);
        if (sequence!=logged) {
            logged=sequence; const int code=result.load(); Log(Description(code));
            if (code==On) { Beep(900,60); Beep(1200,60); }
            else if (code==Off) Beep(600,80);
            else if (code==Stepped || code==Returned || code==MovedUp || code==MovedDown) Beep(1100,60);
            else if (code!=Queued) Beep(400,100);
        }
        Sleep(20);
    }
    return 0;
}
}
extern "C" __declspec(dllexport) unsigned long DoorStepGetStatus() {
    return (ready ? 1ul:0ul)|(armed?2ul:0ul)|(pending?4ul:0ul)|(faulted?8ul:0ul);
}
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason==DLL_PROCESS_ATTACH) {
        ownModule=instance;
        HANDLE worker=CreateThread(nullptr,0,Worker,nullptr,0,nullptr); if (worker) CloseHandle(worker);
    } else if (reason==DLL_PROCESS_DETACH) stopping=true;
    return TRUE;
}
