#!/usr/bin/python3
"""JSDR 솔직한의사생활 인터뷰 편집 (원장님 한 분 + 화면 밖 PD, 고정 카메라 한 대, 가로 16:9).

    /usr/bin/python3 tools/jsdr_edit.py prep  <원본.mp4> <편>     # 말 덩어리, 전사, 얼굴 자리, 편집 계획 초안
    /usr/bin/python3 tools/jsdr_edit.py check <편>                # 계획 검사 (굽기 전 필수)
    /usr/bin/python3 tools/jsdr_edit.py build <편> [--draft] [--only 0:20] [--reuse]   # --reuse: 소리나 이어 붙이기만 다시 (계획을 고쳤으면 쓰지 않는다)
    /usr/bin/python3 tools/jsdr_edit.py sheet <편> [--draft]      # 완성본 장면 모음과 길이, 음량
    /usr/bin/python3 tools/jsdr_edit.py shorts <편> [id] [--draft] # 계획의 shorts 를 세로 1080x1920 카드로
    /usr/bin/python3 tools/jsdr_edit.py listen <편> [a b ...]     # 자른 조각 다시 듣기
    /usr/bin/python3 tools/jsdr_edit.py dips <편> a b             # 그 사이 소리가 꺼지는 자리

2026-11-27 "쥬브젠 시술부위" 편집 전, 편집 후 영상을 재서 만든 문법:
  준비 구간과 반복을 덜어 절반쯤으로, 컷마다 확대 단계(원본, 1.3배, 1.55배) 바꾸기, 한 줄 자막(PD 질문 낱말 파랑, 원장님 결론 노랑),
  챕터 표시(왼쪽 위), 채널 로고(오른쪽 위), 댓글 카드, 큰 제목 한 줄, 전체 화면 자료 + 동그란 원장님 창, 인트로와 아웃트로 범퍼, -14 LUFS.

계획 파일 plans/<편>-edit.json 의 lines 가 곧 편집본이다. 줄 하나 = 원본 [a, b] 한 조각 + 자막 한 줄.
  줄을 지우면 컷, 순서를 바꾸면 재배치. 줄에 붙이는 것: who(pd, dr), text, hl(파랑 낱말 목록), em(노랑 줄), shot(wide, mid, tight),
  broll(자료 id), chapter({"n":1,"title":"인디언주름"}, 다음 챕터까지 유지, false 면 끔), card(댓글 id), title(큰 제목), nocap(자막 없음).
값은 config/jsdr.json 한 곳. 시스템 파이썬 (numpy, cv2, PIL).
"""
import glob, json, os, re, subprocess, sys, wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


CFG = json.load(open(os.path.join(PKG, "config", "jsdr.json"), encoding="utf-8"))
_local = os.path.join(PKG, "config", "local.json")      # 이 컴퓨터만의 값 (키트, 납품 폴더, 전사 모델 자리). git 에 넣지 않는다
if os.path.exists(_local):
    _merge(CFG, json.load(open(_local, encoding="utf-8")))


def use_theme(name):
    """테마 = 브랜드별 색과 글자 (config/themes/<이름>.json). 계획의 "theme" 이 고른다. 기본은 config 의 theme."""
    t = os.path.join(PKG, "config", "themes", f"{name or CFG.get('theme', 'jinps')}.json")
    if not os.path.exists(t):
        raise SystemExit(f"  ✗ 테마가 없다: {t}")
    _merge(CFG, json.load(open(t, encoding="utf-8")))


def model_file():
    wc = CFG["whisper"]
    return os.path.expanduser(wc.get("model_path") or f"~/.cache/jsdr-studio/models/ggml-{wc['model']}.bin")
FPS_N, FPS_D = 30000, 1001
FPS = FPS_N / FPS_D


def P(p):
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(PKG, p)




def work(name):
    d = os.path.join(PKG, "work", name)
    os.makedirs(d, exist_ok=True)
    return d


def plan_path(name, kind="edit"):
    d = os.path.join(PKG, "plans")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{name}-{kind}.json")


def run(cmd, quiet=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"  ✗ 실패: {' '.join(str(c) for c in cmd[:6])} ...\n{r.stderr[-1500:]}")
    return r


def probe(src):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
             "-of", "json", src])
    j = json.loads(r.stdout)
    return float(j["format"]["duration"]), j["streams"][0]["width"], j["streams"][0]["height"]


# ───────────────────────── prep: 말 덩어리와 전사 ─────────────────────────

def envelope(wav, hop=0.01, win=0.02):
    w = wave.open(wav)
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    h, n = int(sr * hop), int(sr * win)
    k = max(0, (len(x) - n) // h)
    idx = np.arange(n)[None, :] + (np.arange(k) * h)[:, None]
    rms = np.sqrt((x[idx] ** 2).mean(axis=1) + 1e-10)
    return 20 * np.log10(rms), hop


def find_islands(db, hop):
    v = CFG["vad"]
    thr = np.percentile(db, 15) + v["up_db"]
    sp = db > thr
    raw, i, n = [], 0, len(sp)
    while i < n:
        if sp[i]:
            j = i
            while j < n and sp[j]:
                j += 1
            raw.append([i * hop, j * hop])
            i = j
        else:
            i += 1
    merged = []
    for a, b in raw:
        if merged and a - merged[-1][1] < v["min_silence"]:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    merged = [m for m in merged if m[1] - m[0] >= v["min_speech"]]
    out = []
    for k, (a, b) in enumerate(merged):
        lo = (merged[k - 1][1] + a) / 2 if k else 0.0
        hi = (b + merged[k + 1][0]) / 2 if k + 1 < len(merged) else len(db) * hop
        a2, b2 = max(lo, a - v["pad_before"]), min(hi, b + v["pad_after"])
        seg = db[int(a / hop):int(b / hop)]
        out.append({"a": round(a2, 3), "b": round(b2, 3), "db": round(float(np.percentile(seg, 75)), 1)})
    return out, float(thr)


def fix_text(t):
    t = re.sub(r"\s+", " ", t).strip()
    for k, v in CFG["corrections"].items():
        t = t.replace(k, v)
    return t


def whisper_islands(wav, isl, wd):
    d = os.path.join(wd, "isl")
    os.makedirs(d, exist_ok=True)
    for f in glob.glob(d + "/*"):
        os.remove(f)
    w = wave.open(wav)
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    pad = np.zeros(int(sr * 0.4), np.int16)
    files = []
    for k, s in enumerate(isl):
        f = os.path.join(d, f"{k:04d}.wav")
        o = wave.open(f, "w")
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr)
        o.writeframes(np.concatenate([pad, x[int(s["a"] * sr):int(s["b"] * sr)], pad]).tobytes())
        o.close()
        files.append(f)
    wc = CFG["whisper"]
    model = model_file()
    for i in range(0, len(files), 40):
        run(["whisper-cli", "-m", model, "-l", wc["lang"], "-t", "8", "-oj", "-np", "--prompt", wc["prompt"]] + files[i:i + 40])
    for k, s in enumerate(isl):
        try:
            j = json.load(open(files[k] + ".json", encoding="utf-8"))["transcription"]
            t = " ".join(x["text"].strip() for x in j if not x["text"].strip().startswith("["))
        except Exception:
            t = ""
        s["text"] = fix_text(t)
    # 전체 전사 한 번 (문맥 참고용: 덩어리 전사가 틀리게 들은 낱말을 고칠 때 본다)
    run(["whisper-cli", "-m", model, "-l", wc["lang"], "-t", "8", "-oj", "-np", "--prompt", wc["prompt"], "-of",
         os.path.join(wd, "full"), wav])
    full = json.load(open(os.path.join(wd, "full.json"), encoding="utf-8"))["transcription"]
    return [(x["offsets"]["from"] / 1000, x["offsets"]["to"] / 1000, fix_text(x["text"])) for x in full]


