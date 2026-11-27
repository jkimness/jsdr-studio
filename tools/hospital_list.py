#!/usr/bin/env python3
"""병원 리스트업과 주소 조회 (피부과, 성형외과, 미용 의원).

표준 라이브러리만 쓴다. 조회는 카카오맵 장소 검색.
KAKAO_REST_KEY 환경 변수가 있으면 공식 로컬 API 를, 없으면 지도 웹 검색을 천천히 쓴다.

    hospital_list.py lookup "오라클피부과" "인천" [--tel 032-566-5595]
    hospital_list.py find "강남" --kind 피부과,성형외과 [--pages 3] [--known master.csv]
    hospital_list.py enrich in.csv out.csv        # 열: 병원명, 지역, 전화 (전화는 없어도 됨)

결과의 "주소 확인" 값
    전화 일치   시트 전화와 카카오 전화가 같다 (가장 믿을 만함)
    이름 일치   이름이 맞고 그 지역에 한 곳뿐이거나 지점 이름이 지역과 맞다
    확인 필요   후보가 여럿이거나 이름 표기가 다르다. 사람이 한 번 본다
    미확인      같은 이름의 병원을 못 찾음 (주소는 비워 둔다)
"""
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SUFFIX = r'(성형외과의원|피부과의원|성형외과|피부과|클리닉|의원|병원)'
MEDICAL = ('피부과', '성형외과', '일반의원', '의원', '병원', '가정의학과', '비뇨기과', '산부인과', '이비인후과', '내과', '외과', '한의원', '치과', '안과', '정형외과', '종합병원')
TYPO = {'의언': '의원', '며동': '명동', '시논현': '신논현'}

# 상권 이름이 주소에 그대로 안 나오는 곳. 주소에 이 낱말 가운데 하나가 있으면 지역이 맞는 것으로 본다.
AREA = {
    '강남': ['강남구', '서초구'], '신논현': ['강남구', '서초구'], '논현': ['강남구'], '역삼': ['강남구'], '선릉': ['강남구'],
    '삼성': ['강남구'], '압구정': ['강남구'], '신사': ['강남구', '서초구'], '청담': ['강남구'], '도산대로': ['강남구'],
    '학동': ['강남구'], '언주': ['강남구'], '대치': ['강남구'], '한티': ['강남구'], '도곡': ['강남구'], '매봉': ['강남구'],
    '강남구청': ['강남구'], '양재': ['서초구', '강남구'], '교대': ['서초구'], '서초': ['서초구', '강남구'], '방배': ['서초구'],
    '반포': ['서초구'], '이수': ['서초구', '동작구'], '사당': ['동작구', '서초구', '관악구'], '잠실': ['송파구'], '송파': ['송파구'],
    '문정': ['송파구'], '가락': ['송파구'], '석촌': ['송파구'], '오금': ['송파구'], '위례': ['송파구', '성남시', '하남시'],
    '천호': ['강동구'], '강동': ['강동구'], '고덕': ['강동구', '평택시'], '명동': ['중구'], '시청': ['중구'], '약수': ['중구'],
    '중구': ['중구'], '홍대': ['마포구'], '합정': ['마포구'], '공덕': ['마포구'], '상암': ['마포구'], '마포': ['마포구'],
    '신촌': ['서대문구', '마포구'], '홍제': ['서대문구'], '서대문': ['서대문구'], '용산': ['용산구'], '이태원': ['용산구'],
    '한남': ['용산구'], '여의도': ['영등포구'], '영등포': ['영등포구'], '당산': ['영등포구'], '목동': ['양천구'],
    '오목교': ['양천구'], '양천': ['양천구'], '마곡': ['강서구'], '발산': ['강서구'], '화곡': ['강서구'], '강서': ['강서구'],
    '구로': ['구로구'], '신도림': ['구로구'], '금천': ['금천구'], '관악': ['관악구'], '서울대': ['관악구'],
    '서울대입구': ['관악구'], '신림': ['관악구'], '동작': ['동작구'], '상도': ['동작구'], '건대': ['광진구'],
    '광진': ['광진구'], '구의': ['광진구'], '자양': ['광진구'], '성수': ['성동구'], '왕십리': ['성동구'], '옥수': ['성동구'],
    '성동': ['성동구'], '동대문': ['동대문구', '중구', '종로구'], '청량리': ['동대문구'], '답십리': ['동대문구'],
    '종로': ['종로구'], '광화문': ['종로구', '중구'], '안국': ['종로구'], '혜화': ['종로구'], '성북': ['성북구'],
    '성신여대': ['성북구'], '노원': ['노원구'], '도봉': ['도봉구'], '쌍문': ['도봉구'], '수유': ['강북구'], '미아': ['강북구'],
    '강북': ['강북구'], '중랑': ['중랑구'], '은평': ['은평구'], '불광': ['은평구'], '연신내': ['은평구'],
    '분당': ['분당구'], '판교': ['분당구'], '서현': ['분당구'], '미금': ['분당구'], '성남': ['성남시'], '수지': ['수지구'],
    '광교': ['영통구', '수지구'], '영통': ['영통구'], '망포': ['영통구'], '동탄': ['화성시'], '일산': ['일산'], '범계': ['안양시'],
    '평촌': ['안양시'], '산본': ['군포시'], '금정': ['군포시', '금정구'], '다산': ['남양주시'], '별내': ['남양주시'],
    '송도': ['연수구'], '부평': ['부평구'], '구월': ['남동구'], '청라': ['서구'], '검단': ['서구'], '계산': ['계양구'],
    '계양': ['계양구'], '영종': ['중구'], '인하대': ['미추홀구'], '불당': ['천안시'], '둔산': ['대전'], '세종': ['세종'],
}
ZONE = [  # 권역
    ('서울 강남권', ['서울 강남구', '서울 서초구', '서울 송파구', '서울 강동구']),
    ('서울 도심, 서북권', ['서울 중구', '서울 종로구', '서울 용산구', '서울 마포구', '서울 서대문구', '서울 은평구']),
    ('서울 서남권', ['서울 영등포구', '서울 양천구', '서울 강서구', '서울 구로구', '서울 금천구', '서울 관악구', '서울 동작구']),
    ('서울 동북권', ['서울 ']),
    ('인천', ['인천 ']),
    ('경기 북부', ['경기 고양시', '경기 파주시', '경기 의정부시', '경기 양주시', '경기 남양주시', '경기 구리시', '경기 김포시', '경기 동두천시', '경기 포천시']),
    ('경기 남부', ['경기 ']),
    ('충청, 세종, 대전', ['충남 ', '충북 ', '세종', '대전 ']),
]


