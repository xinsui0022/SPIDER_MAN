#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdio>
#include <cmath>
#include <limits>
#include "door_logic.h"
#include "MinHook.h"
using namespace doorstep;
int failures=0, checks=0;
void Check(bool pass,const char* name) { ++checks; if (!pass) { ++failures; printf("FAIL %s\n",name); } }
Matrix Identity() { Matrix m{}; for(int i=0;i<4;++i)m.v[i*5]=1; m.v[12]=100; m.v[13]=50; m.v[14]=-100; return m; }
using AddFn=int(*)(int);
__declspec(noinline) int Helper(int x) { volatile int n=3; return x+n; }
__declspec(noinline) int Target(int x) { return Helper(x)+2; }
AddFn original=nullptr;
int Hook(int x) { return original(x)+10; }
using NativeFn=void(*)(int*);
NativeFn nativeOriginal=nullptr;
void NativeHook(int* count) { nativeOriginal(count); *count+=10; }
int main(int argc,char** argv) {
    Matrix m=Identity(), to{};
    Check(ValidMatrix(m),"normalized affine matrix");
    Check(Step(m,2.5f,to)&&std::fabs(to.v[14]+97.5f)<0.0001f&&to.v[13]==50,"horizontal forward distance preserves height");
    Matrix diagonal=m; diagonal.v[0]=0.70710678f; diagonal.v[2]=-0.70710678f; diagonal.v[8]=0.70710678f; diagonal.v[10]=0.70710678f;
    Check(Step(diagonal,2.5f,to)&&std::fabs(Separation(diagonal,to)-2.5f)<0.001f,"diagonal distance normalized");
    Matrix bad=m; bad.v[12]=std::numeric_limits<float>::quiet_NaN(); Check(!Step(bad,2.5f,to),"NaN rejected");
    bad=m; bad.v[0]=2; Check(!Step(bad,2.5f,to),"un-normalized scale rejected");
    bad=m; bad.v[4]=0.5f; Check(!Step(bad,2.5f,to),"sheared basis rejected");
    bad=m; bad.v[3]=1; Check(!Step(bad,2.5f,to),"non-affine matrix rejected");
    bad=m; bad.v[12]=20000; bad.v[8]=1; bad.v[10]=0; bad.v[0]=0; bad.v[2]=-1; Check(!Step(bad,2.5f,to),"world bounds enforced");
    bad=m; bad.v[5]=0;bad.v[6]=-1;bad.v[9]=1;bad.v[10]=0; Check(!Step(bad,2.5f,to),"vertical facing rejected");
    Check(!Step(m,0.1f,to)&&!Step(m,5.1f,to)&&!Step(m,std::numeric_limits<float>::infinity(),to),"step range enforced");
    Check(Vertical(m,1.0f,to)&&to.v[13]==51&&to.v[12]==m.v[12]&&to.v[14]==m.v[14],"upward world Y move preserves horizontal coordinates");
    Check(Vertical(m,-1.0f,to)&&to.v[13]==49,"downward world Y move");
    Check(!Vertical(m,0,to)&&!Vertical(m,-5.1f,to)&&!Vertical(m,std::numeric_limits<float>::quiet_NaN(),to),"vertical distance limits");
    bad=m; bad.v[13]=-20000; Check(!Vertical(bad,-1,to),"vertical world bounds");
    Context c{0x108562,0x10000,0x20000,123}; Anchor a{true,m,c,1000};
    Step(m,2.5f,to); Check(CanReturn(a,c,to,2000),"return within same scene and identity");
    Context changed=c; ++changed.scene; Check(!CanReturn(a,changed,to,2000),"return blocked after objective/scene change");
    changed=c; changed.handle^=0x100000; Check(!CanReturn(a,changed,to,2000),"return blocked after generation change");
    changed=c; ++changed.mover; Check(!CanReturn(a,changed,to,2000),"return blocked after mover replacement");
    Check(!CanReturn(a,c,to,999)&&!CanReturn(a,c,to,121001),"return time window enforced");
    to=m;to.v[14]+=13;Check(!CanReturn(a,c,to,2000),"return range enforced");
    Check(MH_Initialize()==MH_OK,"hook library initializes in isolated harness");
    Check(MH_CreateHook(reinterpret_cast<void*>(&Target),reinterpret_cast<void*>(&Hook),reinterpret_cast<void**>(&original))==MH_OK,"trampoline created");
    Check(MH_EnableHook(reinterpret_cast<void*>(&Target))==MH_OK,"hook enabled in isolated harness");
    volatile AddFn indirect=Target; Check(indirect(7)==22&&original(7)==12,"relative call relocation and original chain");
    Check(MH_DisableHook(reinterpret_cast<void*>(&Target))==MH_OK&&indirect(7)==12,"hook restoration");
    Check(MH_Uninitialize()==MH_OK,"hook cleanup");
    unsigned char* page=static_cast<unsigned char*>(VirtualAlloc(nullptr,4096,MEM_RESERVE|MEM_COMMIT,PAGE_EXECUTE_READWRITE));
    Check(page!=nullptr,"native-pattern test memory allocation");
    if(page) {
        const unsigned char body[]={0x40,0x53,0x48,0x83,0xec,0x20,0x48,0x8b,0xd9,0xe8,0,0,0,0,0x48,0x8b,0xcb,0x48,0x83,0xc4,0x20,0x5b,0xe9,0,0,0,0};
        memcpy(page,body,sizeof(body));
        *reinterpret_cast<int*>(page+10)=128-14;
        *reinterpret_cast<int*>(page+23)=192-27;
        page[128]=0xff;page[129]=0x01;page[130]=0xc3;
        page[192]=0xff;page[193]=0x01;page[194]=0xc3;
        NativeFn fn=reinterpret_cast<NativeFn>(page);
        int count=0; fn(&count); Check(count==2,"audited commit prologue and tail pattern execute with test-only stubs");
        unsigned char before[27];memcpy(before,page,sizeof(before));
        void* trampoline=nullptr;
        Check(MH_Initialize()==MH_OK&&MH_CreateHook(page,reinterpret_cast<void*>(&NativeHook),&trampoline)==MH_OK,"audited native prologue trampoline creation");
        nativeOriginal=reinterpret_cast<NativeFn>(trampoline);
        Check(MH_EnableHook(page)==MH_OK,"audited native prologue hook enables");
        count=0; fn(&count);Check(count==12,"native-pattern hook preserves this argument and original chain");
        count=0; reinterpret_cast<NativeFn>(trampoline)(&count); Check(count==2,"native-pattern relocated relative call and tail jump");
        Check(MH_DisableHook(page)==MH_OK&&!memcmp(page,before,sizeof(before)),"native-pattern bytes restore exactly");
        Check(MH_Uninitialize()==MH_OK,"native-pattern hook cleanup");
        VirtualFree(page,0,MEM_RELEASE);
    }
    if (argc>1) {
        HMODULE dll=LoadLibraryA(argv[1]); Check(dll!=nullptr,"candidate DLL loads in separate harness");
        if(dll) {
            using StatusFn=unsigned long(*)();
            auto status=reinterpret_cast<StatusFn>(GetProcAddress(dll,"DoorStepGetStatus"));
            Check(status!=nullptr,"read-only status export");
            Sleep(600);
            Check(status&&status()==0,"unsupported host remains unarmed with no game hook");
            Sleep(100); FreeLibrary(dll);
        }
    }
    printf("%d checks, %d failures; no game process or save access\n",checks,failures);
    return failures?1:0;
}
