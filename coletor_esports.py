#!/usr/bin/env python3
"""
Coletor E-SPORTS — SpamiReza (Clã 5 · e-SpamiReza)
Puxa a guerra ATUAL do clã (amistoso agendado ou guerra do campeonato) via API
oficial do CoC (proxy RoyaleAPI) e gera:
  - esports_data.json : snapshot da guerra atual + histórico completo guerra-a-guerra
  - injeta no index.html o objeto DATA com: guerra atual (vs/tam/state/timer/esc/res),
    placar do campeonato (guerras/vitórias/derrotas/empates) e RANKING acumulado
    (Índice, MVP) de todas as guerras já registradas.

Diferença do coletor_cwl.py: aqui NÃO existe leaguegroup/rodadas fixas. Cada guerra
é um evento avulso (amistoso ou guerra de campeonato) pego em /clans/{tag}/currentwar.
Como esse endpoint só expõe a guerra ATUAL (some quando acaba/rotaciona), toda guerra
vista precisa ser arquivada em historico_esports.json ANTES que a próxima a substitua
— por isso o coletor faz upsert por "war id" (adversário+início) a cada rodada de 10min.

Modelo do Índice: igual ao das ligas — 55% ataque + 20% defesa + 25% confiabilidade.
Token CoC: env COC_TOKEN  ou  ../COC - Coach/api/.token
Uso: python3 coletor_esports.py
"""
import os, sys, json, urllib.request, urllib.parse, pathlib, hashlib, datetime

PROXY = "https://cocproxy.royaleapi.dev/v1"
TAG = "#2CPQQQ008"
NOME = "e-SpamiReza"
ROOT = pathlib.Path(__file__).resolve().parent
PESO_ATK, PESO_DEF, PESO_CONF = 0.55, 0.20, 0.25

def token():
    if os.environ.get("COC_TOKEN"): return os.environ["COC_TOKEN"].strip()
    cands = [ROOT / ".token", ROOT / "COC_TOKEN.txt"]
    p = ROOT
    for _ in range(6):
        cands.append(p / "COC - Coach" / "api" / ".token")
        p = p.parent
    for c in cands:
        if c.exists(): return c.read_text().strip()
    sys.exit("Token CoC não encontrado (defina COC_TOKEN ou tenha 'COC - Coach/api/.token' perto do projeto)")

