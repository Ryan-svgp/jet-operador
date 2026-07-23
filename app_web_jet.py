import math
import os
import csv
import requests
import folium
import pandas as pd
from datetime import date, datetime
from urllib.parse import quote
import streamlit as st
from streamlit_folium import st_folium

API = "https://logistic.gojet.app/api/v0/urent"
CITY_ID = "6787b812c168def1b2c6d143"
REGISTROS_CSV = os.path.join(os.path.dirname(__file__), "registros.csv")

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

@st.cache_data(ttl=60, show_spinner=False)
def fetch_all_pages(endpoint):
    all_entries = []
    page = 1
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
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
            st.error(f"A API retornou uma resposta inválida. O servidor pode estar bloqueando conexões.")
            break
            
    return all_entries

def zonas_soltos(bikes, grid=0.0015):
    """Agrupa patinetes sem parking_id (soltos na rua) em zonas por proximidade,
    pra nao virar uma zona por patinete individual. grid=0.0015 graus ~ 150m."""
    grupos = {}
    for b in bikes:
        if b.get("parking_id"):
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
            "diff": len(pts)
        })
    return zonas


def maps_link(lat, lng):
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}&travelmode=driving"


def carregar_registros():
    if not os.path.exists(REGISTROS_CSV):
        return []
    with open(REGISTROS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def salvar_registro(data_str, qtd, ganho):
    novo = not os.path.exists(REGISTROS_CSV)
    with open(REGISTROS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if novo:
            writer.writerow(["Data", "Patinetes", "Ganhos (R$)"])
        writer.writerow([data_str, qtd, f"{ganho:.2f}"])


def ordenar_por_distancia(current, targets):
    """Ordena 'targets' pela distancia em linha reta ate a posicao atual."""
    for t in targets:
        d_km = haversine(current["lat"], current["lng"], t["lat"], t["lng"])
        t["_dist_km"] = d_km
        t["_dur_min"] = (d_km / 20.0) * 60.0  # estimativa: 20km/h medio urbano, so pra exibir tempo
    targets.sort(key=lambda z: z["_dist_km"])
    return targets


def gerar_rota(lat, lng, meta, cap, regiao_sel, incluir_soltos):
    """Busca dados frescos e monta a rota otimizada. Reaproveitada tanto pelo
    botao principal quanto pelo botao de recalcular."""
    parkings = fetch_all_pages("parkings")
    reg_info = REGIOES_DF.get(regiao_sel)

    zones = []
    for p in parkings:
        diff = p.get("bikes_count", 0) - p.get("target_bikes_count", 0)
        if diff != 0 and ponto_dentro_da_regiao(p["latitude"], p["longitude"], reg_info):
            zones.append({"name": p.get("name", "Ponto"), "lat": p["latitude"], "lng": p["longitude"], "diff": diff})

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
            targets = ordenar_por_distancia(current, targets)
            t = targets[0]
            qty = min(carrying, -t["diff"], meta - total_delivered)
            if qty <= 0:
                break
            route.append({"action": "DEIXAR", "qty": qty, "name": t["name"], "coords": (t["lat"], t["lng"]),
                          "dist": t["_dist_km"], "duracao_min": t["_dur_min"]})
            t["diff"] += qty
            carrying -= qty
            total_delivered += qty
            current = {"lat": t["lat"], "lng": t["lng"], "name": t["name"]}
        else:
            targets = [z for z in pool if z["diff"] > 0]
            if not targets:
                break
            targets = ordenar_por_distancia(current, targets)
            t = targets[0]
            qty = min(cap, t["diff"], meta - total_delivered)
            if qty <= 0:
                break
            route.append({"action": "PEGAR", "qty": qty, "name": t["name"], "coords": (t["lat"], t["lng"]),
                          "dist": t["_dist_km"], "duracao_min": t["_dur_min"]})
            t["diff"] -= qty
            carrying += qty
            current = {"lat": t["lat"], "lng": t["lng"], "name": t["name"]}

    dist_total = sum(r["dist"] for r in route)
    tempo_est = math.ceil(sum(r["duracao_min"] for r in route) + total_delivered * 1.0)
    return route, total_delivered, dist_total, tempo_est


# ==========================================
# Configuração da Página
# ==========================================
st.set_page_config(page_title="JET Logística Mobile", layout="wide") # Layout wide ajuda a colocar lado a lado
st.title("🚀 Operador JET DF")

# Inicializa memórias da sessão
if 'rota_gerada' not in st.session_state: st.session_state.rota_gerada = False
if 'registros' not in st.session_state: st.session_state.registros = carregar_registros()

# Criando as Abas de navegação
tab_rotas, tab_scanner, tab_registros, tab_bateria = st.tabs(
    ["🗺️ Gerador de Rotas", "📡 Scanner de Regiões", "📅 Registros Diários", "🔋 Trocar Bateria"]
)

# ==========================================
# ABA 1: GERADOR DE ROTAS
# ==========================================
with tab_rotas:
    regiao_sel = st.selectbox("Selecione a Região:", list(REGIOES_DF.keys()))
    coords_padrao = REGIOES_CENTRO.get(regiao_sel, (-15.7939, -47.8828))

    col1, col2 = st.columns(2)
    with col1:
        lat = st.number_input("Latitude Inicial", value=coords_padrao[0], format="%.4f")
        cap = st.number_input("Capacidade da Viagem", value=3, step=1)
    with col2:
        lng = st.number_input("Longitude Inicial", value=coords_padrao[1], format="%.4f")
        meta = st.number_input("Meta de Patinetes", value=20, step=1)

    incluir_soltos = st.checkbox("Incluir patinetes soltos na rua (fora de estacionamento oficial)", value=True)

    if st.button("🔥 Gerar Rota Otimizada", use_container_width=True):
        with st.spinner("Buscando dados da JET..."):
            route, total_delivered, dist_total, tempo_est = gerar_rota(
                lat, lng, meta, cap, regiao_sel, incluir_soltos
            )

            if route:
                st.session_state.rota_gerada = True
                st.session_state.route_data = route
                st.session_state.total_delivered = total_delivered
                st.session_state.dist_total = dist_total
                st.session_state.tempo_est = tempo_est
                st.session_state.start_lat = lat
                st.session_state.start_lng = lng
                st.session_state.passo_feito = [False] * len(route)
                st.session_state.entregues_sessao = 0
                st.session_state.contados_sessao = set()
            else:
                st.warning("Nenhuma rota encontrada para essa região no momento.")
                st.session_state.rota_gerada = False

    if st.session_state.rota_gerada:
        st.success(f"✅ Rota Gerada! Total: {st.session_state.total_delivered} patinetes | R$ {st.session_state.total_delivered * 1.50:.2f}")
        st.info(f"📏 Distância (linha reta): {st.session_state.dist_total:.2f} km | ⏱️ Tempo Est.: ~{st.session_state.tempo_est} min")

        # Layout em Colunas: Mapa de um lado, Passos do outro
        col_mapa, col_passos = st.columns([1.5, 1])

        with col_mapa:
            m = folium.Map(location=[st.session_state.start_lat, st.session_state.start_lng], zoom_start=14)
            folium.CircleMarker([st.session_state.start_lat, st.session_state.start_lng], radius=9, color="green", fill=True, popup="Início").add_to(m)
            
            path = [[st.session_state.start_lat, st.session_state.start_lng]]
            for idx, r in enumerate(st.session_state.route_data, 1):
                path.append(r["coords"])
                cor = "blue" if r["action"] == "PEGAR" else "red"
                folium.CircleMarker(r["coords"], radius=8, color=cor, fill=True, 
                                    popup=f"{idx}. {r['action']}").add_to(m)

            folium.PolyLine(path, color="purple", weight=4).add_to(m)
            st_folium(m, use_container_width=True, height=450, returned_objects=[])

        with col_passos:
            st.subheader("📍 Passo a Passo")
            for idx, r in enumerate(st.session_state.route_data, 1):
                lk = maps_link(*r["coords"])
                i = idx - 1
                acao_txt = "🟢 PEGAR" if r["action"] == "PEGAR" else "🔴 DEIXAR"
                col_chk, col_txt = st.columns([0.15, 0.85])
                with col_chk:
                    feito = st.checkbox("", key=f"passo_{idx}", value=st.session_state.passo_feito[i])
                with col_txt:
                    st.markdown(
                        f"**{idx}. {acao_txt}** {r['qty']} patinete(s) em {r['name']}  \n"
                        f"~{r['duracao_min']:.0f} min / {r['dist']:.2f} km até aqui  \n"
                        f"[🧭 Abrir rota no Maps]({lk})"
                    )
                # conta pro progresso da sessao so na primeira vez que marca
                if feito and not st.session_state.passo_feito[i]:
                    st.session_state.passo_feito[i] = True
                    if r["action"] == "DEIXAR" and idx not in st.session_state.contados_sessao:
                        st.session_state.entregues_sessao += r["qty"]
                        st.session_state.contados_sessao.add(idx)
                elif not feito and st.session_state.passo_feito[i]:
                    st.session_state.passo_feito[i] = False
                    if idx in st.session_state.contados_sessao:
                        st.session_state.entregues_sessao -= r["qty"]
                        st.session_state.contados_sessao.discard(idx)
                st.divider()

            concluidos = sum(st.session_state.passo_feito)
            st.caption(f"{concluidos}/{len(st.session_state.route_data)} passos concluídos nesta rota · "
                       f"{st.session_state.entregues_sessao} patinetes já entregues na sessão")

            st.markdown("**Patinete sumiu do lugar ou já foi pego por outro operador?** "
                        "Atualize sua latitude/longitude lá em cima pra sua posição atual e recalcule:")
            if st.button("🔄 Recalcular com dados atualizados (mantém progresso da sessão)", use_container_width=True):
                with st.spinner("Buscando dados frescos e recalculando..."):
                    meta_restante = max(meta - st.session_state.entregues_sessao, 1)
                    route, total_delivered, dist_total, tempo_est = gerar_rota(
                        lat, lng, meta_restante, cap, regiao_sel, incluir_soltos
                    )
                    if route:
                        st.session_state.route_data = route
                        st.session_state.total_delivered = total_delivered
                        st.session_state.dist_total = dist_total
                        st.session_state.tempo_est = tempo_est
                        st.session_state.start_lat = lat
                        st.session_state.start_lng = lng
                        st.session_state.passo_feito = [False] * len(route)
                        st.session_state.contados_sessao = set()
                        st.rerun()
                    else:
                        st.warning("Nada de novo pra rebalancear por aqui agora — pode ser que a região tenha zerado.")


# ==========================================
# ABA 2: SCANNER DE REGIÕES
# ==========================================
with tab_scanner:
    st.header("📡 Scanner de Oportunidades")
    st.write("Verifique qual região tem a maior demanda de remanejamento agora.")
    
    if st.button("🔍 Escanear Todas as Regiões", use_container_width=True):
        with st.spinner("Analisando todas as zonas do DF..."):
            parkings = fetch_all_pages("parkings")
            resultados = []

            for nome_regiao, reg_info in REGIOES_DF.items():
                if nome_regiao == "Personalizado (Apenas Raio)":
                    continue
                
                sobrando = 0 # Patinetes que precisam ser pegos
                faltando = 0 # Vagas precisando de patinetes

                for p in parkings:
                    if ponto_dentro_da_regiao(p["latitude"], p["longitude"], reg_info):
                        diff = p.get("bikes_count", 0) - p.get("target_bikes_count", 0)
                        if diff > 0:
                            sobrando += diff
                        elif diff < 0:
                            faltando += abs(diff)
                
                # O potencial real de trabalho é o menor número entre o que sobra e o que falta
                potencial_tarefas = min(sobrando, faltando)
                resultados.append({
                    "Região": nome_regiao,
                    "Patinetes Sobrando (Pegar)": sobrando,
                    "Vagas Abertas (Deixar)": faltando,
                    "Potencial Máximo (Tarefas)": potencial_tarefas
                })

            df_resultados = pd.DataFrame(resultados)
            # Ordenar pela região com mais potencial de tarefas
            df_resultados = df_resultados.sort_values(by="Potencial Máximo (Tarefas)", ascending=False).reset_index(drop=True)
            
            st.dataframe(df_resultados, use_container_width=True)
            
            melhor = df_resultados.iloc[0]
            if melhor["Potencial Máximo (Tarefas)"] > 0:
                st.success(f"🏆 A melhor região para faturar agora é **{melhor['Região']}**, com potencial para **{melhor['Potencial Máximo (Tarefas)']}** remanejamentos completos!")
            else:
                st.warning("O mapa parece estar equilibrado agora. Nenhuma grande oportunidade detectada.")


# ==========================================
# ABA 3: REGISTROS DIÁRIOS (CALENDÁRIO)
# ==========================================
with tab_registros:
    st.header("📅 Registros de Trabalho")
    st.caption("Os registros ficam salvos num arquivo no servidor (sobrevivem a fechar o navegador). "
               "Se o app for redeployado do zero no Streamlit Cloud, esse arquivo pode ser resetado — "
               "por isso o botão de exportar CSV abaixo é seu backup pessoal.")

    meta_mensal = st.number_input("🎯 Meta mensal (R$)", value=4000.0, step=100.0)

    with st.form("form_registro"):
        col_data, col_qtd, col_add = st.columns([2, 2, 1])
        with col_data:
            data_reg = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")
        with col_qtd:
            qtd_patinetes = st.number_input("Patinetes Remanejados", min_value=1, step=1)
        with col_add:
            st.write("") # Espaçamento
            st.write("") # Espaçamento
            submit_reg = st.form_submit_button("Salvar")

        if submit_reg:
            ganho = qtd_patinetes * 1.50
            data_str = data_reg.strftime("%d/%m/%Y")
            salvar_registro(data_str, qtd_patinetes, ganho)
            st.session_state.registros.append({
                "Data": data_str,
                "Patinetes": str(qtd_patinetes),
                "Ganhos (R$)": f"{ganho:.2f}"
            })
            st.success("Registro salvo!")

    if st.session_state.registros:
        df_registros = pd.DataFrame(st.session_state.registros)
        df_registros["Patinetes"] = pd.to_numeric(df_registros["Patinetes"], errors="coerce").fillna(0)
        df_registros["Ganhos (R$)"] = pd.to_numeric(df_registros["Ganhos (R$)"], errors="coerce").fillna(0)
        df_registros["_data_dt"] = pd.to_datetime(df_registros["Data"], format="%d/%m/%Y", errors="coerce")

        st.dataframe(
            df_registros[["Data", "Patinetes", "Ganhos (R$)"]],
            use_container_width=True
        )

        st.download_button(
            "⬇️ Exportar CSV",
            data=df_registros[["Data", "Patinetes", "Ganhos (R$)"]].to_csv(index=False).encode("utf-8"),
            file_name="registros_jet.csv",
            mime="text/csv"
        )

        # Total geral
        total_p = int(df_registros["Patinetes"].sum())
        total_r = df_registros["Ganhos (R$)"].sum()
        st.info(f"💰 **Total Acumulado (histórico):** {total_p} patinetes | **R$ {total_r:.2f}**")

        # Progresso do mês atual
        hoje = datetime.today()
        do_mes = df_registros[
            (df_registros["_data_dt"].dt.month == hoje.month) &
            (df_registros["_data_dt"].dt.year == hoje.year)
        ]
        ganho_mes = do_mes["Ganhos (R$)"].sum()
        patinetes_mes = int(do_mes["Patinetes"].sum())
        pct = min(ganho_mes / meta_mensal, 1.0) if meta_mensal > 0 else 0

        st.subheader(f"🎯 Progresso de {hoje.strftime('%B/%Y')}")
        st.progress(pct)
        faltam = max(meta_mensal - ganho_mes, 0)
        dias_no_mes = hoje.day
        dias_restantes = max(
            (date(hoje.year, hoje.month % 12 + 1, 1) - date.today()).days
            if hoje.month < 12 else (date(hoje.year + 1, 1, 1) - date.today()).days,
            1
        )
        st.write(
            f"**R$ {ganho_mes:.2f}** de **R$ {meta_mensal:.2f}** ({pct*100:.0f}%) — "
            f"{patinetes_mes} patinetes até agora. "
            f"Faltam **R$ {faltam:.2f}** (~{math.ceil(faltam/1.5) if faltam > 0 else 0} patinetes) "
            f"em {dias_restantes} dias restantes no mês "
            f"(~R$ {faltam/dias_restantes:.2f}/dia se dividir igual)."
        )
    else:
        st.write("Nenhum registro ainda. Adicione o primeiro acima.")


# ==========================================
# ABA 4: TROCAR BATERIA
# ==========================================
with tab_bateria:
    st.header("🔋 Achar Patinete com Bateria Alta Pra Trocar")
    st.write("Regra do treinamento: se um patinete que você está mexendo está com bateria baixa "
             "(~40% ou menos), troca a bateria dele por uma de um patinete próximo com bateria alta "
             "(90%+). Essa aba só acha o patinete carregado mais perto de você — a troca em si é manual.")

    col_a, col_b = st.columns(2)
    with col_a:
        lat_bat = st.number_input("Sua latitude atual", value=-15.8000, format="%.4f", key="lat_bat")
        limite_bateria = st.slider("Bateria mínima desejada (%)", min_value=50, max_value=100, value=90, step=5)
    with col_b:
        lng_bat = st.number_input("Sua longitude atual", value=-47.8950, format="%.4f", key="lng_bat")
        qtd_resultados = st.number_input("Quantos mostrar", min_value=1, max_value=15, value=5, step=1)

    if st.button("🔍 Achar patinete com bateria alta mais próximo", use_container_width=True):
        with st.spinner("Buscando patinetes..."):
            bikes = fetch_all_pages("bikes")
            candidatos = []
            for b in bikes:
                bat_raw = b.get("battery_percent")
                lat_b, lng_b = b.get("location_lat"), b.get("location_lng")
                if bat_raw is None or lat_b is None or lng_b is None:
                    continue
                bat = round(bat_raw * 100)  # a API manda 0-1 (ex: 0.46), convertendo pra 0-100
                if bat < limite_bateria:
                    continue
                dist = haversine(lat_bat, lng_bat, lat_b, lng_b)
                candidatos.append({
                    "identificador": b.get("identifier", "sem id"),
                    "bateria": bat,
                    "lat": lat_b,
                    "lng": lng_b,
                    "dist_km": dist
                })

            candidatos.sort(key=lambda c: c["dist_km"])
            candidatos = candidatos[:qtd_resultados]

            if not candidatos:
                st.warning(f"Nenhum patinete com {limite_bateria}%+ de bateria encontrado. Tente diminuir o mínimo.")
            else:
                for i, c in enumerate(candidatos, 1):
                    lk = maps_link(c["lat"], c["lng"])
                    st.markdown(
                        f"**{i}. {c['identificador']}** — 🔋 {c['bateria']}% — "
                        f"📍 {c['dist_km']:.2f} km em linha reta  \n[🧭 Abrir no Maps]({lk})"
                    )
                    st.divider()
