# 전체 TTS 모델 목록

| #  | 모델                   | HuggingFace ID                         | 아키텍처                                                            |
|----|------------------------|----------------------------------------|---------------------------------------------------------------------|
| 1  | **Qwen3-TTS**          | `Qwen/Qwen3-TTS-12Hz-*`                | `Qwen3TTSTalkerForConditionalGeneration` + `Qwen3TTSCode2Wav`       |
| 2  | **Fish Speech S2 Pro** | `fishaudio/s2-pro`                     | `FishSpeechSlowARForConditionalGeneration` + `FishSpeechDACDecoder` |
| 3  | **Voxtral TTS**        | `mistralai/Voxtral-4B-TTS-2603`        | `VoxtralTTSForConditionalGeneration` + `VoxtralTTSAudioTokenizer`   |
| 4  | **CosyVoice3**         | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | `CosyVoice3Model` + `CosyVoice3Code2Wav`                            |
| 5  | **VoxCPM 1.5**         | `OpenBMB/VoxCPM1.5`                    | `VoxCPMForConditionalGeneration`                                    |
| 6  | **VoxCPM2**            | `openbmb/VoxCPM2`                      | `VoxCPM2TalkerForConditionalGeneration`                             |
| 7  | **OmniVoice**          | `k2-fsa/OmniVoice`                     | `OmniVoiceModel`                                                    |
| 8  | **MiMo-Audio**         | `XiaomiMiMo/MiMo-Audio-7B-Instruct`    | `MiMoAudioForConditionalGeneration` + `MiMoAudioToken2Wav...`       |
| 9  | **Qwen3-Omni**         | `Qwen/Qwen3-Omni-30B-A3B-Instruct`     | `Qwen3OmniMoeForConditionalGeneration` + `Qwen3OmniMoeCode2Wav`     |
| 10 | **Qwen2.5-Omni**       | `Qwen/Qwen2.5-Omni-7B`, `3B`           | `Qwen2_5OmniForConditionalGeneration` + `Qwen2_5OmniToken2Wav...`   |

---

## Qwen3-TTS 모델 목록

| 크기 | 타입        | HuggingFace ID                         |
|------|-------------|----------------------------------------|
| 1.7B | CustomVoice | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` |
| 1.7B | VoiceDesign | `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` |
| 1.7B | Base        | `Qwen/Qwen3-TTS-12Hz-1.7B-Base`        |
| 0.6B | CustomVoice | `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` |
| 0.6B | Base        | `Qwen/Qwen3-TTS-12Hz-0.6B-Base`        |

모든 Qwen3-TTS 모델은 2-stage 파이프라인으로 동작합니다:
- **Stage 0**: `Qwen3TTSTalkerForConditionalGeneration` (AR 토큰 생성)
- **Stage 1**: `Qwen3TTSCode2Wav` (코드→파형 변환, 24kHz 출력)

모델 구현: `vllm_omni/model_executor/models/qwen3_tts/`
Stage config: `vllm_omni/model_executor/stage_configs/qwen3_tts.yaml`

