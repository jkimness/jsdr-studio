---
name: jsdr-studio
description: JSDR, 진성형외과 영상 스튜디오 총괄. 원장님 인터뷰 원본 하나로 가로 롱폼 편집본(유튜브 솔직한의사생활)과 세로 숏폼(쇼츠, 릴스)을 순서대로 만든다. 준비(전사), 편집 계획, 자료와 댓글, 검사, 시험판, 최종판, 숏폼까지 한 흐름. 브랜드 테마는 진성형외과(jinps)와 JSDR, JUVGEN(juvgen) 두 벌. Use when someone gives a JSDR / 진성형외과 / 솔직한의사생활 / 쥬브젠 원본 영상 and says 영상 만들어 줘, 편집해 줘, 롱폼이랑 숏폼 다, 스튜디오, 전부 만들어 줘, or asks how this studio works or how to install it.
arguments: [원본 영상 경로, 편 이름]
---

# jsdr-studio: 원본 하나로 롱폼과 숏폼까지

저장소는 `~/Projects/jsdr-studio`. 모든 명령은 그 폴더에서 돌린다. 시작 전에 `RULES.md` 를 읽는다 (의료 영상이라 말, 자료, 파일 규칙이 있다).

## 처음 한 번, 그리고 갱신

    git clone https://github.com/jkimness/jsdr-studio.git ~/Projects/jsdr-studio
    cd ~/Projects/jsdr-studio && ./setup.sh

새 판을 받을 때:

    cd ~/Projects/jsdr-studio && git pull && ./setup.sh

`kit/` 에 편집 키트(logo.png, intro.mp4, outro.mp4, 자료 그림)를 넣는다. 다른 자리에 두려면 `config/local.json` 에 `{"kit": "<경로>"}`.

## 어느 브랜드인가 먼저

| 테마 | 언제 | 모양 |
|---|---|---|
| `jinps` (기본) | 진성형외과, 솔직한의사생활 (유튜브 @Drchin777, 인스타 @drchin777) | 남색 #102040, 파랑 #2E54BA, 노랑 강조, 손글씨 챕터, 댓글 카드. 숏폼은 꽉 찬 화면에 제목 두 줄 상자 |
| `juvgen` | JSDR 회사, JUVGEN 제품 (유튜브 @JUVGEN, 인스타 @juvgen.korea) | 남보라 #28264E, 흰 글자, 장식 없음. 색 강조, 손글씨, 댓글 카드, 효과음을 쓰지 않는다 |

기준은 `config/brands.json` 이다. 공식 가이드 파일 없이 2026-11-27 에 올라와 있던 두 채널의 영상과 인스타에서 잰 값이라, 썸네일, 전후 사진 카드, 피드 카드 모양도 거기 적혀 있다. 썸네일과 카드를 만들 일이 있으면 그 파일을 먼저 읽는다.

계획 파일 맨 위에 `"theme": "juvgen"` 을 적으면 바뀐다. 요청에 어느 브랜드인지 없으면 묻는다. 두 브랜드의 로고와 범퍼를 한 영상에 섞지 않는다.
`juvgen` 은 `kit/logo-juvgen.png` 를 쓰고, 인트로와 아웃트로가 없으면 계획의 `intro`, `outro` 를 지운다.

## 흐름

| 단계 | 하는 일 | 스킬, 명령 | 사람이 볼 것 |
|---|---|---|---|
| 1 | 준비: 말 덩어리, 전사, 얼굴 자리, 계획 초안 | `prep` | 없음 |
| 2 | 편집 계획: 무엇을 빼고 남길지, 자막, 챕터 | jsdr-edit 2절 | 뺀 대목 목록 |
| 3 | 자료 그림과 댓글 | jsdr-edit 3절 | 환자 사진 동의, 댓글 출처 |
| 4 | 검사와 1080p 시험판 | `check`, `listen`, `build --draft`, `sheet --draft` | 시험판 한 번 |
| 5 | 최종판 4K (300MB 안) | `build`, `sheet` | 최종 확인 |
| 6 | 숏폼: 롱폼 계획에서 구간을 골라 세로 카드로 | jsdr-shorts | 제목 고르기 |

한 단계가 끝나면 무엇이 나왔고 다음에 사람이 정할 것이 무엇인지 한두 줄로 알린다. 전체를 여러 번 굽지 않는다. 고친 줄만 `--only` 로 본다.
올리는 일(유튜브, 인스타)은 이 스튜디오가 하지 않는다. 파일과 제목, 설명 초안까지만 만든다.

## 폴더

    tools/jsdr_edit.py     도구 하나
    config/jsdr.json       기본값, config/themes/ 브랜드 테마, config/local.json 이 컴퓨터만의 값 (git 밖)
    examples/              기준 편집 계획
    plans/  work/  kit/    편집 계획, 작업물, 편집 키트 (git 밖)
    skills/                이 문서들 (Claude Code 플러그인 jsdr)
