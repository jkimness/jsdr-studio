#!/bin/zsh
# JSDR 영상 스튜디오 설치와 갱신. 처음 한 번, 그리고 git pull 뒤마다 돌린다.
#   ./setup.sh
set -e
cd "$(dirname "$0")"
echo "1. 도구 확인"
for t in ffmpeg ffprobe whisper-cli; do
  command -v $t >/dev/null || { echo "  없음: $t  →  brew install ffmpeg whisper-cpp"; MISSING=1; }
done
[ -n "$MISSING" ] && exit 1
echo "2. 파이썬 모듈 (맥 기본 파이썬 /usr/bin/python3)"
/usr/bin/python3 -c "import numpy, PIL, cv2" 2>/dev/null || /usr/bin/python3 -m pip install --user numpy pillow opencv-python-headless
echo "3. 전사 모델 (1.6GB, 처음 한 번)"
M=~/.cache/jsdr-studio/models/ggml-large-v3-turbo.bin
if [ ! -f config/local.json ] || ! grep -q model_path config/local.json; then
  if [ ! -f $M ]; then
    mkdir -p ~/.cache/jsdr-studio/models
    curl -L --fail -o $M.part https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin && mv $M.part $M
  fi
fi
echo "4. 폴더"
mkdir -p kit plans work deliver
[ -f kit/logo.png ] || echo "  kit/ 에 logo.png, intro.mp4, outro.mp4 를 넣어 주세요 (팀 공유 드라이브의 편집 키트). 다른 자리에 두려면 config/local.json 에 \"kit\" 경로를 적습니다"
echo "5. Claude Code 스킬"
if command -v claude >/dev/null; then
  claude plugin marketplace add "$(pwd)" 2>/dev/null || claude plugin marketplace update jsdr-studio 2>/dev/null || true
  claude plugin install jsdr@jsdr-studio 2>/dev/null || claude plugin update jsdr@jsdr-studio 2>/dev/null || true
  echo "  Claude Code 를 다시 열면 jsdr:jsdr-studio, jsdr:jsdr-edit, jsdr:jsdr-shorts 가 보입니다"
else
  echo "  claude 명령이 없습니다. Claude Code 를 설치한 뒤 다시 돌려 주세요"
fi
echo "끝. 시험: /usr/bin/python3 tools/jsdr_edit.py"
