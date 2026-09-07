import csv
from datetime import date, datetime, time, timedelta
import json
import math
import os
from zoneinfo import ZoneInfo
import folium
from folium.plugins import Draw
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

FUSO_BSB = ZoneInfo("America/Sao_Paulo")

# ==========================================
# Configuração do Supabase (Solução 1 - Banco de Dados)
# ==========================================
USE_SUPABASE = False
try:
    from supabase import Client, create_client

    if "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets:
        supabase: Client = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        )
        USE_SUPABASE = True
except (ImportError, FileNotFoundError, KeyError):
    pass

API = "https://logistic.gojet.app/api/v0/urent"
CITY_ID = "6787b812c168def1b2c6d143"
REGISTROS_CSV = os.path.join(os.path.dirname(__file__), "registros.csv")
ESTADO_JSON = os.path.join(os.path.dirname(__file__), "estado_rota.json")

REGIOES_DF = {
    "Personalizado (Apenas Raio)": None,
    "🖊️ Desenhar Área no Mapa": None,
    "Asa Sul": ("circle", -15.8293, -47.8927, 4.13),
    "Asa Norte": ("circle", -15.7602, -47.8758, 3.87),
    "Sudoeste": ("circle", -15.7871, -47.9318, 2.57),
    "Plano Piloto": (
        "multi_circle",
        [(-15.8393, -47.8839, 5.34), (-15.7551, -47.8650, 5.89)],
    ),
    "Guará": ("box", -15.8534, -15.8041, -47.9993, -47.9579),
    "Águas Claras": ("box", -15.8633, -15.8155, -48.0619, -48.0036),
}

REGIOES_CENTRO = {
    "Asa Sul": (-15.8293, -47.8927),
    "Asa Norte": (-15.7602, -47.8758),
    "Sudoeste": (-15.7871, -47.9318),
    "Plano Piloto": (-15.7939, -47.8828),
    "Guará": (-15.8287, -47.9786),
    "Águas Claras": (-15.8394, -48.0327),
}

REGIOES_ESPECIAIS = ("Personalizado (Apenas Raio)", "🖊️ Desenhar Área no Mapa")


def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def ponto_dentro_da_regiao(lat, lng, reg_info):
    if not reg_info:
        return True
    tipo = reg_info[0]
    if tipo == "circle":
        _, c_lat, c_lng, r_km = reg_info
        return haversine(c_lat, c_lng, lat, lng) <= r_km
    elif tipo == "multi_circle":
        _, circulos = reg_info
        return any(
            haversine(c_lat, c_lng, lat, lng) <= r_km
            for c_lat, c_lng, r_km in circulos
        )
    elif tipo == "box":
        _, min_lat, max_lat, min_lng, max_lng = reg_info
        return (min_lat <= lat <= max_lat) and (min_lng <= lng <= max_lng)
    return True


@st.cache_data(ttl=60, show_spinner=False)
def fetch_all_pages(endpoint):
    all_entries = []
    page = 1
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
    }

    while True:
        url = f"{API}/{endpoint}"
        params = {"city_id": CITY_ID, "page": page, "limit": 1000}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            entries = data.get("entries", [])
            all_entries.extend(entries)
            if page >= data.get("total_pages", 1):
                break
            page += 1
        except requests.exceptions.RequestException as e:
            st.error(f"Erro ao conectar com a API ({endpoint}): {e}")
            break
        except requests.exceptions.JSONDecodeError:
            break
    return all_entries


def zonas_soltos(bikes, grid=0.0015):
    grupos = {}
    for b in bikes:
        if b.get("parking_id"):
            continue

        is_rented = b.get("is_rented", False)
        status = str(b.get("status", "")).lower()
        state = str(b.get("state", "")).lower()
        if (
            is_rented
            or status in ["in_use", "rented", "maintenance"]
            or state in ["in_use", "rented"]
        ):
            continue

        lat, lng = b.get("location_lat"), b.get("location_lng")
        if lat is None or lng is None:
            continue
        chave = (round(lat / grid) * grid, round(lng / grid) * grid)
        grupos.setdefault(chave, []).append((lat, lng))

    zonas = []
    for (klat, klng), pts in grupos.items():
        avg_lat = sum(p[0] for p in pts) / len(pts)
        avg_lng = sum(p[1] for p in pts) / len(pts)
        zonas.append({
            "name": f"🟢 {len(pts)} patinete(s) solto(s) na rua",
            "lat": avg_lat,
            "lng": avg_lng,
            "diff": len(pts),
            "kind": "solto",
        })
    return zonas


def maps_link(lat, lng):
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}&travelmode=walking"


def get_osrm_route(path_coords):
    if len(path_coords) < 2:
        return path_coords, 0, 0, True

    coords_str = ";".join([f"{lng},{lat}" for lat, lng in path_coords])
    url = f"http://router.project-osrm.org/route/v1/foot/{coords_str}?geometries=geojson&overview=full"

    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == "Ok":
                route_info = data["routes"][0]
                coords = [
                    [lat, lng]
                    for lng, lat in route_info["geometry"]["coordinates"]
                ]
                dist_m = route_info.get("distance", 0)
                dur_s = route_info.get("duration", 0)
                return coords, dist_m, dur_s, True
    except Exception:
        pass
    return path_coords, 0, 0, False


