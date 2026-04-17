다음 3가지 모델을 fastapi 로 서빙하고 싶어.
Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
Qwen/Qwen3-TTS-12Hz-1.7B-Base

관련 스크립트는 cloud_run/ 아래 파일들로 동작하면 되는데,
일단은 도커파일이나 빌드 관련 스크립트는 고려하지 않겠어.

1. 우선 위 모델을 로컬 디렉토리에 다운로드 하는 명령어를 알려주고
2. fastapi_tts_server.py & index.html 이 3가지 모델을 지원하기 위해 적절하게 수정되어야 할 것 같아.
3. cloud_run/fastapi_tts_server.py 를 여기서 바로 실행시킬때 필요한 환경변수나 옵션등에 설명해줘
