// SPDX-License-Identifier: GPL-3.0-or-later
// Stdin: unpacked receive bits. Stdout: bounded metadata/clear decoded PCM JSON.
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#else
#include <dlfcn.h>
#endif
#include "decoder.h"
#include "bridge_api.h"
#include <rapidjson/document.h>

using Reset = void (*)();
using Decode = int (*)(const int16_t *, int16_t *);
static Decode codecs[4];
static unsigned valid_syncs = 0;

void rm_sync(unsigned tn, unsigned fn, unsigned mn, unsigned mcc, unsigned mnc, unsigned color) {
    if (tn<1 || tn>4 || fn<1 || fn>18 || mn<1 || mn>60) return;
    ++valid_syncs;
    std::printf("{\"type\":\"sync\",\"tn\":%u,\"fn\":%u,\"mn\":%u,\"mcc\":%u,\"mnc\":%u,\"color\":%u}\n",
                tn,fn,mn,mcc,mnc,color);
    std::fflush(stdout);
}
void rm_report(const char *json) {
    rapidjson::Document doc;
    doc.Parse(json);
    if (doc.HasParseError() || !doc.IsObject() || !doc.HasMember("service") ||
        !doc["service"].IsString() || std::strcmp(doc["service"].GetString(),"UPLANE")) return;
    if (!doc.HasMember("tn") || !doc["tn"].IsUint() || !doc.HasMember("encryption mode") ||
        !doc["encryption mode"].IsUint()) return;
    unsigned slot=doc["tn"].GetUint(), encryption=doc["encryption mode"].GetUint();
    if (slot<1 || slot>4 || valid_syncs<2) return;
    if (encryption != 0) {
        if (encryption != 255) {
            std::printf("{\"type\":\"encrypted\",\"slot\":%u}\n",slot);
            std::fflush(stdout);
        }
        return; // Unknown and encrypted allocation never reaches the vocoder.
    }
    if (!doc.HasMember("fn") || !doc["fn"].IsUint() || !doc.HasMember("mn") || !doc["mn"].IsUint()) return;
    unsigned fn=doc["fn"].GetUint(), mn=doc["mn"].GetUint();
    if (fn<1 || fn>17 || mn<1 || mn>60) return;
    if (!doc.HasMember("frame") || !doc["frame"].IsString() || doc["frame"].GetStringLength()!=1840) return;
    int16_t frame[690], pcm[480];
    unsigned size=Tetra::b64Decode((const unsigned char*)doc["frame"].GetString(),1840,(unsigned char*)frame);
    if (size != sizeof(frame) || codecs[slot-1](frame,pcm) != 0) return;
    unsigned char encoded[1281];
    Tetra::b64Encode((const unsigned char*)pcm,sizeof(pcm),encoded);
    std::printf("{\"type\":\"audio\",\"slot\":%u,\"fn\":%u,\"mn\":%u,\"pcm\":\"%s\"}\n",slot,fn,mn,encoded);
    std::fflush(stdout);
}
int main() {
    try {
#ifdef _WIN32
        _setmode(_fileno(stdin),_O_BINARY);
        _setmode(_fileno(stdout),_O_BINARY);
#endif
        for (int slot=0;slot<4;++slot) {
            char name[64];
#ifdef _WIN32
            std::snprintf(name,sizeof(name),".\\codec-%d.dll",slot+1);
            auto module=LoadLibraryA(name);
            if (!module) throw std::runtime_error("codec load failed");
            auto reset=(Reset)GetProcAddress(module,"rm_reset");
            codecs[slot]=(Decode)GetProcAddress(module,"rm_decode");
#else
            std::snprintf(name,sizeof(name),"./codec-%d.so",slot+1);
            auto module=dlopen(name,RTLD_NOW|RTLD_LOCAL);
            if (!module) throw std::runtime_error("codec load failed");
            auto reset=(Reset)dlsym(module,"rm_reset");
            codecs[slot]=(Decode)dlsym(module,"rm_decode");
#endif
            if (!reset || !codecs[slot]) throw std::runtime_error("codec ABI mismatch");
            reset();
        }
        Tetra::TetraDecoder decoder(-1,true,Tetra::LogLevel::NONE,false,0);
        unsigned char bits[4096];
        size_t count;
        while ((count=std::fread(bits,1,sizeof(bits),stdin))>0) {
            for (size_t i=0;i<count;++i) {
                if (bits[i]>1) return 2;
                decoder.rxSymbol(bits[i]);
            }
        }
        return std::ferror(stdin) ? 3 : 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr,"TETRA receiver error: %s\n",error.what());
        return 1;
    }
}
