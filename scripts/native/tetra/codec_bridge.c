/* SPDX-License-Identifier: GPL-3.0-or-later
 * Receive-only bridge to the pinned tetra-kit channel and speech decoder.
 * No encoder, cipher or key interface is compiled/exported.
 */
#include <stdint.h>
#include <string.h>
#include "channel.h"
#include "source.h"
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
static int first = 1;
EXPORT void rm_reset(void) {
    first = 1;
    Init_Decod_Tetra();
}
EXPORT int rm_decode(const int16_t *frame, int16_t *output) {
    Word16 interleaved[432], coded[432], reordered[286];
    Word16 serial[138], params[24];
    int position = 0;
    for (int block=0; block<4; ++block) {
        if (frame[block*115] != 0x6b21+block) return -1;
        int count = block == 3 ? 90 : 114;
        for (int i=0; i<count; ++i) interleaved[position++] = frame[block*115+1+i];
    }
    Desinterleaving_Speech(interleaved, coded);
    int bad = Channel_Decoding(first, 0, coded, reordered);
    first = 0;
    for (int half=0; half<2; ++half) {
        serial[0] = (Word16)bad;
        memcpy(serial+1, reordered+137*half, 137*sizeof(Word16));
        Bits2prm_Tetra(serial, params);
        Decod_Tetra(params, output+half*240);
        Post_Process(output+half*240, 240);
    }
    if (bad) memset(output, 0, 480*sizeof(int16_t));
    return bad;
}
