"""Bounded decoded PCM timeline with approximate reply-gap placement."""

import numpy as np
from scipy import signal

from radiomind.digital import AudioPacket
from radiomind.nfm import Audio
from radiomind.pcm import PCM_GAIN


class DigitalTimeline:
    """Keep decoded frames and reply gaps, never mix simultaneous TDMA slots.

    The unframed decoder transport has no RF timestamps. Gap placement is approximate
    at the input-block clock; contiguous packets always retain all decoded samples.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.bytes = 0
        self.packets: list[tuple[int, AudioPacket]] = []
        self.end = 0
        self.last_input = 0.0
        self.has_audio = False
        self.channels = 1

    def append(self, packets: list[AudioPacket]) -> bool:
        voice = False
        for packet in packets:
            if (
                len(packet.pcm) not in {320, 640}
                or not np.isfinite(packet.input_seconds)
                or packet.input_seconds < 0
            ):
                raise RuntimeError("Invalid digital PCM packet")
            if packet.slot is not None and (
                packet.slot not in {1, 2, 3, 4} or packet.channels != 1
            ):
                raise RuntimeError("Invalid digital slot packet")
            self.channels = max(self.channels, packet.slot or packet.channels)
            if self.bytes + len(packet.pcm) > self.max_bytes:
                raise RuntimeError("Digital RAM quota reached; capture interrupted")
            start = self.end
            if packet.sample_offset is not None:
                start = packet.sample_offset
                if type(start) is not int or start < 0:
                    raise RuntimeError("Invalid digital sample offset")
            elif self.packets and packet.input_seconds - self.last_input > 0.4:
                start += round((packet.input_seconds - self.last_input - 0.02) * 8000)
            # Also bound sparse pauses, not only packed PCM bytes.
            if (max(self.end, start + 160)) * max(2, self.channels) * 2 > self.max_bytes:
                raise RuntimeError("Digital timeline quota reached; capture interrupted")
            self.packets.append((start, packet))
            self.end = max(self.end, start + 160)
            self.last_input = packet.input_seconds
            self.bytes += len(packet.pcm)
            voice |= bool(np.any(np.abs(np.frombuffer(packet.pcm, dtype="<i2").astype(int)) > 8))
        self.has_audio |= voice
        return voice

    def tracks(self) -> list[tuple[int, Audio]]:
        stereo = np.zeros((self.end, self.channels), dtype=np.float64)
        for start, packet in self.packets:
            samples = np.frombuffer(packet.pcm, dtype="<i2").reshape(160, packet.channels)
            if packet.slot is not None:
                stereo[start : start + 160, packet.slot - 1 : packet.slot] = (
                    samples / 32768 / PCM_GAIN
                )
            else:
                stereo[start : start + 160, : packet.channels] = samples / 32768 / PCM_GAIN
        return [
            (slot + 1, np.asarray(signal.resample_poly(stereo[:, slot], 2, 1)))
            for slot in range(self.channels)
            if np.any(np.abs(stereo[:, slot]) > 8 / 32768 / PCM_GAIN)
        ]