def guess_who(isl):
    """핀 마이크는 원장님께 있다. 화면 밖 PD 는 눈에 띄게 작게 들린다. 두 무리가 6dB 넘게 갈릴 때만 나눈다."""
    lv = np.array([s["db"] for s in isl])
    lo, hi = lv.min(), lv.max()
    for _ in range(20):
        m = (lo + hi) / 2
        a, b = lv[lv < m], lv[lv >= m]
        if not len(a) or not len(b):
            break
        lo, hi = a.mean(), b.mean()
    split = hi - lo > 6
    for s in isl:
        s["who"] = "pd" if split and s["db"] < (lo + hi) / 2 else "dr"
    return split, lo, hi


def find_face(src, wd, dur):
    import cv2
    cc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    got = []
    for k in range(12):
        f = os.path.join(wd, "face.jpg")
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * (k + 1) / 13:.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=1920:-2", f])
        g = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2GRAY)
        fs = cc.detectMultiScale(g, 1.1, 6, minSize=(110, 110))
        if len(fs):
            x, y, w, h = max(fs, key=lambda r: r[2])
            got.append(((x + w / 2) / g.shape[1], (y + h / 2) / g.shape[0], w / g.shape[1]))
    if len(got) < 4:
        raise SystemExit("  ✗ 얼굴을 못 찾았다 (12장 중 4장 미만). 구도를 눈으로 보고 계획의 face 를 손으로 적는다")
    m = np.median(np.array(got), axis=0)
    return {"cx": round(float(m[0]), 4), "cy": round(float(m[1]), 4), "w": round(float(m[2]), 4), "found": len(got)}