def digits(s):
    d = re.sub(r'\D', '', s or '')
    if re.match(r'021[5689]\d{6}$', d):  # 02-1644-8343 처럼 대표번호 앞에 02 를 붙여 적은 것
        d = d[2:]
    return d


def fix(s):
    s = (s or '').strip()
    for a, b in TYPO.items():
        s = s.replace(a, b)
    return re.sub(r'\s+', ' ', s)


def core(name, region=''):
    """브랜드 이름: 간판 유형, 지점, 지역 낱말을 뗀 것."""
    n = re.sub(r'\s+', '', fix(name))
    n = re.sub(r'[\(\[].*?[\)\]]', '', n)
    n = re.sub(SUFFIX + r'.*$', '', n) or n
    region = re.sub(r'\d.*$', '', fix(region))
    for r in filter(None, [region] + AREA.get(region, [])):
        r = r.rstrip('구시')
        if n.startswith(r) and len(n) > len(r) + 1:
            n = n[len(r):]
        elif n.endswith(r) and len(n) > len(r) + 1:
            n = n[:-len(r)]
    return n


def sign_type(name):
    """간판 유형. 전문의만 간판에 과목을 '○○피부과의원' 꼴로 쓸 수 있다는 점을 쓴 분류."""
    n = re.sub(r'\s+', '', fix(name))
    if '성형외과' in n:
        return '성형외과 전문'
    if '피부과' in n:
        return '피부과 전문'
    if re.search(r'(의원|클리닉)', n):
        return '일반 의원'
    return '미표기'


def phone_type(tel):
    d = digits(tel)
    if d.startswith('050'):
        return '안심번호 (0507)'
    if re.match(r'1[5689]\d\d', d) and len(d) == 8:
        return '대표번호'
    if d.startswith('010'):
        return '휴대전화'
    return '지역번호' if d else ''


def fmt_tel(tel):
    d = digits(tel)
    if len(d) == 8:
        return d[:4] + '-' + d[4:]
    if d.startswith('02') and len(d) in (9, 10):
        return f'02-{d[2:-4]}-{d[-4:]}'
    if d.startswith('050') and len(d) in (11, 12):
        return f'{d[:4]}-{d[4:-4]}-{d[-4:]}'
    if len(d) in (10, 11):
        return f'{d[:3]}-{d[3:-4]}-{d[-4:]}'
    return (tel or '').strip()


