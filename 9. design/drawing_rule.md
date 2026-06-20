# drawing_rule.md — 보고서용 다이어그램 작도 규칙 (SSOT)

> 보고서·문서에 넣는 **흐름도·구조 다이어그램**을 만들 때 **반드시** 이 문서를 먼저 읽고 그대로 따른다.
> 기준 산출물(정본): `9. design/report/stage1/step1_collect.html`, `step4_serve.html`, 루트 `pipeline_overview.html`.
> **임의로 다른 양식(회색 배경, 가로로 넓은 캔버스, 외부 폰트, 손코딩 좌표 등)을 쓰지 말 것.**

---

## 0. 핵심 4원칙 (어겼다가 여러 번 다시 만들었음 — 절대 위반 금지)

1. **흰 배경.** `--paper:#ffffff`. 회색(`#f5f5f5` 등) 금지. 흰 문서에 그대로 삽입할 그림이다.
2. **문서용 — 가로로 좁게.** `.wrap{max-width:720px}`(필요 시 760px). SVG는 `width:100%`로 반응형. 가로로 넓은 캔버스(1000px+) 금지.
3. **편집이 쉬운 HTML 구성.** 노드·라벨·화살표를 **상단 데이터 영역**(`META`/`COLS`/`EDGES`/`LABELS`)에 분리하고, 좌표·SVG는 아래 렌더링 엔진이 자동 계산. 사용자가 **데이터만 고치면** 그림이 바뀌게 한다. 손으로 좌표를 박아 넣지 않는다.
4. **시스템 폰트만.** `'Malgun Gothic','맑은 고딕',sans-serif`. 외부 폰트(Google Fonts 등) 로드 금지.

---

## 1. 독자 / 표현 (보고서 시각자료 공통)

- 예상 독자 = **어려운 IT/서버 용어를 모르는 관심 있는 직장인.** 쉽게, 정보량 줄여서, "무엇을·왜"부터.
- **원본 파일명·기술 식별자 노출 금지** → 역할로 풀어쓴다. 예: `collect_data_land_new.py` → "전국 데이터 수집기", `est_horizon_land` → "예측 결과 테이블".
- 어려운 한자·일본어식 조어 금지. 자연스러운 한국어만.
- 기술 약어가 꼭 필요하면(예: `D+1~15`) 작은 글씨로 보조 표기.

---

## 2. 저장 위치

- `9. design/report/stageN/` 에 단계별 폴더를 만들어 저장(예: 5단계 → `9. design/report/stage5/`).
- 각 그림: `이름.html`(원본) + `이름.png`(검수 렌더) + 폴더에 `_render.py`(렌더 도우미) 1개.

---

## 3. 불변 스타일 토큰 (색·타이포)

```
--paper  #ffffff   배경·박스 마스크
--ink    #2d3142   기본 선/제목 텍스트(박스 테두리 model 타입)
--muted  #4f5d75   화살표·보조 텍스트·data/store 테두리
--soft   #7a8399   더 옅은 보조(서브라벨·열 제목)
--accent #eb6c36   강조(주황) — 그림당 1~2곳만(핵심 1개)
--rule   rgba(45,49,66,0.12)   범례 구분선
TEXT     #1a1a1a   모든 본문 글자색
accentTint rgba(235,108,54,0.08~0.10)   강조 박스 채움
store    rgba(45,49,66,0.05)            데이터/저장 박스 채움
ext      rgba(45,49,66,0.03) / 테두리 rgba(45,49,66,0.32)  외부 기관 박스
```

타이포(헤더는 HTML, 그림 안은 SVG `<text>`):
- eyebrow: 8px, 700, `letter-spacing:0.18em`, 대문자, **accent 색**
- h1: 1.6rem, 700
- sub(부제): 12.5px, line-height 1.5
- note(각주, 선택): 11px, muted — 예: `* 제주도 동일한 구조로 동작합니다.`
- footer: 8px, 대문자, tracked — 예: `… · 2026-06`
- 박스 제목: SVG 12.5~13px, 700 / 서브라벨: 10px, 400, muted

**노드 타입 → 스타일**
| 타입 | 채움 | 테두리 | 용도 |
|---|---|---|---|
| `focal` | accentTint | accent | 핵심(1~2개만) |
| `model` | #ffffff | ink | 처리 단계·모델·서비스 |
| `data`/`store` | store | muted | 입력 데이터·저장 |
| `external` | ext | extStroke(점선 느낌) | 외부 기관 |

