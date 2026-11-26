# 안내서 가독성 패스: 원본 화면 캡처(assets/sNN-*.png)는 그대로 두고, 읽어야 할 부분만 잘라 새 파일로 만든다.
# 가로로 잘라 붙인 곳(hcat)·위아래로 이어 붙인 곳(stack)은 캡션에 "잘라 붙임"으로 밝힌다. 글자·수치는 바꾸지 않는다.
import pathlib
from PIL import Image, ImageDraw
A = pathlib.Path(r"D:/04_ByOrbit/10_rnd_AI_byrobit/guidebook/assets")
_c = {}
def src(n):
    if n not in _c: _c[n] = Image.open(A / n).convert("RGB")
    return _c[n]
def R(n, x0, y0, x1, y1): return src(n).crop((x0, y0, x1, y1))
def stack(parts, gap=18):
    W = max(p.width for p in parts); H = sum(p.height for p in parts) + gap * (len(parts) - 1)
    out = Image.new("RGB", (W, H), (255, 255, 255)); y = 0; d = ImageDraw.Draw(out)
    for i, p in enumerate(parts):
        out.paste(p, (0, y)); y += p.height
        if i < len(parts) - 1:
            d.line([(0, y + gap // 2), (W, y + gap // 2)], fill=(200, 200, 200), width=3, ); y += gap
    return out
def hcat(parts, gap=22):
    H = max(p.height for p in parts); W = sum(p.width for p in parts) + gap * (len(parts) - 1)
    out = Image.new("RGB", (W, H), (255, 255, 255)); x = 0; d = ImageDraw.Draw(out)
    for i, p in enumerate(parts):
        out.paste(p, (x, 0)); x += p.width
        if i < len(parts) - 1:
            d.line([(x + gap // 2, 0), (x + gap // 2, H)], fill=(200, 200, 200), width=3); x += gap
    return out
S = {
 "s24a-start-menu.png": lambda: stack([R("s24-start.png", 0, 0, 750, 95), R("s24-start.png", 750, 0, 1680, 95), R("s24-start.png", 215, 120, 1255, 355)]),
 "s01a-library-ailabel.png": lambda: R("s01-library.png", 215, 395, 1300, 545),
 "s01b-library-list.png": lambda: R("s01-library.png", 230, 600, 1480, 1300),
 "s02a-search-chips.png": lambda: stack([R("s02-search.png", 225, 140, 1225, 270), R("s02-search.png", 1190, 200, 2050, 270), R("s02-search.png", 210, 320, 1150, 680)]),
 "s02b-search-chunk.png": lambda: R("s02-search.png", 1170, 320, 2190, 690),
 "s03a-review-list.png": lambda: R("s03-review.png", 1280, 260, 2160, 1070),
 "s03b-review-keys.png": lambda: R("s03-review.png", 1890, 1100, 2380, 1600),
 "s04a-measurements.png": lambda: hcat([R("s04-measurements.png", 240, 250, 1070, 700), R("s04-measurements.png", 1520, 250, 1670, 700)]),
 "s05a-concepts-synonyms.png": lambda: R("s05-concepts.png", 1220, 150, 2180, 950),
 "s05b-concepts-tree.png": lambda: R("s05-concepts.png", 230, 150, 820, 1000),
 "s06a-ask.png": lambda: R("s06-ask.png", 215, 255, 1300, 520),
 "s07a-settings-engine.png": lambda: R("s07-settings.png", 215, 140, 1185, 540),
 "s07b-settings-coa.png": lambda: R("s07-settings.png", 1220, 140, 2190, 500),
 "s08a-collect-sources.png": lambda: R("s08-collect.png", 50, 340, 1200, 1190),
 "s09a-inbox-cards.png": lambda: R("s09-collect-inbox.png", 60, 180, 1260, 1150),
 "s09b-inbox-saved.png": lambda: R("s09-collect-inbox.png", 1500, 0, 2330, 600),
 "s10a-exp-flow.png": lambda: stack([R("s10-exp-flow.png", 20, 190, 1190, 470), R("s10-exp-flow.png", 1190, 190, 2400, 470)]),
 "s11a-exp-data.png": lambda: stack([R("s11-exp-data.png", 30, 220, 1270, 610), hcat([R("s11-exp-data.png", 30, 220, 215, 610), R("s11-exp-data.png", 1285, 220, 2310, 610)])]),
 "s12a-exp-error.png": lambda: R("s12-exp-result.png", 20, 190, 1100, 500),
 "s12b-exp-parity.png": lambda: R("s12-exp-result.png", 20, 560, 1185, 1400),
 "s12c-exp-calib.png": lambda: stack([R("s12-exp-result.png", 20, 1460, 1250, 1610), hcat([R("s12-exp-result.png", 20, 1620, 450, 2200), R("s12-exp-result.png", 1150, 1620, 1450, 2200), R("s12-exp-result.png", 1700, 1620, 2200, 2200)])]),
 "s13a-stats-setup.png": lambda: stack([R("s13-stats-setup.png", 40, 0, 1250, 260), R("s13-stats-setup.png", 40, 1170, 1000, 1500), R("s13-stats-setup.png", 960, 1170, 1880, 1290), R("s13-stats-setup.png", 1860, 1170, 2350, 1290)]),
 "s14a-stats-head.png": lambda: R("s14-stats-result.png", 40, 0, 1250, 330),
 "s14b-stats-checks.png": lambda: stack([R("s14-stats-result.png", 40, 1580, 1185, 2060), R("s14-stats-result.png", 1185, 1580, 2350, 2060)]),
 "s15a-viz-flow.png": lambda: R("s15-viz-flow.png", 1010, 170, 2290, 1000),
 "s16a-viz-dryer.png": lambda: R("s16-viz-drying-3d.png", 180, 280, 1400, 1400),
 "s17a-viz-predict.png": lambda: R("s17-viz-predict.png", 760, 380, 1530, 940),
 "s17b-viz-evidence.png": lambda: R("s17-viz-predict.png", 760, 1360, 1530, 2170),
 "s18a-viz-molecule.png": lambda: R("s18-viz-molecule.png", 40, 30, 1200, 980),
 "s19a-wb-tools.png": lambda: R("s19-wb-parse.png", 40, 160, 1210, 680),
 "s19b-wb-upstage.png": lambda: R("s19-wb-parse.png", 620, 670, 1180, 1330),
 "s19c-wb-compare.png": lambda: stack([R("s19-wb-parse.png", 40, 1700, 1185, 1960), R("s19-wb-parse.png", 1185, 1700, 2330, 1960)]),
 "s20a-wb-chunklist.png": lambda: R("s20-wb-chunks.png", 20, 200, 840, 1120),
 "s20b-wb-buttons.png": lambda: stack([R("s20-wb-chunks.png", 870, 1070, 1640, 1250), R("s20-wb-chunks.png", 1640, 1070, 2140, 1130)]),
 "s21a-wb-labelpopup.png": lambda: R("s21-wb-labels.png", 30, 470, 1290, 1480),
 "s22a-wb-learned.png": lambda: R("s22-wb-learned.png", 30, 280, 1250, 1000),
 "s23a-install.png": lambda: R("s23-install.png", 0, 0, 1300, 1031),
}
if __name__ == "__main__":
    for n, f in S.items():
        im = f(); im.save(A / n); print(n, im.size)