TOK = token()
def get(path):
    req = urllib.request.Request(f"{PROXY}{path}", headers={
        "Authorization": f"Bearer {TOK}", "Accept": "application/json", "User-Agent": "spamireza-esports/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r: return r.status, json.load(r)
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)

def war_id(w):
    """ID estável pra uma guerra avulsa: adversário + horário de início (ou preparação)."""
    base = f"{(w.get('opponent') or {}).get('tag')}|{w.get('startTime') or w.get('preparationStartTime')}"
    return hashlib.sha1(base.encode()).hexdigest()[:12]

def coletar():
    q = urllib.parse.quote(TAG)
    out = {"tag": TAG, "nome": NOME, "elenco": [], "atual": None, "erro": None}
    sc, ci = get(f"/clans/{q}")
    if isinstance(ci, dict):
        out["elenco"] = [{"nome": m.get("name"), "tag": m.get("tag"), "th": m.get("townHallLevel")}
                          for m in ci.get("memberList", [])]
    st, w = get(f"/clans/{q}/currentwar")
    if st != 200 or not isinstance(w, dict) or w.get("state") in (None, "notInWar"):
        out["erro"] = f"currentwar status {st} / state={w.get('state') if isinstance(w, dict) else w}"
        return out
    c, o = w.get("clan") or {}, w.get("opponent") or {}
    if TAG not in (c.get("tag"), o.get("tag")):
        out["erro"] = "guerra não é do clã 5"
        return out
    eu, adv = (c, o) if c.get("tag") == TAG else (o, c)
    membros = []
    for m in eu.get("members", []):
        atks = m.get("attacks") or []
        bo = m.get("bestOpponentAttack") or {}
        membros.append({
            "nome": m.get("name"), "tag": m.get("tag"), "th": m.get("townhallLevel"),
            "pos": m.get("mapPosition"),
            "ataques": [{"estrelas": a.get("stars"), "destr": a.get("destructionPercentage")} for a in atks],
            "def_estrelas": bo.get("stars"), "def_destr": bo.get("destructionPercentage")})
    membros.sort(key=lambda x: x.get("pos") or 99)
    resultado = None
    if w.get("state") == "warEnded":
        es, os_ = eu.get("stars", 0), adv.get("stars", 0)
        ed, od = eu.get("destructionPercentage", 0), adv.get("destructionPercentage", 0)
        resultado = "v" if (es, ed) > (os_, od) else ("d" if (es, ed) < (os_, od) else "e")
    atual = {
        "id": war_id(w), "state": w.get("state"), "teamSize": w.get("teamSize"),
        "adversario": adv.get("name"), "prep": w.get("preparationStartTime"),
        "inicio": w.get("startTime"), "fim": w.get("endTime"),
        "membros": membros, "resultado": resultado,
    }
    out["atual"] = atual
    return out

def salvar_historico(out):
    """Upsert da guerra atual no histórico (por war id). Nunca perde uma guerra
    já registrada mesmo quando a API zera/rotaciona pra próxima. Blindado: só
    sobrescreve uma entrada existente se o novo snapshot tiver >= ataques."""
    hd = ROOT / "historico"; hd.mkdir(exist_ok=True)
    fp = hd / "guerras.json"
    try:
        hist = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        hist = {"guerras": {}}
    a = out.get("atual")
    if a:
        atk_novo = sum(len(m["ataques"]) for m in a["membros"])
        ant = hist["guerras"].get(a["id"])
        atk_ant = sum(len(m["ataques"]) for m in ant["membros"]) if ant else -1
        if ant is None or atk_novo >= atk_ant:
            hist["guerras"][a["id"]] = a
    fp.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    return hist

def agregar(hist, elenco):
    """Ranking acumulado de TODAS as guerras já registradas (inWar/warEnded).
    Confiabilidade = ataques feitos / guerras em que foi escalado."""
    agg = {}
    guerras_contadas, v, e, d = 0, 0, 0, 0
    for g in hist["guerras"].values():
        if g.get("state") not in ("inWar", "warEnded"):
            continue
        guerras_contadas += 1
        if g.get("resultado") == "v": v += 1
        elif g.get("resultado") == "d": d += 1
        elif g.get("resultado") == "e": e += 1
        for m in g["membros"]:
            a = agg.setdefault(m["tag"], {"nome": m["nome"], "th": m["th"], "rounds": 0, "atk": 0,
                                          "est": 0, "defsof": 0, "defcnt": 0, "defneg": 0})
            a["nome"], a["th"] = m["nome"], m["th"]; a["rounds"] += 1
            for at in m["ataques"]:
                a["atk"] += 1; a["est"] += at["estrelas"] or 0
            ds = m.get("def_estrelas")
            if ds is not None:
                a["defsof"] += ds; a["defcnt"] += 1; a["defneg"] += (3 - ds)
    rank = []
    for a in agg.values():
        atk = a["atk"]; spa = a["est"] / atk if atk else 0
        notaAtk = spa / 3 * 100
        conf = min(1, atk / a["rounds"]) if a["rounds"] else 0
        comps = [(PESO_ATK, notaAtk), (PESO_CONF, conf * 100)]
        notaDef = None
        if a["defcnt"] > 0:
            notaDef = (1 - (a["defsof"] / a["defcnt"]) / 3) * 100
            comps.append((PESO_DEF, notaDef))
        wsum = sum(p for p, _ in comps) or 1
        idx = (sum(p * v_ for p, v_ in comps) / wsum)
        sof = round(a["defsof"] / a["defcnt"], 1) if a["defcnt"] else None
        rank.append({"n": a["nome"], "th": a["th"], "atk": atk, "est": a["est"],
                     "spa": round(spa, 2), "conf": round(conf * 100),
                     "def": (round(notaDef) if notaDef is not None else None),
                     "sof": sof, "ndef": a["defcnt"], "idx": round(idx, 1),
                     "mvp": a["est"] + a["defneg"]})
    rank.sort(key=lambda x: -x["idx"])
    for i, x in enumerate(rank): x["pos"] = i + 1
    return rank, {"guerras": guerras_contadas, "v": v, "e": e, "d": d}

def build_data_js(out, hist):
    j = lambda val: json.dumps(val, ensure_ascii=False)
    rank, campeonato = agregar(hist, out["elenco"])
    a = out.get("atual")
    if a and a["state"] in ("preparation", "inWar"):
        esc = [m["nome"] for m in a["membros"]]
        esc_tags = {m["tag"] for m in a["membros"]}
        res = [m["nome"] for m in out["elenco"] if m["tag"] not in esc_tags]
        atual_js = {"vs": a["adversario"], "tam": f'{a["teamSize"]} x {a["teamSize"]}',
                    "state": a["state"], "inicio": a["inicio"], "fim": a["fim"]}
    else:
        esc, res = [], [m["nome"] for m in out["elenco"]]
        atual_js = None
    data = {"nome": out["nome"], "atual": atual_js, "campeonato": campeonato,
            "esc": esc, "res": res, "rank": rank}
    return "const DATA=" + j(data) + ";\n"

def injetar_no_html(data_js):
    idx = ROOT / "index.html"
    html = idx.read_text(encoding="utf-8")
    import re
    html = re.sub(r"const DATA\s*=\s*\{.*?\};\s*", data_js, html, count=1, flags=re.DOTALL)
    idx.write_text(html, encoding="utf-8")

def main():
    print("Coletando guerra atual do Clã 5 e-SpamiReza...")
    out = coletar()
    hist = salvar_historico(out)
    (ROOT / "esports_data.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    injetar_no_html(build_data_js(out, hist))
    a = out.get("atual")
    if a:
        print(f"  vs {a['adversario']} · {a['teamSize']}x{a['teamSize']} · state={a['state']}")
    else:
        print(f"  sem guerra ativa — {out.get('erro','')}")
    print("OK -> index.html + historico/guerras.json atualizados")

if __name__ == "__main__":
    main()