---

## 4. SVG 작도 규칙

- 화살표를 **박스보다 먼저** 그린다(z-order: 선이 박스 뒤로).
- 화살표 라벨은 **뒤에 흰 마스크 사각형**을 깔아 선이 비치지 않게. ≤ 짧게.
- 박스 = 흰 마스크 rect + 스타일 rect 2겹, `rx=6`.
- 범례는 **그림 안이 아니라 하단**에 가로 띠 + 위에 얇은 구분선.
- `viewBox`는 내용에 맞춰 자동 계산. 폭 ~720.

---

## 5. 작업 절차 (렌더 → 눈으로 검수 루프)

1. 기준 템플릿(`stage1/step1_collect.html`) 복사 → 데이터 영역만 교체.
2. `python _render.py 이름.html` → 같은 폴더에 PNG 생성(playwright+chromium, 설치돼 있음).
3. **PNG를 Read로 직접 열어** 겹침·잘림·여백·강조 위치 확인.
4. 문제 있으면 데이터/좌표 수정 후 재렌더. 깔끔할 때까지 반복.

`_render.py`(폴더마다 1개, 재사용):
```python
# -*- coding: utf-8 -*-
import sys, os
from playwright.sync_api import sync_playwright
path = os.path.abspath(sys.argv[1]); out = os.path.splitext(path)[0] + '.png'
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width':1000,'height':720}, device_scale_factor=2)
    pg.goto('file:///' + path.replace('\\', '/')); pg.wait_for_timeout(1200)
    el = pg.query_selector('.wrap'); (el or pg).screenshot(path=out); b.close()
print(out)
```

---

## 6. 재사용 템플릿 (자동배치형 — 단순 열 흐름)

`COLS`(열←왼→오, 각 열 박스↑→↓)와 `EDGES`만 채우면 좌표·화살표·범례 자동. 복잡한 커스텀 배치는 `step4_serve.html`처럼 `LABELS` + 직접 build() 방식을 참고.

