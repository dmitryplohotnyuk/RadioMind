$ErrorActionPreference = 'Stop'
$fixtureRoot = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'runtime\fixtures'
New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $synth.SetOutputToWaveFile((Join-Path $fixtureRoot 'speech.wav'), $format)
    $synth.Speak('This is a local radio test. The receiver is recording a short voice message. We are testing clear speech, silence, and the automatic scanner. Please check that the beginning and ending of every sentence are preserved.')
} finally { $synth.Dispose() }