def zone(addr):
    for z, keys in ZONE:
        if any(addr.startswith(k) for k in keys):
            return z
    return '기타 지방' if addr else ''


def sido_sigungu(addr):
    p = addr.split()
    if not p:
        return '', ''
    if p[0].startswith('세종'):
        return '세종', ''
    sgg = p[1] if len(p) > 1 else ''
    if len(p) > 2 and p[1].endswith('시') and p[2].endswith('구'):
        sgg = p[1] + ' ' + p[2]
    return p[0], sgg


def full_address(p):
    """도로명 주소 + 건물, 층 (지번 주소 뒤쪽에서)."""
    road, lot = (p.get('new_address') or '').strip(), (p.get('address') or '').strip()
    if not road:
        return lot
    m = re.search(r'\s\d+(?:-\d+)?\s+(.+)$', lot)
    return f'{road} ({m.group(1)})' if m else road


_last = [0.0]


def search(query, page=1, pause=0.6):
    """카카오맵 장소 검색. [{id, name, tel, address, new_address, cate, homepage}]"""
    wait = pause - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    key = os.environ.get('KAKAO_REST_KEY')
    try:
        if key:
            u = 'https://dapi.kakao.com/v2/local/search/keyword.json?' + urllib.parse.urlencode({'query': query, 'page': page, 'size': 15})
            d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'Authorization': 'KakaoAK ' + key}), timeout=15).read())
            out = [dict(id=x['id'], name=x['place_name'], tel=x['phone'], address=x['address_name'], new_address=x['road_address_name'],
                        cate=x['category_name'].split(' > ')[-1], homepage='') for x in d.get('documents', [])]
        else:
            u = 'https://search.map.kakao.com/mapsearch/map.daum?' + urllib.parse.urlencode({'q': query, 'msFlag': 'A', 'sort': 0, 'page': page})
            req = urllib.request.Request(u, headers={'Referer': 'https://map.kakao.com/', 'User-Agent': 'Mozilla/5.0'})
            d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode('utf-8'))
            out = [dict(id=str(x.get('confirmid')), name=x.get('name'), tel=x.get('tel'), address=x.get('address'), new_address=x.get('new_address'),
                        cate=x.get('cate_name_depth3') or x.get('last_cate_name') or '', homepage=x.get('homepage') or '') for x in d.get('place', [])]
    finally:
        _last[0] = time.time()
    return out


def region_ok(p, region):
    region = re.sub(r'\d.*$', '', fix(region)).rstrip('구시') if len(fix(region)) > 2 else fix(region)
    if not region:
        return False
    hay = (p.get('name') or '') + ' ' + (p.get('new_address') or '') + ' ' + (p.get('address') or '')
    return region in hay or any(a in hay for a in AREA.get(region, []))


def pick(cands, name, region, tel=''):
    """후보에서 하나 고르기. (후보 또는 None, 주소 확인 값)"""
    cands = [p for p in (cands or []) if isinstance(p, dict)]
    med = [p for p in cands if any(m in (p.get('cate') or '') for m in MEDICAL)]
    if not med:
        return None, '미확인'
    t = digits(tel)
    if t:
        for p in med:
            if digits(p.get('tel')) == t:
                return p, '전화 일치'
    c = core(name, region)
    flat = lambda x: re.sub(r'\s+', '', x or '').lower()
    c = c.lower()
    same = [p for p in med if c and c in flat(p.get('name'))]
    here = [p for p in same if region_ok(p, region)]
    # 안심번호(0507)는 진짜 번호와 끝 네 자리가 같은 일이 많다
    tail = [p for p in same if len(t) >= 8 and digits(p.get('tel'))[-4:] == t[-4:]]
    for group in ([p for p in tail if p in here], tail if len(tail) == 1 else []):
        if group:
            return group[0], '이름 일치'
    if here:
        r = flat(region)
        exact = [p for p in here if flat(p['name']).replace('점', '') in (flat(name), flat(name) + '의원', flat(name) + r, r + flat(name), flat(name) + '의원' + r)]
        roads = {p.get('new_address') or p.get('address') for p in here}
        if len(here) == 1 or len(roads) == 1 or len(exact) == 1:
            return (exact or here)[0], '이름 일치'
        return here[0], '확인 필요'
    if same:
        return same[0], '확인 필요'
    # 이름 표기가 다른데(영문, 한글) 끝 네 자리와 지역이 맞는 곳. 사람이 한 번 본다
    alt = [p for p in med if len(t) >= 8 and digits(p.get('tel'))[-4:] == t[-4:] and region_ok(p, region)]
    if len(alt) == 1:
        return alt[0], '확인 필요'
    return None, '미확인'