def split_caption(text, n):
    """자막 한 줄 n 자 안으로, 띄어쓰기에서만 나눈다. 조각 길이를 고르게."""
    if len(text) <= n:
        return [text]
    words, k = text.split(" "), -(-len(text) // n)
    target, out, cur = len(text) / k, [], ""
    for w in words:
        if cur and (len(cur) + 1 + len(w) > n or (len(cur) >= target and len(out) < k - 1)):
            out.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


def dip(db, hop, t, span=0.35):
    i0, i1 = max(0, int((t - span) / hop)), min(len(db), int((t + span) / hop))
    return (i0 + int(np.argmin(db[i0:i1]))) * hop if i1 > i0 else t


def prep(src, name):
    wd = work(name)
    src = os.path.abspath(src)
    dur, w, h = probe(src)
    wav = os.path.join(wd, "src16k.wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
    db, hop = envelope(wav)
    isl, thr = find_islands(db, hop)
    print(f"  말 덩어리 {len(isl)}개 (문턱 {thr:.1f}dB), 전사 중 ...")
    full = whisper_islands(wav, isl, wd)
    split, lo, hi = guess_who(isl)
    face = find_face(src, wd, dur)
    lines = []
    for k, s in enumerate(isl):
        if not s["text"]:
            continue
        parts = split_caption(s["text"], CFG["caption_chars"])
        tot, a = sum(len(p) for p in parts), s["a"]
        for i, p in enumerate(parts):
            b = s["b"] if i == len(parts) - 1 else round(dip(db, hop, a + (s["b"] - s["a"]) * len(p) / max(1, tot)), 3)
            b = max(b, a + 0.2)
            lines.append({"id": f"{k}" + ("abcdefgh"[i] if len(parts) > 1 else ""), "a": round(a, 3), "b": round(min(b, s["b"]), 3),
                          "who": s["who"], "text": p})
            a = lines[-1]["b"]
    json.dump({"name": name, "src": src, "dur": dur, "size": [w, h], "face": face, "islands": isl},
              open(plan_path(name, "words"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = [f"# {name} 전사 (말 덩어리 {len(isl)}개, {dur:.0f}초)", "",
          f"화자 추정: {'소리 크기로 나눔 (PD ' + format(lo, '.0f') + 'dB, 원장님 ' + format(hi, '.0f') + 'dB)' if split else '못 나눔, 전부 dr 로 둠. 글로 보고 pd 를 적는다'}", "",
          "## 덩어리 (시각은 정확, 글은 짧은 덩어리라 틀릴 수 있음)", ""]
    md += [f"- #{k} [{s['a']:.2f} ~ {s['b']:.2f}] {s['who']} {s['db']}dB: {s['text']}" for k, s in enumerate(isl)]
    md += ["", "## 전체 전사 (글은 문맥이 있어 더 정확, 시각은 1초쯤 틀림)", ""]
    md += [f"- [{a:.1f} ~ {b:.1f}] {t}" for a, b, t in full]
    open(os.path.join(wd, f"{name}-transcript.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    pp = plan_path(name)
    if os.path.exists(pp):
        pp = plan_path(name, "edit-draft")
        print("  계획 파일이 이미 있어 초안은 따로 둔다")
    one = lambda l: " " + json.dumps(l, ensure_ascii=False)
    body = ('{\n "name": %s,\n "src": %s,\n "intro": "intro.mp4",\n "outro": "outro.mp4",\n "broll": {},\n "cards": {},\n "lines": [\n%s\n ]\n}\n'
            % (json.dumps(name), json.dumps(src, ensure_ascii=False), ",\n".join(one(l) for l in lines)))
    open(pp, "w", encoding="utf-8").write(body)
    print(f"  얼굴 {face}\n  전사 {os.path.join(wd, name + '-transcript.md')}\n  계획 초안 {pp} ({len(lines)}줄)")


# ───────────────────────── 계획 읽기와 검사 ─────────────────────────

def load(name):
    plan = json.load(open(plan_path(name), encoding="utf-8"))
    use_theme(plan.get("theme"))
    words = json.load(open(plan_path(name, "words"), encoding="utf-8"))
    plan.setdefault("face", words["face"])
    plan["dur"] = words["dur"]
    return plan


def frames(plan):
    """줄마다 프레임 범위와 샷. 가까운 줄(쉼 keep_gap 안)은 쉼을 살려 이어 붙이고, 그 밖은 컷으로 보고 확대 단계를 바꾼다."""
    L, out, chap, cyc, prev = plan["lines"], [], None, 0, None
    for i, l in enumerate(L):
        fa, fb = round(l["a"] * FPS), round(l["b"] * FPS)
        if i + 1 < len(L) and 0 < L[i + 1]["a"] - l["b"] <= CFG["keep_gap"]:
            fb = round(L[i + 1]["a"] * FPS)
        cut = prev is None or prev["fb"] != fa
        if "chapter" in l:
            chap = l["chapter"] or None
        if l.get("broll"):
            shot = "broll"
        elif l.get("shot"):
            shot = l["shot"]
        elif l.get("who") == "pd":
            shot = "wide"
        elif cut or prev["shot"] in ("wide", "broll"):
            cyc += 1
            shot = ("mid", "tight")[cyc % 2] if prev is not None and prev["shot"] != "wide" else "mid"
        else:
            shot = prev["shot"]
        prev = {"i": i, "fa": fa, "fb": max(fb, fa + 2), "cut": cut, "shot": shot, "chapter": chap, "line": l}
        out.append(prev)
    return out


def font(spec, px):
    return ImageFont.truetype(P(spec), max(8, int(round(px))))


def cap_width(text, H):
    c = CFG["caption"]
    return font(c["font"], c["size"] * H).getlength(text)


def check(name, quiet=False):
    plan = load(name)
    errs, warns, L = [], [], plan["lines"]
    if not L:
        errs.append("lines 가 비었다")
    H, W = 1080, 1920
    for i, l in enumerate(L):
        tag = f"줄 {i} ({l.get('id', '?')})"
        if not (0 <= l["a"] < l["b"] <= plan["dur"] + 0.05):
            errs.append(f"{tag}: 시각이 이상하다 {l['a']} ~ {l['b']}")
        t = l.get("text", "")
        if not l.get("nocap"):
            if not t:
                errs.append(f"{tag}: 자막이 비었다 (일부러면 nocap)")
            elif cap_width(t, H) > CFG["caption"]["max_w"] * W:
                errs.append(f"{tag}: 자막이 화면 폭을 넘는다, 줄을 둘로 나눈다: {t}")
            elif l.get("broll") and plan.get("broll", {}).get(l["broll"], {}).get("pip", "br") and cap_width(t, H) > CFG["caption"]["max_w_pip"] * W:
                errs.append(f"{tag}: 자막이 동그란 창과 겹친다, 줄을 둘로 나눈다: {t}")
        for h in l.get("hl", []):
            if h not in t:
                errs.append(f"{tag}: hl '{h}' 가 자막에 없다")
        for k in CFG["corrections"]:
            if k in t:
                errs.append(f"{tag}: 잘못 들은 낱말 '{k}' → '{CFG['corrections'][k]}'")
        for f in CFG["forbidden"]:
            if f in t or f in str(l.get("title", "")):
                warns.append(f"{tag}: 준법 확인 낱말 '{f}': {t}")
        if l.get("broll"):
            b = plan.get("broll", {}).get(l["broll"])
            if not b:
                errs.append(f"{tag}: broll '{l['broll']}' 정의가 없다")
            elif not os.path.exists(asset(b["img"])):
                errs.append(f"{tag}: 자료 그림이 없다 {asset(b['img'])}")
        for c in ([l["card"]] if isinstance(l.get("card"), str) else l.get("card", [])):
            if c not in plan.get("cards", {}):
                errs.append(f"{tag}: card '{c}' 정의가 없다")
    for k, c in plan.get("cards", {}).items():
        for f in CFG["forbidden"]:
            if f in c.get("text", ""):
                warns.append(f"댓글 카드 {k}: 준법 확인 낱말 '{f}'")
    # 질문만 있고 답이 없는 자리
    for i, l in enumerate(L):
        if l.get("who") == "pd" and l.get("text", "").rstrip().endswith("?") and (i + 1 == len(L) or L[i + 1].get("who") == "pd" and L[i + 1]["text"].rstrip().endswith("?") and L[i + 1]["a"] - l["b"] > 1):
            warns.append(f"줄 {i}: 질문 뒤에 답이 없다: {l['text']}")
    for k in ("intro", "outro"):
        if plan.get(k) and not os.path.exists(asset(plan[k])):
            errs.append(f"{k} 범퍼가 없다 {asset(plan[k])}")
    if not os.path.exists(asset(CFG["logo"]["file"])):
        warns.append("로고 파일이 없다, 로고 없이 굽는다")
    F = frames(plan) if L and not errs else []
    body = sum(f["fb"] - f["fa"] for f in F) / FPS
    cuts = sum(1 for f in F if f["cut"])
    if not quiet or errs:
        print(f"  줄 {len(L)}, 컷 {cuts}, 본편 {body:.1f}초 (원본 {plan['dur']:.0f}초의 {100 * body / plan['dur']:.0f}%), "
              f"자료 화면 {sum(1 for f in F if f['shot'] == 'broll')}줄, 챕터 {len({json.dumps(f['chapter'], ensure_ascii=False) for f in F if f['chapter']})}개")
        for w in warns:
            print("  ! " + w)
        for e in errs:
            print("  ✗ " + e)
    if errs:
        raise SystemExit(1)
    return plan, F


def asset(p):
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(P(CFG["kit"]), p)


# ───────────────────────── 그림 (PIL) ─────────────────────────

def rgba(hexs, a=255):
    h = hexs.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def text_layer(runs, fnt, H, glow):
    """runs: [(글, 채움색, 흰 테두리 여부)]. 남색 번짐 위에 글자. 그림과 폭을 돌려준다."""
    pad = int(0.03 * H)
    wds = [fnt.getlength(t) for t, _, _ in runs]
    asc, desc = fnt.getmetrics()
    w, h = int(sum(wds)) + pad * 2, asc + desc + pad * 2
    g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    x = pad
    for (t, _, _), tw in zip(runs, wds):
        d.text((x, pad), t, font=fnt, fill=rgba(glow), stroke_width=max(2, int(0.0032 * H)), stroke_fill=rgba(glow))
        x += tw
    g = g.filter(ImageFilter.GaussianBlur(max(1.0, 0.0028 * H)))
    g = Image.alpha_composite(g, g)
    d = ImageDraw.Draw(g)
    x = pad
    for (t, fill, white), tw in zip(runs, wds):
        if white:
            d.text((x, pad), t, font=fnt, fill=rgba(fill), stroke_width=max(1, int(0.0022 * H)), stroke_fill=(255, 255, 255, 255))
        d.text((x, pad), t, font=fnt, fill=rgba(fill))
        x += tw
    return g


def caption_img(l, H):
    c = CFG["caption"]
    fnt, t = font(c["font"], c["size"] * H), l["text"]
    if l.get("em"):
        runs = [(t, c["em"], False)]
    else:
        spans = sorted((t.find(h), t.find(h) + len(h)) for h in l.get("hl", []) if h in t)
        runs, cur = [], 0
        for a, b in spans:
            if a < cur:
                continue
            if a > cur:
                runs.append((t[cur:a], c["fill"], False))
            runs.append((t[a:b], c["hl"], True))
            cur = b
        if cur < len(t):
            runs.append((t[cur:], c["fill"], False))
    return text_layer(runs, fnt, H, c["glow"])


def chapter_img(ch, H):
    c = CFG["chapter"]
    fn, ft = font(c["num_font"], c["num_size"] * H), font(c["title_font"], c["title_size"] * H)
    sw = max(2, int(0.006 * H))
    n, t = str(ch["n"]), ch["title"]
    wn, wt = fn.getlength(n), ft.getlength(t)
    an, dn = fn.getmetrics()
    im = Image.new("RGBA", (int(wn + wt + 0.05 * H + sw * 4), an + dn + sw * 6), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((sw * 2, sw * 2), n, font=fn, fill=(255, 255, 255, 255), stroke_width=sw, stroke_fill=rgba(c["stroke"]))
    at, _ = ft.getmetrics()
    tx, ty = sw * 2 + wn + 0.018 * H, sw * 2 + an - at - 0.004 * H
    d.text((tx, ty), t, font=ft, fill=rgba(c["stroke"]), stroke_width=max(3, int(0.0065 * H)), stroke_fill=rgba(c["stroke"]))
    d.text((tx, ty), t, font=ft, fill=(255, 255, 255, 255), stroke_width=max(1, int(0.0016 * H)), stroke_fill=(255, 255, 255, 255))
    return im


def card_img(card, H):
    """유튜브 댓글 카드. 글은 실제 댓글 그대로, 이름은 가린다."""
    c = CFG["card"]
    fnt, small = font(c["font"], c["size"] * H), font(c["font"], c["size"] * H * 0.82)
    rows = card["text"].split("\n")
    pad, av, lh = int(0.016 * H), int(0.036 * H), int(c["size"] * H * 1.5)
    tw = max([fnt.getlength(r) for r in rows] + [0.16 * H])
    w, h = int(pad * 3 + av + tw), int(pad * 2 + lh * (len(rows) + 1))
    sh = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((20, 24, 20 + w, 24 + h), fill=(0, 0, 0, 70))
    sh = sh.filter(ImageFilter.GaussianBlur(10))
    d = ImageDraw.Draw(sh)
    d.rectangle((20, 20, 20 + w, 20 + h), fill=(255, 255, 255, 250))
    ax, ay = 20 + pad, 20 + pad
    d.ellipse((ax, ay, ax + av, ay + av), fill=rgba(card.get("color", "#5B9E6B")))
    d.ellipse((ax + av * 0.33, ay + av * 0.2, ax + av * 0.67, ay + av * 0.54), fill=(255, 255, 255, 235))
    d.pieslice((ax + av * 0.18, ay + av * 0.6, ax + av * 0.82, ay + av * 1.3), 180, 360, fill=(255, 255, 255, 235))
    tx = ax + av + pad
    bar = Image.new("RGBA", sh.size, (0, 0, 0, 0))
    ImageDraw.Draw(bar).rounded_rectangle((tx, ay + lh * 0.2, tx + 0.07 * H, ay + lh * 0.72), radius=4, fill=(150, 150, 150, 200))
    sh = Image.alpha_composite(sh, bar.filter(ImageFilter.GaussianBlur(max(2, 0.004 * H))))
    d = ImageDraw.Draw(sh)
    d.text((tx + 0.078 * H, ay + lh * 0.12), card.get("ago", ""), font=small, fill=(110, 110, 110, 255))
    for k, r in enumerate(rows):
        d.text((tx, ay + lh * (k + 1)), r, font=fnt, fill=(20, 20, 20, 255))
    return sh


def pip_geom(W, H, side="br"):
    p = CFG["pip"]
    D = int(p["d"] * H) // 2 * 2
    cx = p["cx"] if side == "br" else p["left_cx"]
    return D, int(cx * W - D / 2), int(p["cy"] * H - D / 2)


def overlay_png(f, plan, W, H, path, layer="base"):
    """layer: base (아래 그늘, 챕터, 로고, 자막), bro (자료 화면 위 점선, 동그란 창 테, 사례 표기), fx (큰 제목, 댓글 카드: 페이드)."""
    l = f["line"]
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    base, bro, fx = layer == "base", layer == "bro", layer == "fx"
    g = CFG["gradient"]
    y0 = int(g["from"] * H)
    ramp = np.zeros((H, W, 4), np.uint8)
    ramp[y0:, :, 3] = (np.linspace(0, 1, H - y0) ** 1.6 * 255 * g["alpha"]).astype(np.uint8)[:, None]
    if base:
        im = Image.alpha_composite(im, Image.fromarray(ramp, "RGBA"))
    if fx and l.get("title"):
        im = Image.alpha_composite(im, Image.new("RGBA", (W, H), (0, 0, 0, int(255 * CFG["title"]["dim"]))))
    d = ImageDraw.Draw(im)
    if bro and f["shot"] == "broll":
        b = plan["broll"][l["broll"]]
        r = max(2, int(0.0045 * H))
        for cx, cy, rx, ry in b.get("dots", []):
            n = int(2 * np.pi * max(rx * W, ry * H) / (r * 5.5))
            for k in range(n):
                a = 2 * np.pi * k / n
                x, y = cx * W + rx * W * np.cos(a), cy * H + ry * H * np.sin(a)
                d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 240))
        if b.get("pip", "br"):
            D, px, py = pip_geom(W, H, b.get("pip", "br"))
            rw = max(3, int(CFG["pip"]["ring"] * H))
            d.ellipse((px - rw // 2, py - rw // 2, px + D + rw // 2, py + D + rw // 2), outline=(255, 255, 255, 255), width=rw)
        if b.get("case"):
            fn = font(CFG["card"]["font"], 0.024 * H)
            t = text_layer([(CFG["case_note"], "#FFFFFF", False)], fn, H, "#000000")
            im.alpha_composite(t, (int(W / 2 - t.width / 2), int(0.815 * H - t.height / 2)))
    cards = ([l["card"]] if isinstance(l.get("card"), str) else l.get("card", [])) if fx else []
    for k, cid in enumerate(cards):
        c = plan["cards"][cid]
        ci = card_img(c, H)
        x, y = c.get("pos", [CFG["card"]["pos"][0], CFG["card"]["pos"][1] - 0.13 * k])
        im.alpha_composite(ci, (int(x * W) - 20, int(y * H) - 20))
    if base and f["chapter"]:
        im.alpha_composite(chapter_img(f["chapter"], H), (int(CFG["chapter"]["x"] * W), int(CFG["chapter"]["y"] * H)))
    lg = CFG["logo"]
    if base and os.path.exists(asset(lg["file"])):
        lo = Image.open(asset(lg["file"])).convert("RGBA")
        lw = int(lg["w"] * W)
        lo = lo.resize((lw, int(lo.height * lw / lo.width)), Image.LANCZOS)
        im.alpha_composite(lo, (int(lg["x"] * W), int(lg["y"] * H)))
    if fx and l.get("title"):
        t = text_layer([(l["title"], "#FFFFFF", False)], font(CFG["title"]["font"], CFG["title"]["size"] * H), H, "#000000")
        im.alpha_composite(t, (int(W / 2 - t.width / 2), int(CFG["title"]["y"] * H - t.height / 2)))
    if base and l.get("text") and not l.get("nocap"):
        t = caption_img(l, H)
        im.alpha_composite(t, (int(W / 2 - t.width / 2), int(CFG["caption"]["y"] * H - t.height / 2)))
    im.save(path)


def fit_image(src, W, H, focus, path):
    im = Image.open(src).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * s + 0.999), int(im.height * s + 0.999)), Image.LANCZOS)
    fx, fy = focus
    x = int(min(max(0, im.width * fx - W / 2), im.width - W))
    y = int(min(max(0, im.height * fy - H / 2), im.height - H))
    im.crop((x, y, x + W, y + H)).save(path, quality=95)


# ───────────────────────── build ─────────────────────────

def enc(o):
    return ["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-b:v", o["bitrate"], "-bf", "0", "-g", "30", "-pix_fmt", "yuv420p",
            "-r", f"{FPS_N}/{FPS_D}", "-video_track_timescale", str(FPS_N), "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-an"]


def crop_for(z, face, sw, sh):
    tx, ty = CFG["face_target"]
    cw, ch = int(sw / z) // 2 * 2, int(sh / z) // 2 * 2
    x = min(max(0, int(face["cx"] * sw - tx * cw)), sw - cw)
    y = min(max(0, int(face["cy"] * sh - ty * ch)), sh - ch)
    return cw, ch, x, y


def build(name, draft=False, only=None, reuse=False):
    plan, F = check(name, quiet=True)
    o = dict(CFG["out"]["draft" if draft else "final"])
    W, H = o["w"], o["h"]
    # 최종 파일 크기 상한 (300MB 를 넘기지 않는다). 길이에서 비트레이트를 계산한다
    total = sum(f["fb"] - f["fa"] for f in F) / FPS + sum(probe(asset(plan[k]))[0] for k in ("intro", "outro") if plan.get(k))
    cap = (CFG["out"]["max_mb"] * 8 * 0.93) / total - 0.26
    if cap < float(o["bitrate"].rstrip("M")):
        o["bitrate"] = f"{cap:.1f}M"
    wd = work(name)
    sd = os.path.join(wd, "seg-draft" if draft else "seg")
    os.makedirs(sd, exist_ok=True)
    if not reuse:
        for f in glob.glob(sd + "/*"):
            os.remove(f)
    src = plan["src"]
    _, sw, sh = probe(src)
    face, grade = plan["face"], CFG["grade"]
    if only:
        F = F[only[0]:only[1]]
    D, _, _ = pip_geom(W, H)
    mask = os.path.join(sd, "mask.png")
    m = Image.new("L", (D * 4, D * 4), 0)
    ImageDraw.Draw(m).ellipse((0, 0, D * 4 - 1, D * 4 - 1), fill=255)
    m.resize((D, D), Image.LANCZOS).save(mask)
    # 같은 자료가 이어지는 줄은 한 번의 느린 밀기로 본다
    runs, k = {}, 0
    while k < len(F):
        if F[k]["shot"] == "broll":
            j = k
            while j + 1 < len(F) and F[j + 1]["shot"] == "broll" and F[j + 1]["line"]["broll"] == F[k]["line"]["broll"]:
                j += 1
            tot, acc = sum(F[q]["fb"] - F[q]["fa"] for q in range(k, j + 1)) / FPS, 0.0
            for q in range(k, j + 1):
                runs[q] = (acc, tot)
                acc += (F[q]["fb"] - F[q]["fa"]) / FPS
            k = j + 1
        else:
            k += 1
    segs = []
    if plan.get("intro") and not only:
        segs.append(("intro", asset(plan["intro"])))
    fxsig = lambda f: json.dumps([f["line"].get("card"), f["line"].get("title")], ensure_ascii=False)
    has_fx = lambda f: bool(f["line"].get("card") or f["line"].get("title"))
    FD, IMG = CFG["fade"], ["-loop", "1", "-framerate", f"{FPS_N}/{FPS_D}"]

    def fades(T, fin, fout):
        d = min(FD, T / 2)
        return (f",fade=t=in:st=0:d={d:.3f}:alpha=1" if fin else "") + (f",fade=t=out:st={T - d:.3f}:d={d:.3f}:alpha=1" if fout else "")

    def doc_chain(shot):
        cw, ch, x, y = crop_for(CFG["shots"][shot], face, sw, sh)
        return f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos,{grade}"

    for q, f in enumerate(F):
        n, ss = f["fb"] - f["fa"], f["fa"] / FPS
        T = n / FPS
        ov, out = os.path.join(sd, f"ov{q:03d}.png"), os.path.join(sd, f"s{q:03d}.mp4")
        if reuse and os.path.exists(out):
            segs.append(("line", out))
            continue
        prev, nxt = (F[q - 1] if q else None), (F[q + 1] if q + 1 < len(F) else None)
        overlay_png(f, plan, W, H, ov, "base")
        ins = ["-ss", f"{ss:.4f}", "-i", src] + IMG + ["-i", ov]
        k = 2
        if f["shot"] == "broll":
            b = plan["broll"][f["line"]["broll"]]
            bg = os.path.join(sd, f"bg-{f['line']['broll']}.jpg")
            if not os.path.exists(bg):
                fit_image(asset(b["img"]), W, H, b.get("focus", [0.5, 0.5]), bg)
            bo = os.path.join(sd, f"bo{q:03d}.png")
            overlay_png(f, plan, W, H, bo, "bro")
            ins += IMG + ["-i", bg] + IMG + ["-i", mask] + IMG + ["-i", bo]
            ibg, imask, ibo, k = 2, 3, 4, 5
            t0, tot = runs[q]
            kz = b.get("push", CFG["broll_push"])
            zoom = (f"scale=w='trunc({W}*(1+{kz}*({t0:.3f}+t)/{tot:.3f})/2)*2':h='trunc({H}*(1+{kz}*({t0:.3f}+t)/{tot:.3f})/2)*2':eval=frame:flags=bicubic,"
                    f"crop={W}:{H}," if kz else "")
            fin = prev is not None and prev["shot"] != "broll"       # 원장님 화면에서 자료로 녹아든다
            fout = nxt is not None and nxt["shot"] != "broll"
            side = b.get("pip", "br")
            need_doc = fin or fout
            fc = f"[0:v]split=2[sa][sb];" if side and need_doc else ("[0:v]null[sa];" if side else "[0:v]null[sb];")
            fc += f"[{ibg}:v]{zoom}setsar=1,format=yuv420p[bg];"
            if side:
                s_ = int(CFG["pip"]["src"] * sh) // 2 * 2
                x = min(max(0, int(face["cx"] * sw - s_ / 2)), sw - s_)
                y = min(max(0, int((face["cy"] + 0.02) * sh - s_ / 2)), sh - s_)
                _, px, py = pip_geom(W, H, side)
                fc += (f"[sa]crop={s_}:{s_}:{x}:{y},scale={D}:{D}:flags=lanczos,{grade},format=rgba[p];[{imask}:v]format=gray[m];"
                       f"[p][m]alphamerge[pc];[bg][pc]overlay={px}:{py}[t0];")
            else:
                fc += "[bg]null[t0];"
            fc += f"[t0][{ibo}:v]overlay=0:0:format=auto[t];"
            if need_doc:
                shot = (nxt["shot"] if fout and not fin else prev["shot"] if fin and not fout else "wide")
                fc += f"[sb]{doc_chain(shot)}[doc];[t]format=yuva420p{fades(T, fin, fout)}[tf];[doc][tf]overlay=0:0:format=auto[v];"
            else:
                fc += "[t]null[v];" + ("" if side else "[sb]nullsink;")
        else:
            fc = f"[0:v]{doc_chain(f['shot'])}[v];"
        fc += "[v][1:v]overlay=0:0:format=auto[v2];"
        if has_fx(f):
            fxp = os.path.join(sd, f"fx{q:03d}.png")
            overlay_png(f, plan, W, H, fxp, "fx")
            ins += IMG + ["-i", fxp]
            fin = prev is None or fxsig(prev) != fxsig(f)
            fout = nxt is None or fxsig(nxt) != fxsig(f)
            fc += f"[{k}:v]format=rgba{fades(T, fin, fout)}[fxf];[v2][fxf]overlay=0:0:format=auto[o]"
        else:
            fc += "[v2]null[o]"
        run(["ffmpeg", "-v", "error", "-y"] + ins + ["-filter_complex", fc, "-map", "[o]", "-frames:v", str(n)] + enc(o) + [out])
        segs.append(("line", out))
        if q % 10 == 9:
            print(f"  {q + 1}/{len(F)} 줄")
    if plan.get("outro") and not only:
        segs.append(("outro", asset(plan["outro"])))
    # 범퍼는 같은 규격으로 다시 굽고 소리는 프레임 수에 맞춘다
    vids, auds = [], []
    for kind, p in segs:
        if kind == "line":
            vids.append(p)
            continue
        d, _, _ = probe(p)
        n = round(d * FPS)
        v, a = os.path.join(sd, f"{kind}.mp4"), os.path.join(sd, f"{kind}.wav")
        run(["ffmpeg", "-v", "error", "-y", "-i", p, "-vf", f"scale={W}:{H}:flags=lanczos,fps={FPS_N}/{FPS_D}", "-frames:v", str(n)] + enc(o) + [v])
        run(["ffmpeg", "-v", "error", "-y", "-i", p, "-vn", "-af", f"aresample=48000,apad,atrim=end={n / FPS:.6f}", "-ac", "2", a])
        vids.append(v)
        auds.append((kind, a))
    # 본편 소리: 이어진 줄은 한 덩어리로, 이음매마다 8ms 페이드
    rr = []
    for f in F:
        if rr and rr[-1][1] == f["fa"]:
            rr[-1][1] = f["fb"]
        else:
            rr.append([f["fa"], f["fb"]])
    parts = []
    for k, (fa, fb) in enumerate(rr):
        dd = (fb - fa) / FPS
        parts.append(f"[0:a]atrim=start={fa / FPS:.6f}:end={fb / FPS:.6f},asetpts=PTS-STARTPTS,afade=t=in:d=0.008,"
                     f"afade=t=out:st={dd - 0.008:.6f}:d=0.008[a{k}]")
    body_raw, body = os.path.join(sd, "body-raw.wav"), os.path.join(sd, "body.wav")
    fs = os.path.join(sd, "audio.txt")
    open(fs, "w").write(";\n".join(parts) + ";\n" + "".join(f"[a{k}]" for k in range(len(rr))) + f"concat=n={len(rr)}:v=0:a=1[o]")
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-/filter_complex", fs, "-map", "[o]", "-ar", "48000", "-ac", "2", body_raw])
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", body_raw, "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    I = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])
    gain = CFG["lufs"] - I
    tot = sum(f["fb"] - f["fa"] for f in F) / FPS
    run(["ffmpeg", "-v", "error", "-y", "-i", body_raw, "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89:level=false,apad,atrim=end={tot:.6f}", body])
    sx = CFG.get("sfx", {})
    if sx.get("file") and plan.get("sfx", True):
        wh = asset(sx["file"])
        if not os.path.exists(wh):
            make_whoosh(wh)
        at, acc, seen = [], 0.0, None
        for q, f in enumerate(F):
            ch = json.dumps(f["chapter"], ensure_ascii=False) if f["chapter"] else None
            ttl = f["line"].get("title")
            if (ch and ch != seen) or (ttl and (q == 0 or F[q - 1]["line"].get("title") != ttl)):
                at.append(acc)
            seen = ch
            acc += (f["fb"] - f["fa"]) / FPS
        if at:
            mixed = os.path.join(sd, "body-sfx.wav")
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", body]
            for _ in at:
                cmd += ["-i", wh]
            fc = "".join(f"[{k + 1}:a]aresample=48000,volume={sx['gain_db']}dB,adelay={int(t * 1000)}:all=1[s{k}];" for k, t in enumerate(at))
            fc += "[0:a]" + "".join(f"[s{k}]" for k in range(len(at))) + f"amix=inputs={len(at) + 1}:normalize=0:duration=first[o]"
            run(cmd + ["-filter_complex", fc, "-map", "[o]", "-ac", "2", mixed])
            body = mixed
            print(f"  전환 효과음 {len(at)}곳: " + ", ".join(f"{t:.1f}초" for t in at))
    order = [a for k, a in auds if k == "intro"] + [body] + [a for k, a in auds if k == "outro"]
    lst = os.path.join(sd, "v.txt")
    open(lst, "w").write("".join(f"file '{v}'\n" for v in vids))
    out = os.path.join(wd, f"{name}{'-draft' if draft else ''}{'-part' if only else ''}.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst]
    for a in order:
        cmd += ["-i", a]
    cmd += ["-filter_complex", "".join(f"[{k + 1}:a]" for k in range(len(order))) + f"concat=n={len(order)}:v=0:a=1[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out]
    run(cmd)
    d, _, _ = probe(out)
    print(f"  본편 음량 {I:.1f} → {CFG['lufs']} LUFS ({gain:+.1f}dB)\n  결과 {out} ({d:.1f}초, {W}x{H})")
    return out


def make_whoosh(path):
    """전환 효과음이 키트에 없을 때 쓰는 임시 소리 (걸러 낸 잡음이 0.5초 부풀었다 꺼진다). 채널이 쓰는 효과음을 받으면 같은 이름으로 바꾼다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.55:c=pink:r=48000:a=0.6", "-af",
         "highpass=f=700,lowpass=f=5200,afade=t=in:d=0.28:curve=qsin,afade=t=out:st=0.28:d=0.27:curve=exp", "-ac", "2", path])


# ───────────────────────── 숏폼 (세로 1080x1920 카드) ─────────────────────────

def short_png(f, sh_def, path):
    S = CFG["shorts"]
    W, H = 1080, 1920
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    t1, t2 = (sh_def["title"] + [""])[:2] if len(sh_def["title"]) > 1 else ("", sh_def["title"][0])
    f1, f2 = font(S["font_light"], S["title1"]["size"]), font(S["font_heavy"], S["title2"]["size"])
    if t1:
        d.text((W / 2 - f1.getlength(t1) / 2, S["title1"]["y"]), t1, font=f1, fill=rgba(S["soft"]))
    acc = sh_def.get("accent", "")
    parts = [(t2, False)] if not acc or acc not in t2 else [(t2[:t2.find(acc)], False), (acc, True), (t2[t2.find(acc) + len(acc):], False)]
    x = W / 2 - f2.getlength(t2) / 2
    for t, a in parts:
        d.text((x, S["title2"]["y"]), t, font=f2, fill=rgba(S["accent"] if a else "#FFFFFF"))
        x += f2.getlength(t)
    l = f["line"]
    fc = font(S["font_bold"], S["caption"]["size"])
    rows = split_caption(l.get("text", ""), S["caption"]["chars"]) if not l.get("nocap") else []
    for k, r in enumerate(rows[:2]):
        col = S["accent"] if l.get("em") else "#FFFFFF"
        d.text((W / 2 - fc.getlength(r) / 2, S["caption"]["y"] + k * S["caption"]["size"] * 1.32), r, font=fc, fill=rgba(col))
    fk = font(S["font_light"], S["credit_size"])
    cr = sh_def.get("credit", S["credit"])
    d.text((W / 2 - fk.getlength(cr) / 2, S["credit_y"]), cr, font=fk, fill=rgba(S["soft"]))
    im.save(path)


def build_short(name, sid=None, draft=False):
    """계획의 shorts 에 적은 편을 굽는다. 줄 범위 [from, to) 는 계획 lines 의 순번. 자료 화면 줄도 원장님 화면으로 간다."""
    plan, F = check(name, quiet=True)
    S = CFG["shorts"]
    defs = [s for s in plan.get("shorts", []) if sid in (None, s["id"])]
    if not defs:
        raise SystemExit("  ✗ 계획에 shorts 가 없다 (또는 그 id 가 없다)")
    src = plan["src"]
    _, sw, sh = probe(src)
    face, grade = plan["face"], CFG["grade"]
    W, H = 1080, 1920
    cx, cy, cw, ch = S["card"]
    for sd_ in defs:
        a, b = sd_["lines"]
        FF = F[a:b]
        sd = os.path.join(work(name), f"short-{sd_['id']}")
        os.makedirs(sd, exist_ok=True)
        for x in glob.glob(sd + "/*"):
            os.remove(x)
        m = Image.new("L", (cw * 2, ch * 2), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, cw * 2 - 1, ch * 2 - 1), radius=S["radius"] * 2, fill=255)
        mask = os.path.join(sd, "mask.png")
        m.resize((cw, ch), Image.LANCZOS).save(mask)
        o = {"bitrate": "3M" if draft else S["bitrate"]}
        vids, cyc, prev = [], 0, None
        for q, f in enumerate(FF):
            n, ss = f["fb"] - f["fa"], f["fa"] / FPS
            if prev is None or prev["fb"] != f["fa"]:
                cyc += 1                                      # 컷마다 확대 단계를 바꾼다
            z = S["zoom"][cyc % len(S["zoom"])]
            hh = int(sh / z) // 2 * 2
            ww = int(hh * cw / ch) // 2 * 2
            x = min(max(0, int(face["cx"] * sw - ww / 2)), sw - ww)
            y = min(max(0, int(face["cy"] * sh - S["face_y"] * hh)), sh - hh)
            ov, out = os.path.join(sd, f"ov{q:03d}.png"), os.path.join(sd, f"s{q:03d}.mp4")
            short_png(f, sd_, ov)
            fc = (f"color=c={S['bg']}:s={W}x{H}:r={FPS_N}/{FPS_D}[bg];[0:v]crop={ww}:{hh}:{x}:{y},scale={cw}:{ch}:flags=lanczos,{grade},format=rgba[v];"
                  f"[1:v]format=gray[m];[v][m]alphamerge[vc];[bg][vc]overlay={cx}:{cy}[t];[t][2:v]overlay=0:0:format=auto[o]")
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.4f}", "-i", src, "-loop", "1", "-i", mask, "-loop", "1", "-i", ov,
                 "-filter_complex", fc, "-map", "[o]", "-frames:v", str(n)] + enc(o) + [out])
            vids.append(out)
            prev = f
        rr = []
        for f in FF:
            if rr and rr[-1][1] == f["fa"]:
                rr[-1][1] = f["fb"]
            else:
                rr.append([f["fa"], f["fb"]])
        parts = [f"[0:a]atrim=start={fa / FPS:.6f}:end={fb / FPS:.6f},asetpts=PTS-STARTPTS,afade=t=in:d=0.008,"
                 f"afade=t=out:st={(fb - fa) / FPS - 0.008:.6f}:d=0.008[a{k}]" for k, (fa, fb) in enumerate(rr)]
        fs, raw, aud = os.path.join(sd, "audio.txt"), os.path.join(sd, "raw.wav"), os.path.join(sd, "a.wav")
        open(fs, "w").write(";\n".join(parts) + ";\n" + "".join(f"[a{k}]" for k in range(len(rr))) + f"concat=n={len(rr)}:v=0:a=1[o]")
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-/filter_complex", fs, "-map", "[o]", "-ar", "48000", "-ac", "2", raw])
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", raw, "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
        gain = CFG["lufs"] - float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])
        tot = sum(f["fb"] - f["fa"] for f in FF) / FPS
        run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89:level=false,apad,atrim=end={tot:.6f}", aud])
        lst = os.path.join(sd, "v.txt")
        open(lst, "w").write("".join(f"file '{v}'\n" for v in vids))
        out = os.path.join(work(name), f"{name}-{sd_['id']}{'-draft' if draft else ''}.mp4")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", aud, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
        print(f"  숏폼 {sd_['id']}: {out} ({tot:.1f}초, {len(FF)}줄)")


def sheet(name, draft=False):
    wd = work(name)
    out = os.path.join(wd, f"{name}{'-draft' if draft else ''}.mp4")
    d, w, h = probe(out)
    qa = os.path.join(wd, "qa")
    os.makedirs(qa, exist_ok=True)
    for f in glob.glob(qa + "/*.jpg"):
        os.remove(f)
    run(["ffmpeg", "-v", "error", "-y", "-i", out, "-vf", "fps=1/2,scale=640:-2", "-q:v", "4", os.path.join(qa, "f_%04d.jpg")])
    fr = sorted(glob.glob(qa + "/f_*.jpg"))
    for k in range(0, len(fr), 9):
        ims = [Image.open(f) for f in fr[k:k + 9]]
        w0, h0 = ims[0].size
        sh = Image.new("RGB", (w0 * 3 + 8, h0 * 3 + 8), (0, 0, 0))
        for i, im in enumerate(ims):
            sh.paste(im, ((i % 3) * (w0 + 4), (i // 3) * (h0 + 4)))
        sh.save(os.path.join(qa, f"sheet_{k // 9 + 1:02d}.jpg"), quality=82)
    for f in fr:
        os.remove(f)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", out, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    I = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1]
    pk = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r.stderr)[-1]
    print(f"  {out}\n  길이 {d:.1f}초, {w}x{h}, 음량 {I} LUFS, 피크 {pk} dBFS\n  장면 모음 {qa}/sheet_*.jpg (한 칸 2초, 9칸 한 장)")


def listen(name, spans=None):
    """자른 조각을 다시 듣는다. 구간을 주면 그 구간만, 안 주면 계획의 모든 줄을 듣고 자막과 다르게 들린 줄을 알린다.
    문장 안에서 자를 때 (말 덩어리 안쪽 시각은 어림값) 앞뒤 낱말이 잘렸는지 여기서 확인한다."""
    import difflib
    wd = work(name)
    wav = os.path.join(wd, "src16k.wav")
    lines = None
    if not spans:
        lines = json.load(open(plan_path(name), encoding="utf-8"))["lines"]
        spans = [(l["a"], l["b"]) for l in lines]
    isl = [{"a": a, "b": b} for a, b in spans]
    whisper_spans(wav, isl, wd)
    bad = 0
    for k, s in enumerate(isl):
        if lines is None:
            print(f"  [{s['a']:.2f} ~ {s['b']:.2f}] {s['text']}")
            continue
        norm = lambda t: re.sub(r"[^0-9A-Za-z가-힣]", "", t)
        r = difflib.SequenceMatcher(None, norm(lines[k].get("text", "")), norm(s["text"])).ratio()
        if r < 0.6:
            bad += 1
            print(f"  ? 줄 {k} ({lines[k].get('id', '?')}) [{s['a']:.2f} ~ {s['b']:.2f}] 자막: {lines[k].get('text', '')} / 들림: {s['text']}")
    if lines is not None:
        print(f"  다시 듣기 {len(isl)}줄, 다르게 들린 줄 {bad} (자막을 일부러 다듬은 줄은 그대로 둔다. 앞뒤 낱말이 잘렸으면 a, b 를 고친다)")


def whisper_spans(wav, isl, wd):
    d = os.path.join(wd, "listen")
    os.makedirs(d, exist_ok=True)
    for f in glob.glob(d + "/*"):
        os.remove(f)
    w = wave.open(wav)
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    pad = np.zeros(int(sr * 0.4), np.int16)
    files = []
    for k, s in enumerate(isl):
        f = os.path.join(d, f"{k:04d}.wav")
        o = wave.open(f, "w")
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr)
        o.writeframes(np.concatenate([pad, x[int(s["a"] * sr):int(s["b"] * sr)], pad]).tobytes())
        o.close()
        files.append(f)
    wc = CFG["whisper"]
    model = model_file()
    for i in range(0, len(files), 40):
        run(["whisper-cli", "-m", model, "-l", wc["lang"], "-t", "8", "-oj", "-np"] + files[i:i + 40])
    for k, s in enumerate(isl):
        try:
            j = json.load(open(files[k] + ".json", encoding="utf-8"))["transcription"]
            s["text"] = fix_text(" ".join(x["text"].strip() for x in j if not x["text"].strip().startswith("[")))
        except Exception:
            s["text"] = ""


def dips(name, a, b):
    """[a, b] 안에서 소리가 꺼지는 자리 (자를 수 있는 틈) 를 깊은 순으로."""
    db, hop = envelope(os.path.join(work(name), "src16k.wav"))
    i0, i1 = int(a / hop), int(b / hop)
    seg = db[i0:i1]
    out = []
    for i in range(3, len(seg) - 3):
        if seg[i] == seg[max(0, i - 8):i + 9].min():
            out.append((float(seg[i]), (i0 + i) * hop))
    for v, t in sorted(out)[:12]:
        print(f"  {t:.2f}초 {v:.0f}dB")


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if len(a) >= 2 and a[0] == "listen":
        nums = [float(x) for x in a[2:]]
        return listen(a[1], list(zip(nums[0::2], nums[1::2])) or None)
    if len(a) >= 2 and a[0] == "shorts":
        return build_short(a[1], a[2] if len(a) > 2 else None, "--draft" in sys.argv)
    if len(a) >= 4 and a[0] == "dips":
        return dips(a[1], float(a[2]), float(a[3]))
    draft = "--draft" in sys.argv
    only = None
    if "--only" in sys.argv:
        s = sys.argv[sys.argv.index("--only") + 1]
        a.remove(s)
        only = tuple(int(x) for x in s.split(":"))
    if len(a) >= 3 and a[0] == "prep":
        prep(a[1], a[2])
    elif len(a) >= 2 and a[0] == "check":
        check(a[1])
    elif len(a) >= 2 and a[0] == "build":
        build(a[1], draft, only, "--reuse" in sys.argv)
    elif len(a) >= 2 and a[0] == "sheet":
        sheet(a[1], draft)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
