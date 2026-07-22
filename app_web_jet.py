import math
import requests
import folium
import streamlit as st
from streamlit_folium import st_folium

API = "https://logistic.gojet.app/api/v0/urent"
CITY_ID = "6787b812c168def1b2c6d143"

REGIOES_DF = {
    "Personalizado (Apenas Raio)": None,
    "Asa Sul": ("circle", -15.8293, -47.8927, 4.13),
    "Asa Norte": ("circle", -15.7602, -47.8758, 3.87),
    "Sudoeste": ("circle", -15.7871, -47.9318, 2.57),
    "Plano Piloto": ("multi_circle", [(-15.8393, -47.8839, 5.34), (-15.7551, -47.8650, 5.89)]),
    "Guará": ("box", -15.8534, -15.8041, -47.9993, -47.9579),
    "Águas Claras": ("box", -15.8633, -15.8155, -48.0619, -48.0036)
}

REGIOES_CENTRO = {
    "Asa Sul": (-15.8293, -47.8927),
    "Asa Norte": (-15.7602, -47.8758),
    "Sudoeste": (-15.7871, -47.9318),
    "Plano Piloto": (-15.7939, -47.8828),
    "Guará": (-15.8287, -47.9786),
    "Águas Claras": (-15.8394, -48.0327)
}

def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))

def ponto_dentro_da_regiao(lat, lng, reg_info):
    if not reg_info: return True
    tipo = reg_info[0]
    if tipo == "circle":
        _, c_lat, c_lng, r_km = reg_info
        return haversine(c_lat, c_lng, lat, lng) <= r_km
    elif tipo == "multi_circle":
        _, circulos = reg_info
        return any(haversine(c_lat, c_lng, lat, lng) <= r_km for c_lat, c_lng, r_km in circulos)
    elif tipo == "box":
        _, min_lat, max_lat, min_lng, max_lng = reg_info
        return (min_lat <= lat <= max_lat) and (min_lng <= lng <= max_lng)
    return True

def fetch_all_pages(endpoint):
    all_entries = []
    page = 1
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
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
            st.error(f"A API retornou uma resposta inválida (HTTP {r.status_code}). O servidor pode estar bloqueando conexões externas.")
            break
            
    return all_entries

# ==========================================
# Interface Web
# ==========================================
st.set_page_config(page_title="JET Logística Mobile", layout="centered")
st.title("🚀 Operador JET DF")

regiao_sel = st.selectbox("Selecione a Região:", list(REGIOES_DF.keys()))
coords_padrao = REGIOES_CENTRO.get(regiao_sel, (-15.7939, -47.8828))

col1, col2 = st.columns(2)
with col1:
    lat = st.number_input("Latitude Inicial", value=coords_padrao[0], format="%.4f")
    cap = st.number_input("Capacidade da Viagem", value=3, step=1)
with col2:
    lng = st.number_input("Longitude Inicial", value=coords_padrao[1], format="%.4f")
    meta = st.number_input("Meta de Patinetes", value=20, step=1)

if 'rota_gerada' not in st.session_state:
    st.session_state.rota_gerada = False