def lookup(name, region, tel='', cands=None):
    name, region = fix(name), fix(region)
    if cands is None:
        cands = search(f'{name} {region}'.strip())
        for q in (f'{core(name, region)} {region}', name, core(name, region) + ' 의원'):
            if not cands:
                cands = search(q.strip())
    p, status = pick(cands, name, region, tel)
    row = {'병원명': name, '지역': region, '주소': '', '시도': '', '시군구': '', '권역': '', '카카오 전화': '', '진료과': '',
           '카카오 등록명': '', '홈페이지': '', '카카오맵': '', '주소 확인': status, '카카오 ID': ''}
    if p:
        addr = full_address(p)
        sido, sgg = sido_sigungu(p.get('new_address') or p.get('address') or '')
        row.update({'주소': addr, '시도': sido, '시군구': sgg, '권역': zone(addr), '카카오 전화': p.get('tel') or '', '진료과': p.get('cate') or '',
                    '카카오 등록명': p.get('name') or '', '홈페이지': p.get('homepage') or '',
                    '카카오맵': f"https://place.map.kakao.com/{p['id']}", '카카오 ID': p['id']})
    row['간판 유형'] = sign_type(row['카카오 등록명'] or name)
    row['브랜드'] = core(name, region)
    return row


def find(region, kinds, pages=3, known=None):
    """지역의 병원 후보 모으기. known 에 있는 곳(카카오 ID, 전화, 이름+시군구)은 뺀다."""
    seen_id, seen_tel, seen_name = set(), set(), set()
    for k in known or []:
        m = re.search(r'(\d+)$', k.get('카카오맵') or '')
        if m:
            seen_id.add(m.group(1))
        for col in ('카카오 전화', '시트 기재 전화', '전화'):
            if digits(k.get(col)):
                seen_tel.add(digits(k.get(col)))
        seen_name.add((core(k.get('병원명', ''), k.get('지역', '')), k.get('시군구', '')))
    out = []
    for kind in kinds:
        for page in range(1, pages + 1):
            got = search(f'{region} {kind}', page)
            if not got:
                break
            for p in got:
                if not any(m in (p.get('cate') or '') for m in ('피부과', '성형외과', '의원')):
                    continue
                row = lookup(p['name'], region, cands=[p])
                row['주소 확인'] = '검색 결과'
                key = (row['브랜드'], row['시군구'])
                if p['id'] in seen_id or (digits(p.get('tel')) and digits(p.get('tel')) in seen_tel) or key in seen_name:
                    continue
                seen_id.add(p['id'])
                out.append(row)
    return out


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(rows, f):
    if not rows:
        return
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)


def main(a):
    if len(a) >= 2 and a[0] == 'lookup':
        tel = a[a.index('--tel') + 1] if '--tel' in a else ''
        print(json.dumps(lookup(a[1], a[2] if len(a) > 2 and not a[2].startswith('--') else '', tel), ensure_ascii=False, indent=1))
    elif len(a) >= 2 and a[0] == 'find':
        kinds = a[a.index('--kind') + 1].split(',') if '--kind' in a else ['피부과', '성형외과']
        pages = int(a[a.index('--pages') + 1]) if '--pages' in a else 3
        known = read_csv(a[a.index('--known') + 1]) if '--known' in a else None
        rows = find(a[1], kinds, pages, known)
        write_csv(rows, sys.stdout)
        print(f'{len(rows)}곳 (이미 있는 곳 제외)', file=sys.stderr)
    elif len(a) >= 3 and a[0] == 'enrich':
        src = read_csv(a[1])
        out = []
        for i, r in enumerate(src):
            row = lookup(r.get('병원명', ''), r.get('지역', ''), r.get('전화', ''))
            out.append({**r, **{k: v for k, v in row.items() if k not in ('병원명', '지역')}})
            if i % 25 == 0:
                print(f'{i + 1}/{len(src)}', file=sys.stderr)
        with open(a[2], 'w', encoding='utf-8-sig', newline='') as f:
            write_csv(out, f)
    else:
        print(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
