# JSDR 영상 스튜디오

원장님 인터뷰 원본 하나를 채널 편집본(가로 롱폼)과 세로 숏폼으로 만드는 도구와 Claude Code 스킬입니다.
nesscre8tive × AI Storians 가 JSDR, 진성형외과 마케팅팀과 같이 쓰려고 만들었습니다.

## 설치 (맥)

    brew install ffmpeg whisper-cpp
    git clone https://github.com/jkimness/jsdr-studio.git ~/Projects/jsdr-studio
    cd ~/Projects/jsdr-studio && ./setup.sh

새 판 받기:

    cd ~/Projects/jsdr-studio && git pull && ./setup.sh

그다음 `kit/` 폴더에 편집 키트(logo.png, intro.mp4, outro.mp4)를 넣습니다. 키트와 원본 영상은 이 저장소에 들어 있지 않습니다.

## 쓰는 법

Claude Code 를 `~/Projects/jsdr-studio` 에서 열고 이렇게 말합니다.

- "이 원본 편집해 줘: <영상 경로>" → 스킬 `jsdr:jsdr-studio` 가 준비부터 최종판까지 안내합니다
- "숏폼도 뽑아 줘" → `jsdr:jsdr-shorts`

직접 돌릴 수도 있습니다.

    /usr/bin/python3 tools/jsdr_edit.py prep  "<원본.mp4>" <편>     # 전사와 계획 초안 (3분)
    /usr/bin/python3 tools/jsdr_edit.py check <편>                  # 계획 검사
    /usr/bin/python3 tools/jsdr_edit.py build <편> --draft          # 1080p 시험판 (3분)
    /usr/bin/python3 tools/jsdr_edit.py build <편>                  # 4K 최종판 (5분, 300MB 안)
    /usr/bin/python3 tools/jsdr_edit.py shorts <편>                 # 세로 숏폼

## 무엇을 해 주나

- 촬영 준비, 반복 질문, 곁가지를 덜어 원본의 절반 아래로 줄입니다 (무엇을 뺄지는 계획 파일에서 사람이 봅니다)
- 컷마다 확대 단계를 바꾸고, 한 줄 자막, 챕터 표시, 로고, 댓글 카드, 큰 제목, 전체 화면 자료와 동그란 원장님 창, 인트로와 아웃트로를 얹습니다
- 소리는 -14 LUFS 로 맞춥니다
- 같은 계획에서 세로 숏폼을 뽑습니다

## 브랜드 테마

`config/themes/jinps.json` 진성형외과와 솔직한의사생활, `config/themes/juvgen.json` JSDR 과 JUVGEN.
기준은 `config/brands.json` 입니다. 두 채널에 올라와 있던 영상과 인스타에서 잰 값이고, 색이 원본과 몇 단계 다를 수 있습니다. 고치려면 테마 파일만 고치면 됩니다.

## 꼭 읽을 것

[RULES.md](RULES.md): 의료 영상이라 자막, 환자 사진, 댓글, 제목에 지킬 것이 있습니다.

## 알려진 것

- 맥 전용입니다 (영상 인코더가 맥의 VideoToolbox).
- 전사는 컴퓨터 안에서 돕니다 (whisper.cpp). 영상과 소리가 밖으로 나가지 않습니다.
- 서체: Pretendard, 나눔손글씨 펜 (둘 다 SIL OFL).