```html
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>단계 · 제목</title>
<!-- 시스템 폰트(맑은 고딕) · 흰 배경 — 흰 문서 삽입용 -->
<style>
  :root{ --paper:#ffffff; --ink:#2d3142; --muted:#4f5d75; --soft:#7a8399;
         --accent:#eb6c36; --rule:rgba(45,49,66,0.12); }
  *{box-sizing:border-box}
  body{ margin:0; background:var(--paper); color:#1a1a1a;
        font-family:'Malgun Gothic','맑은 고딕',sans-serif;
        display:flex; justify-content:center; padding:2rem 1rem; }
  .wrap{width:100%; max-width:720px}
  .eyebrow{font-size:8px; font-weight:700; letter-spacing:0.18em; text-transform:uppercase;
           color:var(--accent); margin:0 0 0.4rem;}
  h1{font-weight:700; font-size:1.6rem; margin:0 0 0.3rem; line-height:1.1;}
  .sub{font-size:12.5px; color:#1a1a1a; margin:0 0 1rem; line-height:1.5;}
  svg{width:100%; height:auto; display:block}
  .note{font-size:11px; color:var(--muted); margin:0.6rem 0 0; line-height:1.4;}
  footer{margin-top:1rem; padding-top:0.6rem; border-top:1px solid var(--rule);
         font-size:8px; letter-spacing:0.12em; color:#1a1a1a; text-transform:uppercase;}
</style>
</head>
<body>
<div class="wrap">
  <p class="eyebrow" id="eyebrow"></p>
  <h1 id="title"></h1>
  <p class="sub" id="subtitle"></p>
  <svg id="diagram" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="흐름도"></svg>
  <p class="note" id="note"></p>
  <footer id="footer"></footer>
</div>

<!-- ====================================================================== -->
<!--  ▼▼▼  여기만 고치면 됩니다 — 좌표·화살표는 자동 계산됩니다  ▼▼▼          -->
<!-- ====================================================================== -->
<script>
  const META = {
    eyebrow:  "STEP n · 제목",
    title:    "제목",
    subtitle: "한 문장 설명(무엇을·왜).",
    note:     "",   // 각주 없으면 빈 문자열
    footer:   "… · 2026-06",
  };

  // 열(왼→오) · 각 열의 박스(위→아래). type: external | focal | data | model | store
  const COLS = [
    { head:"열 제목", boxes:[
        { id:"a", n:"노드명", sub:["보조설명1","보조설명2"], type:"external" },
    ]},
    { head:"열 제목", boxes:[
        { id:"b", n:"핵심 노드", sub:["설명"], type:"focal" },
    ]},
    { head:"열 제목", boxes:[
        { id:"c", n:"결과", sub:["설명"], type:"data" },
    ]},
  ];

  // 화살표: [출발 id, 도착 id, 라벨(생략 가능)]
  const EDGES = [ ["a","b"], ["b","c","라벨"] ];

  const LEGEND = [
    { type:"external", label:"외부 기관" },
    { type:"focal",    label:"핵심" },
    { type:"data",     label:"데이터" },
  ];
  // ====================================================================== //
  // ▲▲▲  보통은 여기까지만 수정하면 됩니다  ▲▲▲                              //
  // ====================================================================== //

  const T = { paper:'#ffffff', ink:'#2d3142', muted:'#4f5d75', soft:'#7a8399',
              accent:'#eb6c36', accentTint:'rgba(235,108,54,0.08)',
              rule:'rgba(45,49,66,0.12)', store:'rgba(45,49,66,0.05)',
              ext:'rgba(45,49,66,0.03)', extStroke:'rgba(45,49,66,0.32)' };
  const FONT = "'Malgun Gothic','맑은 고딕',sans-serif";
  const TEXT = '#1a1a1a';
  const STYLE = {
    focal:{fill:T.accentTint,stroke:T.accent}, data:{fill:T.store,stroke:T.muted},
    external:{fill:T.ext,stroke:T.extStroke}, store:{fill:T.store,stroke:T.muted},
    model:{fill:'#ffffff',stroke:T.ink},
  };
  const CFG = { nodeW:184, colGapX:64, padX:24, padTop:78, vGap:22, footPad:44 };
  const esc=(s)=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
  const t=(x,y,s,{size=12,col=TEXT,w=600,anc='middle',ls=0}={})=>
    `<text x="${x}" y="${y}" fill="${col}" font-size="${size}" font-weight="${w}" `+
    `font-family="${FONT}" text-anchor="${anc}" letter-spacing="${ls}em">${esc(s)}</text>`;
  function boxH(b){ return 40 + (b.sub||[]).length*14; }
  function build(){
    const { nodeW,colGapX,padX,padTop,vGap,footPad } = CFG;
    const colH = COLS.map(c=>c.boxes.reduce((s,b)=>s+boxH(b),0)+(c.boxes.length-1)*vGap);
    const maxColH = Math.max(...colH);
    const vbW = padX*2 + COLS.length*nodeW + (COLS.length-1)*colGapX;
    const legendY = padTop + maxColH + 30, vbH = legendY + footPad;
    const pos={};
    COLS.forEach((c,ci)=>{ const x=padX+ci*(nodeW+colGapX); let y=padTop+(maxColH-colH[ci])/2;
      c._headY=y-14; c._headX=x+nodeW/2;
      c.boxes.forEach(b=>{ const h=boxH(b); pos[b.id]={x,y,w:nodeW,h,cx:x+nodeW/2,cy:y+h/2,left:x,right:x+nodeW}; y+=h+vGap; }); });
    let arrows='',labels='',boxes='',heads='';
    EDGES.forEach(([f,to,lab])=>{ const a=pos[f],b=pos[to]; if(!a||!b)return;
      const x1=a.right,y1=a.cy,x2=b.left-4,y2=b.cy;
      arrows+=`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${T.muted}" stroke-width="1" marker-end="url(#arrow)"/>`;
      if(lab){ const mx=(x1+x2)/2,my=(y1+y2)/2,w=lab.length*9+10;  // 라벨은 선 위로(짧은 화살표서도 안 가리게)
        labels+=`<rect x="${mx-w/2}" y="${my-19}" width="${w}" height="14" rx="2" fill="${T.paper}"/>`+t(mx,my-8,lab,{size:8.5,col:T.muted,w:600,ls:0.04}); } });
    COLS.forEach(c=>{ heads+=t(c._headX,c._headY,c.head,{size:8.5,col:T.soft,w:600,ls:0.12}); });
    COLS.forEach(c=>c.boxes.forEach(b=>{ const p=pos[b.id],s=STYLE[b.type]||STYLE.model,hasSub=(b.sub||[]).length>0;
      boxes+=`<rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="6" fill="${T.paper}"/>`+
             `<rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="6" fill="${s.fill}" stroke="${s.stroke}" stroke-width="1"/>`;
      boxes+=t(p.cx, hasSub?p.y+22:p.cy+4, b.n, {size:12.5,col:TEXT,w:700});
      (b.sub||[]).forEach((ln,i)=>{ boxes+=t(p.cx,p.y+38+i*14,ln,{size:10,col:T.muted,w:400}); }); }));
    let legend=`<line x1="${padX}" y1="${legendY}" x2="${vbW-padX}" y2="${legendY}" stroke="${T.rule}" stroke-width="0.8"/>`;
    let lx=padX,ly=legendY+10;
    LEGEND.forEach(it=>{ const s=STYLE[it.type]||STYLE.model;
      legend+=`<rect x="${lx}" y="${ly}" width="12" height="12" rx="2" fill="${s.fill}" stroke="${s.stroke}" stroke-width="1"/>`+
              t(lx+16,ly+10,it.label,{size:8.5,col:TEXT,w:500,anc:'start',ls:0.03}); lx+=it.label.length*13+40; });
    const svg=document.getElementById('diagram'); svg.setAttribute('viewBox',`0 0 ${vbW} ${vbH}`);
    svg.innerHTML=`<defs><marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="${T.muted}"/></marker></defs>`+
      `<rect width="100%" height="100%" fill="${T.paper}"/>`+arrows+labels+heads+boxes+legend;
    for(const k of ['eyebrow','title','subtitle','note','footer']) document.getElementById(k).textContent=META[k]||'';
  }
  build();