if st.button("🔥 Gerar Rota Otimizada", use_container_width=True):
    with st.spinner("Buscando dados da JET..."):
        parkings = fetch_all_pages("parkings")
        bikes = fetch_all_pages("bikes")
        reg_info = REGIOES_DF.get(regiao_sel)
        
        zones = []
        for p in parkings:
            diff = p.get("bikes_count", 0) - p.get("target_bikes_count", 0)
            if diff != 0 and ponto_dentro_da_regiao(p["latitude"], p["longitude"], reg_info):
                zones.append({"name": p.get("name", "Ponto"), "lat": p["latitude"], "lng": p["longitude"], "diff": diff})

        pool = [dict(z) for z in zones]
        route = []
        carrying = 0
        current = {"lat": lat, "lng": lng, "name": "INÍCIO"}
        total_delivered = 0

        while len(route) < 100:
            if total_delivered >= meta: break
            has_surplus = any(z["diff"] > 0 for z in pool)
            if carrying == 0 and not has_surplus: break

            if carrying > 0:
                targets = [z for z in pool if z["diff"] < 0]
                if not targets: break
                targets.sort(key=lambda z: haversine(current["lat"], current["lng"], z["lat"], z["lng"]))
                t = targets[0]
                qty = min(carrying, -t["diff"], meta - total_delivered)
                if qty <= 0: break
                dist = haversine(current["lat"], current["lng"], t["lat"], t["lng"])
                route.append({"action": "DEIXAR", "qty": qty, "name": t["name"], "coords": (t["lat"], t["lng"]), "dist": dist})
                t["diff"] += qty
                carrying -= qty
                total_delivered += qty
                current = {"lat": t["lat"], "lng": t["lng"], "name": t["name"]}
            else:
                targets = [z for z in pool if z["diff"] > 0]
                if not targets: break
                targets.sort(key=lambda z: haversine(current["lat"], current["lng"], z["lat"], z["lng"]))
                t = targets[0]
                qty = min(cap, t["diff"], meta - total_delivered)
                if qty <= 0: break
                dist = haversine(current["lat"], current["lng"], t["lat"], t["lng"])
                route.append({"action": "PEGAR", "qty": qty, "name": t["name"], "coords": (t["lat"], t["lng"]), "dist": dist})
                t["diff"] -= qty
                carrying += qty
                current = {"lat": t["lat"], "lng": t["lng"], "name": t["name"]}

        if route:
            dist_total = sum(r["dist"] for r in route)
            tempo_est = math.ceil((dist_total / 12.0) * 60.0 + (total_delivered * 2.0))
            
            st.session_state.rota_gerada = True
            st.session_state.route_data = route
            st.session_state.total_delivered = total_delivered
            st.session_state.dist_total = dist_total
            st.session_state.tempo_est = tempo_est
            st.session_state.start_lat = lat
            st.session_state.start_lng = lng
        else:
            st.warning("Nenhuma rota encontrada para essa região no momento.")
            st.session_state.rota_gerada = False

if st.session_state.rota_gerada:
    total_deliv = st.session_state.total_delivered
    dist_total = st.session_state.dist_total
    tempo_est = st.session_state.tempo_est
    route = st.session_state.route_data
    s_lat = st.session_state.start_lat
    s_lng = st.session_state.start_lng

    st.success(f"✅ Rota Gerada! Total: {total_deliv} patinetes | R$ {total_deliv * 1.50:.2f}")
    st.info(f"📏 Distância: {dist_total:.2f} km | ⏱️ Tempo Est.: ~{tempo_est} min")

    m = folium.Map(location=[s_lat, s_lng], zoom_start=14)
    folium.CircleMarker([s_lat, s_lng], radius=9, color="green", fill=True, popup="Início").add_to(m)
    
    path = [[s_lat, s_lng]]
    for idx, r in enumerate(route, 1):
        path.append(r["coords"])
        cor = "blue" if r["action"] == "PEGAR" else "red"
        folium.CircleMarker(r["coords"], radius=8, color=cor, fill=True, 
                            popup=f"{idx}. {r['action']} {r['qty']} em {r['name']}").add_to(m)

    folium.PolyLine(path, color="purple", weight=4).add_to(m)
    
    # Renderiza o mapa maior, usando a largura da tela e evitando recarregamentos extras com returned_objects
    st_folium(m, use_container_width=True, height=500, returned_objects=[])

    st.divider()
    
    # Mostra os passos em formato de texto estruturado
    st.subheader("📍 Passo a Passo da Rota")
    for idx, r in enumerate(route, 1):
        if r["action"] == "PEGAR":
            st.write(f"**{idx}. 🟢 PEGAR** {r['qty']} patinete(s) em **{r['name']}**")
        else:
            st.write(f"**{idx}. 🔴 DEIXAR** {r['qty']} patinete(s) em **{r['name']}**")
