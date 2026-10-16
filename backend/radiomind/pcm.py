"""One audio scale for VAD and storage; never amplify quiet receiver noise."""

import numpy as np
from numpy.typing import NDArray

from radiomind.nfm import Audio

PCM_GAIN = 0.25  # 12 dB headroom relative to nominal 2.5 kHz FM deviation.


def pcm16(audio: Audio) -> NDArray[np.int16]:
    scaled = audio * PCM_GAIN
    magnitude = np.abs(scaled)
    # Linear for ordinary speech; continuous soft knee for exceptional peaks.
    # Keep overload metrics on the unmodified signal, not this bounded output.
    limited = np.where(magnitude <= 0.8, magnitude, 0.8 + 0.19 * np.tanh((magnitude - 0.8) / 0.19))
    return np.asarray(np.sign(scaled) * limited * 32767, dtype="<i2")