</script>
</body>
</html>
```

> 강조색(주황)이 2곳을 넘으면 핵심이 흐려진다. 박스를 줄일 수 있으면 줄인다(개요는 단순하게, 상세는 따로).

---

## 7. matplotlib 차트 — 글자 겹침 빠른 수정 (자주 생김)

**전제 규칙(2026-06-20 추가):** matplotlib 차트를 그릴 때는 ① **반드시 `/matplotlib-render-review` 스킬**(렌더 → PNG를 Read로 검수 → 수정 루프)을 쓴다. ② **plot용 .py는 사용자가 직접 고치기 쉽게** — 바꿀 값(데이터·라벨·색·제목·축·범례)을 **파일 상단에 변수로 모으고** 한국어 주석으로 표시. ③ **글자와 그래프(선·점·막대·축)는 절대 겹치지 않게** 한다(아래 표로 수정).

차트는 각각 `_*.py` 스크립트가 만든다. **스크립트를 열어 아래 값만 고치고 다시 실행하면(`python 스크립트.py`) PNG가 그 자리에서 갱신된다.** (한 스크립트가 여러 PNG를 만들기도 함.)

| 겹침 증상 | 고칠 곳 |
|---|---|
| **제목 ↔ 부제 겹침** | `set_title(..., pad=30)` 키우고 `fig.subplots_adjust(top=0.82)` 낮춤 |
| **화살표 주석 글자가 선/다른 글자에 겹침** | `ax.annotate(..., xytext=(x, y))`의 (x,y)를 **빈 공간**으로. 좌표는 데이터 단위(축 눈금과 같은 값). `xy=`는 화살표가 가리키는 점이라 그대로 둠 |
| **일반 글자 겹침** | `ax.text(x, y, ...)`의 x,y 이동 |
| **범례가 선/글자 위에** | `ax.legend(loc=...)` 위치 바꿈('upper right'·'lower right'·'upper left'·'lower left') 또는 `bbox_to_anchor=(x,y)` |
| **글자 크기** | `fontsize=` 조정 |

- **빈 공간 좌표 읽는 법**: 그래프 축 눈금을 보고, 글자를 놓고 싶은 빈 칸의 가로값(x)·세로값(y)을 그대로 `xytext`/`text`에 넣는다.
- **주의 — 두 좌표계**: 대부분 글자는 데이터 좌표. 단 `transform=ax.transAxes`가 붙은 글자(보통 부제)는 **비율 좌표**(좌하단 0,0 ~ 우상단 1,1)다. 부제 위치는 보통 `(0, 1.03)`.
- **화살표 라벨/주석은 선 위로 살짝 띄우기**(겹침 예방). HTML 자동배치 엔진도 이 규칙 적용됨(§6 라벨 `my-19`).