# ==========================================
# Funções de Banco de Dados / Estado
# ==========================================
def carregar_estado():
    if USE_SUPABASE:
        try:
            res = (
                supabase.table("estado_rota")
                .select("dados")
                .eq("id", 1)
                .execute()
            )
            if res.data:
                return res.data[0]["dados"]
        except Exception:
            pass
        return {}
    else:
        if not os.path.exists(ESTADO_JSON):
            return {}
        try:
            with open(ESTADO_JSON, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def salvar_estado(d):
    if USE_SUPABASE:
        try:
            supabase.table("estado_rota").upsert({"id": 1, "dados": d}).execute()
        except Exception:
            pass
    else:
        try:
            with open(ESTADO_JSON, "w", encoding="utf-8") as f:
                json.dump(d, f)
        except Exception:
            pass


def limpar_estado():
    if USE_SUPABASE:
        try:
            supabase.table("estado_rota").update({"dados": {}}).eq(
                "id", 1
            ).execute()
        except Exception:
            pass
    else:
        if os.path.exists(ESTADO_JSON):
            try:
                os.remove(ESTADO_JSON)
            except Exception:
                pass


def carregar_registros():
    if USE_SUPABASE:
        try:
            res = supabase.table("registros_diarios").select("*").execute()
            return [
                {
                    "Data": r["data"],
                    "Patinetes": r["patinetes"],
                    "Ganhos (R$)": float(r["ganhos"]),
                }
                for r in res.data
            ]
        except Exception:
            return []
    else:
        if not os.path.exists(REGISTROS_CSV):
            return []
        with open(REGISTROS_CSV, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


def salvar_registro(data_str, qtd, ganho):
    if USE_SUPABASE:
        try:
            supabase.table("registros_diarios").insert({
                "data": data_str,
                "patinetes": str(qtd),
                "ganhos": ganho,
            }).execute()
        except Exception:
            pass
    else:
        novo = not os.path.exists(REGISTROS_CSV)
        with open(REGISTROS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if novo:
                writer.writerow(["Data", "Patinetes", "Ganhos (R$)"])
            writer.writerow([data_str, qtd, f"{ganho:.2f}"])


def snapshot_estado():
    return {
        "rota_gerada": st.session_state.get("rota_gerada", False),
        "route_data": st.session_state.get("route_data", []),
        "route_version": st.session_state.get("route_version", 0),
        "total_delivered": st.session_state.get("total_delivered", 0),
        "dist_total": st.session_state.get("dist_total", 0),
        "tempo_est": st.session_state.get("tempo_est", 0),
        "start_lat": st.session_state.get("start_lat", -15.8000),
        "start_lng": st.session_state.get("start_lng", -47.8950),
        "passo_feito": st.session_state.get("passo_feito", []),
        "entregues_sessao": st.session_state.get("entregues_sessao", 0),
        "contados_sessao": list(st.session_state.get("contados_sessao", set())),
        "meta": st.session_state.get("ultima_meta", 20),
        "cap": st.session_state.get("ultima_cap", 2),
        "regiao": st.session_state.get("ultima_regiao", "Asa Sul"),
        "draw_lat": st.session_state.get("draw_lat"),
        "draw_lng": st.session_state.get("draw_lng"),
        "draw_radius_km": st.session_state.get("draw_radius_km"),
    }


def render_area_selector(widget_key, default_center):
    st.markdown(
        "**🖊️ Desenhe um círculo no mapa para definir a área de busca:**"
    )

    center = [
        st.session_state.get("draw_lat", default_center[0]),
        st.session_state.get("draw_lng", default_center[1]),
    ]
    m_draw = folium.Map(location=center, zoom_start=13)
    Draw(
        export=False,
        draw_options={
            "polyline": False,
            "polygon": False,
            "rectangle": False,
            "circle": True,
            "marker": False,
            "circlemarker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m_draw)

    if "draw_lat" in st.session_state and "draw_radius_km" in st.session_state:
        folium.Circle(
            [st.session_state["draw_lat"], st.session_state["draw_lng"]],
            radius=st.session_state["draw_radius_km"] * 1000,
            color="orange",
            fill=True,
            fill_opacity=0.15,
        ).add_to(m_draw)

    out = st_folium(
        m_draw,
        height=400,
        use_container_width=True,
        key=widget_key,
        returned_objects=["last_active_drawing"],
    )

    if out and out.get("last_active_drawing"):
        geom = out["last_active_drawing"].get("geometry", {}) or {}
        props = out["last_active_drawing"].get("properties", {}) or {}
        if geom.get("type") == "Point" and "radius" in props:
            c_lng, c_lat = geom["coordinates"]
            st.session_state["draw_lat"] = c_lat
            st.session_state["draw_lng"] = c_lng
            st.session_state["draw_radius_km"] = props["radius"] / 1000.0
            salvar_estado(snapshot_estado())

    if "draw_lat" in st.session_state and "draw_radius_km" in st.session_state:
        st.success(
            f"✅ Área definida: raio de {st.session_state['draw_radius_km']:.2f} km "
            f"em torno de ({st.session_state['draw_lat']:.5f}, {st.session_state['draw_lng']:.5f})"
        )
        return (
            "circle",
            st.session_state["draw_lat"],
            st.session_state["draw_lng"],
            st.session_state["draw_radius_km"],
        )
    else:
        st.warning(
            "⚠️ Desenhe um círculo no mapa (ícone de círculo na barra à esquerda do mapa) antes de prosseguir."
        )
        return None


def nivel_criticidade(zone):
    if zone.get("kind") != "estacionamento":
        return 2
    bikes_count = zone.get("bikes_count")
    if bikes_count == 0:
        return 0
    if bikes_count == 1:
        return 1
    return 2


def ordenar_alvos(current, targets, acao, pool_completo=None):
    for t in targets:
        d_km = haversine(current["lat"], current["lng"], t["lat"], t["lng"])
        t["_dist_km"] = d_km
        t["_dur_min"] = (d_km / 15.0) * 60.0

        score = d_km
        if acao == "PEGAR":
            if t.get("kind") == "solto":
                score -= 0.15
        elif acao == "DEIXAR":
            crit = nivel_criticidade(t)
            if crit == 0:
                score -= 0.25
            elif crit == 1:
                score -= 0.10

        t["_score"] = score

    targets.sort(key=lambda z: z["_score"])
    return targets


def gerar_rota(
    lat,
    lng,
    meta,
    cap,
    regiao_sel,
    incluir_soltos,
    raio_personalizado=None,
    reg_info_override=None,
):
    parkings = fetch_all_pages("parkings")

    if reg_info_override is not None:
        reg_info = reg_info_override
    elif regiao_sel == "Personalizado (Apenas Raio)":
        reg_info = ("circle", lat, lng, raio_personalizado)
    else:
        reg_info = REGIOES_DF.get(regiao_sel)

    zones = []
    for p in parkings:
        diff = p.get("bikes_count", 0) - p.get("target_bikes_count", 0)
        if diff != 0 and ponto_dentro_da_regiao(
            p["latitude"], p["longitude"], reg_info
        ):
            zones.append({
                "name": p.get("name", "Ponto"),
                "lat": p["latitude"],
                "lng": p["longitude"],
                "diff": diff,
                "kind": "estacionamento",
                "bikes_count": p.get("bikes_count", 0),
            })

    if incluir_soltos:
        bikes = fetch_all_pages("bikes")
        for z in zonas_soltos(bikes):
            if ponto_dentro_da_regiao(z["lat"], z["lng"], reg_info):
                zones.append(z)

    pool = [dict(z) for z in zones]
    route = []
    carrying = 0
    current = {"lat": lat, "lng": lng, "name": "INÍCIO"}
    total_delivered = 0

    while len(route) < 100:
        if total_delivered >= meta:
            break
        has_surplus = any(z["diff"] > 0 for z in pool)
        if carrying == 0 and not has_surplus:
            break

        if carrying > 0:
            targets = [z for z in pool if z["diff"] < 0]
            if not targets:
                break

            targets = ordenar_alvos(current, targets, "DEIXAR")
            t = targets[0]

            qty = min(carrying, -t["diff"], meta - total_delivered)
            if qty <= 0:
                break
            route.append({
                "action": "DEIXAR",
                "qty": qty,
                "name": t["name"],
                "coords": (t["lat"], t["lng"]),
                "dist": t["_dist_km"],
                "duracao_min": t["_dur_min"],
                "criticidade": nivel_criticidade(t),
            })
            t["diff"] += qty
            carrying -= qty
            total_delivered += qty
            current = {"lat": t["lat"], "lng": t["lng"], "name": t["name"]}

        else:
            targets = [z for z in pool if z["diff"] > 0]
            if not targets:
                break

            targets = ordenar_alvos(current, targets, "PEGAR", pool)
            t = targets[0]

            qty = min(cap, t["diff"], meta - total_delivered)
            if qty <= 0:
                break
            route.append({
                "action": "PEGAR",
                "qty": qty,
                "name": t["name"],
                "coords": (t["lat"], t["lng"]),
                "dist": t["_dist_km"],
                "duracao_min": t["_dur_min"],
            })
            t["diff"] -= qty
            carrying += qty
            current = {"lat": t["lat"], "lng": t["lng"], "name": t["name"]}

    dist_total = sum(r["dist"] for r in route)

    tempo_manuseio = 0.0
    for r in route:
        if r["qty"] == 1:
            tempo_manuseio += 1.0
        elif r["qty"] >= 2:
            tempo_manuseio += 1.75 + (r["qty"] - 2) * 0.75

    tempo_est = math.ceil(sum(r["duracao_min"] for r in route) + tempo_manuseio)
    return route, total_delivered, dist_total, tempo_est


def melhor_ponto_inicio(zonas_surplus, meta_qtd, lat_ini=None, lng_ini=None):
    melhor_candidato = None
    melhor_custo = float("inf")
    melhor_cadeia = []

    for candidato in zonas_surplus:
        pool = [dict(z) for z in zonas_surplus]
        current = {"lat": candidato["lat"], "lng": candidato["lng"]}
        acumulado = 0
        custo = 0.0
        cadeia = []
        primeira_parada = True

        while acumulado < meta_qtd:
            disponiveis = [z for z in pool if z["diff"] > 0]
            if not disponiveis:
                break
            disponiveis = ordenar_alvos(current, disponiveis, "PEGAR", pool)
            t = disponiveis[0]

            d = haversine(current["lat"], current["lng"], t["lat"], t["lng"])
            if (
                primeira_parada
                and t["name"] == candidato["name"]
                and t["lat"] == candidato["lat"]
            ):
                d = 0.0
            pega = min(t["diff"], meta_qtd - acumulado)
            custo += d
            acumulado += pega
            cadeia.append({
                "name": t["name"],
                "lat": t["lat"],
                "lng": t["lng"],
                "qty": pega,
                "dist": d,
            })
            t["diff"] -= pega
            current = {"lat": t["lat"], "lng": t["lng"]}
            primeira_parada = False
            if t["diff"] <= 0:
                pool.remove(t)

        distancia_chegada = (
            haversine(lat_ini, lng_ini, candidato["lat"], candidato["lng"])
            if lat_ini and lng_ini
            else 0
        )
        custo_total = custo + distancia_chegada

        if acumulado >= meta_qtd and custo_total < melhor_custo:
            melhor_custo = custo_total
            melhor_candidato = candidato
            melhor_cadeia = cadeia

    return melhor_candidato, melhor_custo, melhor_cadeia


# ==========================================
# Projeção de Descarga da Bateria com Horário Base
# ==========================================
def projetar_bateria_datas(bateria_atual_pct, dt_inicio, dt_alvo):
    delta_horas = (dt_alvo - dt_inicio).total_seconds() / 3600.0
    if delta_horas < 0:
        delta_horas = 0.0

    # Consumo fixo observado de 1% a cada 35.5 minutos (~1.69% por hora parado)
    gasto = delta_horas * (60.0 / 35.5)
    bateria_futura = max(0.0, bateria_atual_pct - gasto)
    return round(bateria_futura, 1), round(delta_horas, 2)


# ==========================================
# Configuração da Página UI
# ==========================================
st.set_page_config(page_title="JET Logística Mobile", layout="wide")
st.title("🚀 Operador JET DF")

if USE_SUPABASE:
    st.caption("✅ Conectado ao banco de dados em nuvem.")

_estado_salvo = carregar_estado()

if "rota_gerada" not in st.session_state:
    st.session_state.rota_gerada = _estado_salvo.get("rota_gerada", False)
    st.session_state.route_data = _estado_salvo.get("route_data", [])
    st.session_state.route_version = _estado_salvo.get("route_version", 0)
    st.session_state.total_delivered = _estado_salvo.get("total_delivered", 0)
    st.session_state.dist_total = _estado_salvo.get("dist_total", 0)
    st.session_state.tempo_est = _estado_salvo.get("tempo_est", 0)
    st.session_state.start_lat = _estado_salvo.get("start_lat", -15.8000)
    st.session_state.start_lng = _estado_salvo.get("start_lng", -47.8950)
    st.session_state.passo_feito = _estado_salvo.get("passo_feito", [])
    st.session_state.entregues_sessao = _estado_salvo.get("entregues_sessao", 0)
    st.session_state.contados_sessao = set(
        _estado_salvo.get("contados_sessao", [])
    )
    st.session_state.ultima_meta = _estado_salvo.get("meta", 20)
    st.session_state.ultima_cap = _estado_salvo.get("cap", 2)
    st.session_state.ultima_regiao = _estado_salvo.get("regiao", "Asa Sul")
    if _estado_salvo.get("draw_lat") is not None:
        st.session_state.draw_lat = _estado_salvo.get("draw_lat")
        st.session_state.draw_lng = _estado_salvo.get("draw_lng")
        st.session_state.draw_radius_km = _estado_salvo.get("draw_radius_km")

if "registros" not in st.session_state:
    st.session_state.registros = carregar_registros()

tab_rotas, tab_inicio, tab_scanner, tab_registros, tab_bateria = st.tabs(
    ["🗺️ Gerador", "🎯 Onde Começar", "📡 Scanner", "📅 Registros", "🔋 Bateria"]
)

# ==========================================
# ABA 1: GERADOR DE ROTAS
# ==========================================
with tab_rotas:
    if st.session_state.rota_gerada:
        st.caption("🔁 Rota recuperada de onde você parou.")

    regioes_lista = list(REGIOES_DF.keys())
    idx_regiao_padrao = (
        regioes_lista.index(st.session_state.ultima_regiao)
        if st.session_state.ultima_regiao in regioes_lista
        else 0
    )

    col_reg, col_raio = st.columns(2)
    with col_reg:
        regiao_sel = st.selectbox(
            "Selecione a Região:", regioes_lista, index=idx_regiao_padrao
        )
    with col_raio:
        raio_personalizado = None
        if regiao_sel == "Personalizado (Apenas Raio)":
            raio_personalizado = st.number_input(
                "Raio de busca (km)",
                min_value=0.5,
                max_value=15.0,
                value=2.0,
                step=0.5,
            )
        elif regiao_sel == "🖊️ Desenhar Área no Mapa":
            st.caption("Desenhe a área no mapa logo abaixo ⬇️")
        else:
            st.write("")

    coords_padrao = REGIOES_CENTRO.get(regiao_sel, (-15.7939, -47.8828))

    reg_info_override = None
    if regiao_sel == "🖊️ Desenhar Área no Mapa":
        reg_info_override = render_area_selector(
            "map_draw_rotas", coords_padrao
        )

    col1, col2 = st.columns(2)
    with col1:
        lat_padrao = (
            st.session_state.start_lat
            if st.session_state.rota_gerada
            else coords_padrao[0]
        )
        lat = st.number_input("Latitude Inicial", value=lat_padrao, format="%.5f")
        cap = st.number_input(
            "Capacidade da Viagem", value=st.session_state.ultima_cap, step=1
        )
    with col2:
        lng_padrao = (
            st.session_state.start_lng
            if st.session_state.rota_gerada
            else coords_padrao[1]
        )
        lng = st.number_input(
            "Longitude Inicial", value=lng_padrao, format="%.5f"
        )
        meta = st.number_input(
            "Meta de Patinetes", value=st.session_state.ultima_meta, step=1
        )

    incluir_soltos = st.checkbox("Incluir patinetes soltos na rua", value=True)
    usar_rota_real = st.checkbox(
        "🧭 Calcular distância real pelas ruas (OSRM)",
        value=False,
        help="Em áreas de quadra fechada o OSRM pode dar uma volta enorme onde a pé daria pra cortar caminho. Deixe desmarcado pra usar linha reta (mais realista).",
    )

    col_gerar, col_limpar = st.columns([3, 1])
    with col_limpar:
        if st.button("🗑️ Limpar sessão", use_container_width=True):
            limpar_estado()
            for k in [
                "rota_gerada",
                "route_data",
                "total_delivered",
                "dist_total",
                "tempo_est",
                "start_lat",
                "start_lng",
                "passo_feito",
                "entregues_sessao",
                "contados_sessao",
            ]:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()

    with col_gerar:
        if st.button("🔥 Gerar Rota Otimizada", use_container_width=True):
            if (
                regiao_sel == "🖊️ Desenhar Área no Mapa"
                and reg_info_override is None
            ):
                st.error(
                    "Desenhe um círculo no mapa para definir a área antes de gerar a rota."
                )
            else:
                with st.spinner("Buscando dados e calculando rotas..."):
                    route, total_delivered, dist_total, tempo_est = gerar_rota(
                        lat,
                        lng,
                        meta,
                        cap,
                        regiao_sel,
                        incluir_soltos,
                        raio_personalizado,
                        reg_info_override,
                    )
                    if route:
                        st.session_state.rota_gerada = True
                        st.session_state.route_data = route
                        st.session_state.route_version = (
                            st.session_state.get("route_version", 0) + 1
                        )
                        st.session_state.total_delivered = total_delivered
                        st.session_state.dist_total = dist_total
                        st.session_state.tempo_est = tempo_est
                        st.session_state.start_lat = lat
                        st.session_state.start_lng = lng
                        st.session_state.passo_feito = [False] * len(route)
                        st.session_state.entregues_sessao = 0
                        st.session_state.contados_sessao = set()
                        st.session_state.ultima_meta = meta
                        st.session_state.ultima_cap = cap
                        st.session_state.ultima_regiao = regiao_sel
                        salvar_estado(snapshot_estado())
                    else:
                        st.warning("Nenhuma rota encontrada para essa região.")
                        st.session_state.rota_gerada = False

    if st.session_state.rota_gerada:
        st.success(
            f"✅ Rota Gerada! Total: {st.session_state.total_delivered} patinetes | R$ {st.session_state.total_delivered * 1.50:.2f}"
        )

        path = [[st.session_state.start_lat, st.session_state.start_lng]]
        for idx, r in enumerate(st.session_state.route_data, 1):
            path.append(r["coords"])

        if usar_rota_real:
            with st.spinner("Calculando trajeto real pelas ruas (OSRM)..."):
                path_real, osrm_dist_m, osrm_dur_s, rota_ok = get_osrm_route(
                    path
                )

            if rota_ok:
                distancia_real_km = osrm_dist_m / 1000.0
                tempo_deslocamento_min = (distancia_real_km / 15.0) * 60.0

                tempo_manuseio = 0.0
                for r in st.session_state.route_data:
                    if r["qty"] == 1:
                        tempo_manuseio += 1.0
                    elif r["qty"] >= 2:
                        tempo_manuseio += 1.75 + (r["qty"] - 2) * 0.75

                tempo_est_real = math.ceil(
                    tempo_deslocamento_min + tempo_manuseio
                )
                st.info(
                    f"📍 **Distância (Ruas):** {distancia_real_km:.2f} km | ⏱️ **Tempo Est. (Ruas):** ~{tempo_est_real} min"
                )
            else:
                st.info(
                    f"📏 Distância (Linha Reta): {st.session_state.dist_total:.2f} km | ⏱️ Tempo Est.: ~{st.session_state.tempo_est} min"
                )
                st.caption("⚠️ Falha na API de ruas. Exibindo linha reta.")
                path_real = path
        else:
            path_real = path
            st.info(
                f"📏 Distância (Linha Reta): {st.session_state.dist_total:.2f} km | ⏱️ Tempo Est.: ~{st.session_state.tempo_est} min"
            )

        col_mapa, col_passos = st.columns([1.5, 1])
        with col_mapa:
            m = folium.Map(
                location=[
                    st.session_state.start_lat,
                    st.session_state.start_lng,
                ],
                zoom_start=15,
            )
            folium.CircleMarker(
                [st.session_state.start_lat, st.session_state.start_lng],
                radius=9,
                color="green",
                fill=True,
                popup="Início",
            ).add_to(m)

            if (
                st.session_state.ultima_regiao == "Personalizado (Apenas Raio)"
                and raio_personalizado
            ):
                folium.Circle(
                    [st.session_state.start_lat, st.session_state.start_lng],
                    radius=raio_personalizado * 1000,
                    color="gray",
                    fill=False,
                    opacity=0.3,
                ).add_to(m)
            elif (
                st.session_state.ultima_regiao == "🖊️ Desenhar Área no Mapa"
                and "draw_lat" in st.session_state
                and "draw_radius_km" in st.session_state
            ):
                folium.Circle(
                    [st.session_state["draw_lat"], st.session_state["draw_lng"]],
                    radius=st.session_state["draw_radius_km"] * 1000,
                    color="orange",
                    fill=False,
                    opacity=0.3,
                ).add_to(m)

            for idx, r in enumerate(st.session_state.route_data, 1):
                if r["action"] == "PEGAR":
                    cor = "blue"
                else:
                    crit = r.get("criticidade", 2)
                    cor = (
                        "red"
                        if crit == 0
                        else ("orange" if crit == 1 else "darkred")
                    )
                folium.CircleMarker(
                    r["coords"],
                    radius=8,
                    color=cor,
                    fill=True,
                    popup=f"{idx}. {r['action']}",
                ).add_to(m)

            folium.PolyLine(path_real, color="purple", weight=4).add_to(m)
            st_folium(
                m, use_container_width=True, height=450, returned_objects=[]
            )
            st.caption(
                "🔵 Pegar  ·  🔴 Deixar (crítico, 0 vagas)  ·  🟠 Deixar (quase vazio, 1)  ·  🔺 Deixar (normal)"
            )

        with col_passos:
            st.subheader("📍 Passo a Passo")
            lista_passos = st.container(height=420)
            with lista_passos:
                for idx, r in enumerate(st.session_state.route_data, 1):
                    lk = maps_link(*r["coords"])
                    i = idx - 1
                    if r["action"] == "PEGAR":
                        acao_txt = "🟢 PEGAR"
                    else:
                        crit = r.get("criticidade", 2)
                        if crit == 0:
                            acao_txt = "🔴 DEIXAR (crítico — 0 patinetes)"
                        elif crit == 1:
                            acao_txt = "🟠 DEIXAR (quase vazio — 1 patinete)"
                        else:
                            acao_txt = "🔴 DEIXAR"
                    col_chk, col_txt = st.columns([0.15, 0.85])
                    with col_chk:
                        feito = st.checkbox(
                            "",
                            key=f"passo_{st.session_state.route_version}_{idx}",
                            value=st.session_state.passo_feito[i],
                        )
                    with col_txt:
                        st.markdown(
                            f"**{idx}. {acao_txt}** {r['qty']} un. em {r['name']}  \n"
                            f"~{r['duracao_min']:.0f} min / {r['dist']:.2f} km  \n"
                            f"[🧭 Maps]({lk})"
                        )

                    mudou = False
                    if feito and not st.session_state.passo_feito[i]:
                        st.session_state.passo_feito[i] = True
                        mudou = True
                        if (
                            r["action"] == "DEIXAR"
                            and idx not in st.session_state.contados_sessao
                        ):
                            st.session_state.entregues_sessao += r["qty"]
                            st.session_state.contados_sessao.add(idx)
                    elif not feito and st.session_state.passo_feito[i]:
                        st.session_state.passo_feito[i] = False
                        mudou = True
                        if idx in st.session_state.contados_sessao:
                            st.session_state.entregues_sessao -= r["qty"]
                            st.session_state.contados_sessao.discard(idx)

                    if mudou:
                        salvar_estado(snapshot_estado())
                    st.divider()

            st.caption(
                f"{sum(st.session_state.passo_feito)}/{len(st.session_state.route_data)} concluídos · {st.session_state.entregues_sessao} entregues"
            )
            if st.button("🔄 Recalcular", use_container_width=True):
                with st.spinner("Recalculando..."):
                    meta_restante = max(
                        meta - st.session_state.entregues_sessao, 1
                    )
                    route, total_delivered, dist_total, tempo_est = gerar_rota(
                        lat,
                        lng,
                        meta_restante,
                        cap,
                        regiao_sel,
                        incluir_soltos,
                        raio_personalizado,
                        reg_info_override,
                    )
                    if route:
                        st.session_state.route_data = route
                        st.session_state.route_version = (
                            st.session_state.get("route_version", 0) + 1
                        )
                        st.session_state.total_delivered = total_delivered
                        st.session_state.dist_total = dist_total
                        st.session_state.tempo_est = tempo_est
                        st.session_state.passo_feito = [False] * len(route)
                        st.session_state.contados_sessao = set()
                        salvar_estado(snapshot_estado())
                        st.rerun()

# ==========================================
# ABA 2: ONDE COMEÇAR
# ==========================================
with tab_inicio:
    st.header("🎯 Onde Começar")
    col_x, col_y = st.columns(2)
    with col_x:
        regiao_inicio = st.selectbox(
            "Região:", list(REGIOES_DF.keys()), key="regiao_inicio"
        )
    with col_y:
        meta_inicio = st.number_input(
            "Metas (patinetes)",
            min_value=1,
            value=10,
            step=1,
            key="meta_inicio",
        )

    col_lat_ini, col_lng_ini = st.columns(2)
    with col_lat_ini:
        lat_ini = st.number_input(
            "Sua Latitude Atual", value=-15.8000, format="%.5f"
        )
    with col_lng_ini:
        lng_ini = st.number_input(
            "Sua Longitude Atual", value=-47.8950, format="%.5f"
        )

    raio_inicio = None
    if regiao_inicio == "Personalizado (Apenas Raio)":
        raio_inicio = st.number_input(
            "Raio de busca (km)", value=3.0, step=0.5, key="raio_inicio_input"
        )

    reg_info_override_inicio = None
    if regiao_inicio == "🖊️ Desenhar Área no Mapa":
        reg_info_override_inicio = render_area_selector(
            "map_draw_inicio", (lat_ini, lng_ini)
        )

    incluir_soltos_inicio = st.checkbox(
        "Incluir patinetes soltos na rua", value=True, key="soltos_inicio"
    )

    if st.button("🔍 Achar melhor ponto", use_container_width=True):
        if (
            regiao_inicio == "🖊️ Desenhar Área no Mapa"
            and reg_info_override_inicio is None
        ):
            st.error(
                "Desenhe um círculo no mapa para definir a área antes de buscar."
            )
        else:
            with st.spinner("Testando..."):
                if reg_info_override_inicio is not None:
                    reg_info = reg_info_override_inicio
                elif regiao_inicio == "Personalizado (Apenas Raio)":
                    reg_info = ("circle", lat_ini, lng_ini, raio_inicio)
                else:
                    reg_info = REGIOES_DF.get(regiao_inicio)

                parkings = fetch_all_pages("parkings")
                zonas_surplus = []
                for p in parkings:
                    diff = p.get("bikes_count", 0) - p.get(
                        "target_bikes_count", 0
                    )
                    if diff > 0 and ponto_dentro_da_regiao(
                        p["latitude"], p["longitude"], reg_info
                    ):
                        zonas_surplus.append({
                            "name": p.get("name", "Ponto"),
                            "lat": p["latitude"],
                            "lng": p["longitude"],
                            "diff": diff,
                            "kind": "estacionamento",
                        })

                if incluir_soltos_inicio:
                    bikes = fetch_all_pages("bikes")
                    for z in zonas_soltos(bikes):
                        if ponto_dentro_da_regiao(z["lat"], z["lng"], reg_info):
                            zonas_surplus.append(z)

                if not zonas_surplus:
                    st.warning("Nenhum ponto com sobra encontrado.")
                else:
                    candidato, custo, cadeia = melhor_ponto_inicio(
                        zonas_surplus, meta_inicio, lat_ini, lng_ini
                    )
                    if candidato:
                        lk = maps_link(candidato["lat"], candidato["lng"])
                        st.success(f"🏆 Melhor ponto: **{candidato['name']}**")
                        st.info(
                            f"📏 {custo:.2f} km de deslocamento total (incluindo até o 1º ponto)."
                        )

                        m2 = folium.Map(
                            location=[lat_ini, lng_ini], zoom_start=14
                        )
                        folium.CircleMarker(
                            [lat_ini, lng_ini],
                            radius=7,
                            color="black",
                            fill=True,
                            popup="Você está aqui",
                        ).add_to(m2)
                        folium.CircleMarker(
                            [candidato["lat"], candidato["lng"]],
                            radius=10,
                            color="green",
                            fill=True,
                            popup="Começar Aqui",
                        ).add_to(m2)
                        if (
                            regiao_inicio == "Personalizado (Apenas Raio)"
                            and raio_inicio
                        ):
                            folium.Circle(
                                [lat_ini, lng_ini],
                                radius=raio_inicio * 1000,
                                color="gray",
                                fill=False,
                                opacity=0.3,
                            ).add_to(m2)
                        elif (
                            regiao_inicio == "🖊️ Desenhar Área no Mapa"
                            and reg_info_override_inicio
                        ):
                            _, c_lat, c_lng, c_r = reg_info_override_inicio
                            folium.Circle(
                                [c_lat, c_lng],
                                radius=c_r * 1000,
                                color="gray",
                                fill=False,
                                opacity=0.3,
                            ).add_to(m2)

                        for c in cadeia:
                            folium.CircleMarker(
                                [c["lat"], c["lng"]],
                                radius=7,
                                color="blue",
                                fill=True,
                            ).add_to(m2)
                        st_folium(
                            m2,
                            use_container_width=True,
                            height=400,
                            returned_objects=[],
                        )

# ==========================================
# ABA 3: SCANNER
# ==========================================
with tab_scanner:
    st.header("📡 Scanner")
    if st.button("🔍 Escanear Todas as Regiões", use_container_width=True):
        with st.spinner("Analisando..."):
            parkings = fetch_all_pages("parkings")
            resultados = []
            for nome_regiao, reg_info in REGIOES_DF.items():
                if nome_regiao in REGIOES_ESPECIAIS:
                    continue
                sobrando, faltando = 0, 0
                for p in parkings:
                    if ponto_dentro_da_regiao(
                        p["latitude"], p["longitude"], reg_info
                    ):
                        diff = p.get("bikes_count", 0) - p.get(
                            "target_bikes_count", 0
                        )
                        if diff > 0:
                            sobrando += diff
                        elif diff < 0:
                            faltando += abs(diff)
                resultados.append({
                    "Região": nome_regiao,
                    "Potencial Máximo (Tarefas)": min(sobrando, faltando),
                })
            df_resultados = (
                pd.DataFrame(resultados)
                .sort_values(
                    by="Potencial Máximo (Tarefas)", ascending=False
                )
                .reset_index(drop=True)
            )
            st.dataframe(df_resultados, use_container_width=True)

# ==========================================
# ABA 4: REGISTROS
# ==========================================
with tab_registros:
    st.header("📅 Registros")
    meta_mensal = st.number_input(
        "🎯 Meta mensal (R$)", value=4000.0, step=100.0
    )

    with st.form("form_registro"):
        col_data, col_qtd, col_add = st.columns([2, 2, 1])
        with col_data:
            data_reg = st.date_input(
                "Data", value=date.today(), format="DD/MM/YYYY"
            )
        with col_qtd:
            qtd_patinetes = st.number_input("Patinetes", min_value=1, step=1)
        with col_add:
            submit_reg = st.form_submit_button("Salvar")

        if submit_reg:
            ganho = qtd_patinetes * 1.50
            data_str = data_reg.strftime("%d/%m/%Y")
            salvar_registro(data_str, qtd_patinetes, ganho)
            st.session_state.registros.append({
                "Data": data_str,
                "Patinetes": str(qtd_patinetes),
                "Ganhos (R$)": f"{ganho:.2f}",
            })
            st.success("Salvo!")

    if st.session_state.registros:
        df_registros = pd.DataFrame(st.session_state.registros)
        st.dataframe(df_registros, use_container_width=True)

# ==========================================
# ABA 5: BATERIA (Horário de Brasília & Filtro Total de Data/Hora)
# ==========================================
with tab_bateria:
    st.header("🔋 Previsão de Bateria da Frota")

    # Horário atual de Brasília
    agora_bsb = datetime.now(FUSO_BSB)

    st.subheader("1. Ponto de Partida (Horário Atual de Referência)")
    c_ref1, c_ref2 = st.columns(2)
    with c_ref1:
        data_base = st.date_input("Data Atual (DF):", value=agora_bsb.date())
    with c_ref2:
        hora_base = st.time_input("Hora Atual (DF):", value=agora_bsb.time())

    dt_inicio_selecionado = datetime.combine(
        data_base, hora_base, tzinfo=FUSO_BSB
    )

    st.subheader("2. Horário da Previsão (Até Quando Simular)")
    c_alvo1, c_alvo2 = st.columns(2)
    with c_alvo1:
        data_alvo = st.date_input(
            "Data Alvo:",
            value=agora_bsb.date(),
            help="Se for simular para a madrugada do dia seguinte, avance 1 dia.",
        )
    with c_alvo2:
        hora_alvo = st.time_input("Hora Alvo:", value=time(5, 0))

    dt_alvo_selecionado = datetime.combine(data_alvo, hora_alvo, tzinfo=FUSO_BSB)

    # Verificação do intervalo
    diff_horas = (
        dt_alvo_selecionado - dt_inicio_selecionado
    ).total_seconds() / 3600.0
    if diff_horas < 0:
        st.error(
            "⚠️ O horário alvo selecionado é ANTERIOR ao horário atual. Ajuste a data ou a hora."
        )
    else:
        st.caption(
            f"⏱️ Intervalo calculado: **{diff_horas:.2f} horas** até o horário alvo."
        )

    st.divider()

    st.subheader("3. Região e Filtros")
    col_reg_b, col_filtro = st.columns(2)
    with col_reg_b:
        regiao_bat = st.selectbox(
            "Filtrar por Região:", list(REGIOES_DF.keys()), key="regiao_bat_sel"
        )
    with col_filtro:
        filtro_status = st.selectbox(
            "Exibir no Mapa:",
            ["Apenas Críticos (<= 20%)", "Apenas Alerta (21% a 30%)", "Todos"],
            index=0,
        )

    raio_bat = None
    if regiao_bat == "Personalizado (Apenas Raio)":
        raio_bat = st.number_input(
            "Raio (km):", min_value=0.5, max_value=15.0, value=3.0, step=0.5
        )

    coords_centro_bat = REGIOES_CENTRO.get(regiao_bat, (-15.7939, -47.8828))
    reg_info_override_bat = None
    if regiao_bat == "🖊️ Desenhar Área no Mapa":
        reg_info_override_bat = render_area_selector(
            "map_draw_bat", coords_centro_bat
        )

    if st.button("🔍 Calcular Previsão e Mostrar Mapa", use_container_width=True):
        if diff_horas < 0:
            st.error("Corrija as datas/horários antes de continuar.")
        elif (
            regiao_bat == "🖊️ Desenhar Área no Mapa"
            and reg_info_override_bat is None
        ):
            st.error(
                "Desenhe um círculo no mapa acima para definir a área de busca."
            )
        else:
            with st.spinner("Buscando patinetes e simulando descarga..."):
                bikes = fetch_all_pages("bikes")

                if reg_info_override_bat is not None:
                    reg_info = reg_info_override_bat
                elif regiao_bat == "Personalizado (Apenas Raio)":
                    reg_info = (
                        "circle",
                        coords_centro_bat[0],
                        coords_centro_bat[1],
                        raio_bat,
                    )
                else:
                    reg_info = REGIOES_DF.get(regiao_bat)

                patinetes_processados = []
                for b in bikes:
                    bat_raw = b.get("battery_percent")
                    lat_b = b.get("location_lat")
                    lng_b = b.get("location_lng")

                    if bat_raw is None or lat_b is None or lng_b is None:
                        continue

                    if not ponto_dentro_da_regiao(lat_b, lng_b, reg_info):
                        continue

                    bat_atual = round(bat_raw * 100, 1)
                    bat_futura, horas_calc = projetar_bateria_datas(
                        bat_atual, dt_inicio_selecionado, dt_alvo_selecionado
                    )

                    patinetes_processados.append({
                        "identifier": b.get("identifier", "Sem ID"),
                        "bateria_atual": bat_atual,
                        "bateria_futura": bat_futura,
                        "lat": lat_b,
                        "lng": lng_b,
                    })

                if not patinetes_processados:
                    st.warning("Nenhum patinete encontrado nessa área.")
                else:
                    df_bat = pd.DataFrame(patinetes_processados)

                    if filtro_status == "Apenas Críticos (<= 20%)":
                        df_exibicao = df_bat[df_bat["bateria_futura"] <= 20]
                    elif filtro_status == "Apenas Alerta (21% a 30%)":
                        df_exibicao = df_bat[
                            (df_bat["bateria_futura"] > 20)
                            & (df_bat["bateria_futura"] <= 30)
                        ]
                    else:
                        df_exibicao = df_bat

                    st.info(
                        f"⏱️ Tempo simulado: **{diff_horas:.2f} horas** (consumo de ~1,69% por hora parado)"
                    )
                    st.success(
                        f"📍 Exibindo **{len(df_exibicao)}** patinetes de um total de {len(df_bat)} na região."
                    )

                    if not df_exibicao.empty:
                        lat_med = df_exibicao["lat"].mean()
                        lng_med = df_exibicao["lng"].mean()
                        m_bat = folium.Map(
                            location=[lat_med, lng_med], zoom_start=14
                        )

                        for _, row in df_exibicao.iterrows():
                            bat_f = row["bateria_futura"]
                            bat_a = row["bateria_atual"]
                            id_p = row["identifier"]

                            if bat_f <= 10:
                                cor = "red"
                            elif bat_f <= 20:
                                cor = "orange"
                            elif bat_f <= 30:
                                cor = "yellow"
                            else:
                                cor = "green"

                            lk = maps_link(row["lat"], row["lng"])
                            popup_html = f"""
                            <b>{id_p}</b><br>
                            Bateria agora: <b>{bat_a}%</b><br>
                            Às {dt_alvo_selecionado.strftime('%d/%m %H:%M')}: <b>{bat_f}%</b><br>
                            <a href="{lk}" target="_blank">🧭 Abrir no Maps</a>
                            """

                            folium.CircleMarker(
                                location=[row["lat"], row["lng"]],
                                radius=7,
                                color=cor,
                                fill=True,
                                fill_color=cor,
                                fill_opacity=0.85,
                                popup=popup_html,
                                tooltip=f"{id_p} | {bat_f}% às {dt_alvo_selecionado.strftime('%H:%M')}",
                            ).add_to(m_bat)

                        st_folium(
                            m_bat,
                            use_container_width=True,
                            height=550,
                            returned_objects=[],
                        )
                        st.caption(
                            "🔴 <= 10% (crítico) · 🟠 11% a 20% (recolher) · 🟡 21% a 30% · 🟢 > 30%"
                        )
                    else:
                        st.warning(
                            "Nenhum patinete se enquadra no filtro selecionado para esse intervalo de tempo."
                        )
